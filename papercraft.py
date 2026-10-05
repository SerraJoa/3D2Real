"""Nucli del desplegament: malla 3D → peces planes → pestanyes → pàgines SVG.

Unitats: tot en mil·límetres un cop la malla s'ha escalat amb `scale_to`.
Coordenades 2D de les peces: eix y cap amunt, vistes des de fora del volum.
"""
from __future__ import annotations

import heapq
import io
import math
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
import trimesh
from shapely.geometry import LineString, MultiPoint, Polygon
from shapely import affinity
from shapely.ops import unary_union

PAGES = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "Carta": (215.9, 279.4)}

MARGIN = 10.0  # mm de marge de pàgina

# Fracció de l'àrea d'un polígon que es tolera com a solapament numèric.
OVERLAP_TOL = 1e-4


# ---------------------------------------------------------------- malla

def load_mesh(data: bytes, name: str) -> trimesh.Trimesh:
    kind = Path(name).suffix.lower().lstrip(".")
    obj = trimesh.load(io.BytesIO(data), file_type=kind, force="scene")
    meshes = [g for g in obj.geometry.values() if isinstance(g, trimesh.Trimesh)]
    if not meshes:
        raise ValueError("No s'ha trobat cap malla.")
    mesh = trimesh.util.concatenate(meshes)
    return clean(mesh)


def clean(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    mesh = mesh.copy()
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    return mesh


def simplify(mesh: trimesh.Trimesh, target: int) -> trimesh.Trimesh:
    if len(mesh.faces) <= target:
        return mesh.copy()
    for args in (dict(face_count=target), dict(target_faces=target)):
        try:
            return clean(mesh.simplify_quadric_decimation(**args))
        except TypeError:
            continue
    raise RuntimeError("Cal una versió de trimesh amb simplificació quadric (fast-simplification).")


def scale_to(mesh: trimesh.Trimesh, size_mm: float) -> trimesh.Trimesh:
    """Escala la malla perquè la seva dimensió més gran faci `size_mm`."""
    out = mesh.copy()
    out.apply_scale(size_mm / float(max(out.extents)))
    return out


def edge_faces(faces: np.ndarray) -> dict[tuple[int, int], list[int]]:
    em: dict[tuple[int, int], list[int]] = {}
    for fi, f in enumerate(faces):
        for i in range(3):
            a, b = int(f[i]), int(f[(i + 1) % 3])
            em.setdefault((min(a, b), max(a, b)), []).append(fi)
    return em


# ---------------------------------------------------------------- geometria 2D

def _cross(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _apex(A: np.ndarray, B: np.ndarray, L0: float, L1: float, side: int) -> np.ndarray | None:
    """Tercer vèrtex a distància L0 d'A i L1 de B, a l'esquerra (side=1) o dreta (-1) d'AB."""
    d = float(np.linalg.norm(B - A))
    if d < 1e-9:
        return None
    x = (L0 * L0 - L1 * L1 + d * d) / (2 * d)
    h = math.sqrt(max(L0 * L0 - x * x, 0.0))
    u = (B - A) / d
    return A + u * x + np.array([-u[1], u[0]]) * h * side


def _root_coords(V: np.ndarray, f: np.ndarray) -> np.ndarray:
    a, b, c = V[f]
    A = np.zeros(2)
    B = np.array([np.linalg.norm(b - a), 0.0])
    C = _apex(A, B, float(np.linalg.norm(c - a)), float(np.linalg.norm(c - b)), 1)
    return np.array([A, B, C])


def _child_coords(V, F, parent: int, pc: np.ndarray, child: int, e) -> np.ndarray | None:
    """Gira la cara `child` al voltant de l'aresta `e` fins al pla de la cara `parent`."""
    f = [int(x) for x in F[parent]]
    i0, i1 = f.index(e[0]), f.index(e[1])
    A, B, P = pc[i0], pc[i1], pc[3 - i0 - i1]
    g = [int(x) for x in F[child]]
    k = next(v for v in g if v not in e)
    side = -1 if _cross(B - A, P - A) > 0 else 1  # costat oposat al pare
    C = _apex(A, B, float(np.linalg.norm(V[k] - V[e[0]])), float(np.linalg.norm(V[k] - V[e[1]])), side)
    if C is None:
        return None
    return np.array([A if v == e[0] else B if v == e[1] else C for v in g])


class _Shapes:
    """Polígons d'una peça amb prefiltre per capsa per detectar solapaments."""

    def __init__(self):
        self.polys: list[Polygon] = []
        self.bounds = np.empty((0, 4))

    def near(self, poly: Polygon) -> np.ndarray:
        if not self.polys:
            return np.empty(0, dtype=int)
        x0, y0, x1, y1 = poly.bounds
        b = self.bounds
        return np.nonzero((b[:, 0] < x1) & (b[:, 2] > x0) & (b[:, 1] < y1) & (b[:, 3] > y0))[0]

    def hits(self, poly: Polygon) -> bool:
        for i in self.near(poly):
            other = self.polys[i]
            tol = OVERLAP_TOL * min(poly.area, other.area) + 1e-9
            if poly.intersection(other).area > tol:
                return True
        return False

    def add(self, poly: Polygon) -> int:
        self.polys.append(poly)
        self.bounds = np.vstack([self.bounds, poly.bounds])
        return len(self.polys) - 1

    def replace(self, i: int, poly) -> None:
        self.polys[i] = poly
        self.bounds[i] = poly.bounds


# ---------------------------------------------------------------- desplegament

@dataclass
class Tab:
    """Pestanya d'una aresta AB: un trapezi, o diverses dents si s'ha dentat."""
    A: np.ndarray
    B: np.ndarray
    polys: list[np.ndarray]
    full_area: float          # àrea de la pestanya sencera, per comparar
    shape: int = -1           # índex a Piece.shapes

    def geom(self):
        return unary_union([Polygon(q) for q in self.polys])


@dataclass
class Piece:
    tris: dict[int, np.ndarray] = field(default_factory=dict)       # cara → 3×2
    folds: dict[tuple[int, int], str] = field(default_factory=dict)  # aresta → "vall"/"muntanya"
    tabs: list[Tab] = field(default_factory=list)
    labels: list[tuple[np.ndarray, str, float]] = field(default_factory=list)
    cuts: list[np.ndarray] = field(default_factory=list)            # segments 2×2
    fold_lines: list[tuple[np.ndarray, str]] = field(default_factory=list)
    shapes: _Shapes = field(default_factory=_Shapes, repr=False)
    shape_of: dict[int, int] = field(default_factory=dict, repr=False)  # cara → índex a shapes
    tab_of: dict[int, Tab] = field(default_factory=dict, repr=False)    # índex a shapes → pestanya

    def place(self, fi: int, coords: np.ndarray, poly: Polygon) -> None:
        self.tris[fi] = coords
        self.shape_of[fi] = self.shapes.add(poly)

    def add_tab(self, tab: Tab) -> None:
        tab.shape = self.shapes.add(tab.geom())
        self.tab_of[tab.shape] = tab
        self.tabs.append(tab)

    def tab_polys(self) -> list[np.ndarray]:
        return [q for t in self.tabs for q in t.polys]

    def points(self) -> np.ndarray:
        pts = list(self.tris.values()) + self.tab_polys()
        return np.vstack(pts)

    def transform(self, fn) -> None:
        self.tris = {k: fn(v) for k, v in self.tris.items()}
        for t in self.tabs:
            t.A, t.B = fn(t.A[None])[0], fn(t.B[None])[0]
            t.polys = [fn(q) for q in t.polys]
        self.labels = [(fn(p[None])[0], s, z) for p, s, z in self.labels]
        self.cuts = [fn(c) for c in self.cuts]
        self.fold_lines = [(fn(c), k) for c, k in self.fold_lines]


# Arestes amb un angle de plec menor que aquest (radians) es consideren planes.
FLAT_ANGLE = math.radians(0.5)


def fold_kind(mesh: trimesh.Trimesh, a: int, b: int) -> str:
    """Muntanya si l'aresta és convexa vista des de fora, vall si és còncava, pla si no plega."""
    n = mesh.face_normals
    if float(np.dot(n[a], n[b])) >= math.cos(FLAT_ANGLE):
        return "pla"
    d = mesh.triangles_center[b] - mesh.triangles_center[a]
    return "muntanya" if float(np.dot(n[a], d)) < 0 else "vall"


def _fits(lo: np.ndarray, hi: np.ndarray, max_size: tuple[float, float] | None) -> bool:
    if max_size is None:
        return True
    w, h = sorted(hi - lo)
    return w <= min(max_size) and h <= max(max_size)


# Pes de la distància al centre de la peça respecte de l'angle de plec a l'hora
# de decidir quina cara s'afegeix. Més alt → peces més rodones i menys punxegudes.
COMPACT = 0.05

# Si en tancar el ventall d'un vèrtex les dues vores d'una aresta queden a menys
# d'aquesta distància (mm), l'aresta es plega en lloc de tallar-la.
FOLD_SNAP = 0.3


def flat_patches(mesh: trimesh.Trimesh, em, region: np.ndarray | None = None) -> np.ndarray:
    """Agrupa les cares coplanars connectades: cada grup es desplega sencer o gens.

    Amb `region`, dues cares de regions diferents mai no van al mateix grup.
    """
    parent = list(range(len(mesh.faces)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for fs in em.values():
        if len(fs) == 2 and fold_kind(mesh, fs[0], fs[1]) == "pla" and (
                region is None or region[fs[0]] == region[fs[1]]):
            parent[find(fs[0])] = find(fs[1])
    return np.array([find(i) for i in range(len(mesh.faces))])


def unfold(mesh: trimesh.Trimesh, max_size: tuple[float, float] | None = None,
           tab_mm: float = 0.0, region: np.ndarray | None = None
           ) -> tuple[list[Piece], np.ndarray]:
    """Desplega la malla en peces sense solapaments.

    Cada peça creix des de la zona plana més gran que queda lliure. Primer s'hi
    afegeixen les zones que pleguen per arestes més planes i més properes al centre
    de la peça. Una zona que solaparia la peça, o que la faria més gran que
    `max_size` (mm), no s'hi afegeix per aquella aresta (queda com a costura) i
    acaba en una altra peça.

    Amb `tab_mm` > 0 es reserva, a cada aresta lliure, l'espai d'una pestanya: cap
    cara nova no hi pot caure. Així no es formen escletxes sense lloc per enganxar.

    Amb `region` (una etiqueta per cara), les arestes entre regions diferents sempre
    són costures: cada peça queda dins d'una sola regió.
    """
    V, F, N = mesh.vertices, mesh.faces, mesh.face_normals
    em = edge_faces(F)
    patch = flat_patches(mesh, em, region)
    members: dict[int, list[int]] = {}
    for fi, pid in enumerate(patch):
        members.setdefault(int(pid), []).append(fi)
    neigh: list[list[tuple[float, int, tuple[int, int]]]] = [[] for _ in F]
    for e, fs in em.items():
        if len(fs) == 2 and (region is None or region[fs[0]] == region[fs[1]]):
            a, b = fs
            w = float(np.arccos(np.clip(np.dot(N[a], N[b]), -1.0, 1.0)))
            neigh[a].append((w, b, e))
            neigh[b].append((w, a, e))
    unit = float(mesh.edges_unique_length.mean()) if len(mesh.edges_unique) else 1.0
    patch_area = {pid: float(mesh.area_faces[fs].sum()) for pid, fs in members.items()}

    owner = np.full(len(F), -1)
    pieces: list[Piece] = []
    counter = 0
    for root in sorted(range(len(F)), key=lambda f: (-patch_area[int(patch[f])], -mesh.area_faces[f])):
        if owner[root] >= 0:
            continue
        piece = Piece()
        idx = len(pieces)
        pieces.append(piece)
        heap: list = []
        zones = _Shapes()
        zone_of: dict[tuple[int, tuple[int, int]], int] = {}
        freed: set[int] = set()
        box = [None, None]

        def grow_patch(start: int, coords: np.ndarray):
            """Coordenades de tota la zona plana de `start`, desplegada des d'ella."""
            pid = int(patch[start])
            placed = {start: coords}
            todo = [start]
            while todo:
                f = todo.pop()
                for w, nb, e in neigh[f]:
                    if patch[nb] != pid or nb in placed or owner[nb] >= 0:
                        continue
                    cc = _child_coords(V, F, f, placed[f], nb, e)
                    if cc is None:
                        continue
                    placed[nb] = cc
                    todo.append(nb)
            return placed

        def closing(group: dict[int, np.ndarray]) -> list[tuple[int, int, tuple[int, int]]]:
            """Arestes del grup que ja toquen una cara de la peça sobre el paper."""
            out = []
            for fi, cc in group.items():
                g = [int(x) for x in F[fi]]
                for w, nb, e2 in neigh[fi]:
                    if owner[nb] != idx:
                        continue
                    f = [int(x) for x in F[nb]]
                    if all(np.linalg.norm(cc[g.index(v)] - piece.tris[nb][f.index(v)]) <= FOLD_SNAP
                           for v in e2):
                        out.append((nb, fi, e2))
            return out

        def blocked(group: dict[int, np.ndarray], polys, shut) -> bool:
            own = {zone_of.get((nb, e2)) for nb, _, e2 in shut}
            for poly in polys:
                if not poly.is_valid or piece.shapes.hits(poly):
                    return True
                for i in zones.near(poly):
                    if i in own or i in freed:
                        continue
                    z = zones.polys[i]
                    if poly.intersection(z).area > OVERLAP_TOL * z.area + 1e-9:
                        return True
            return False

        def commit(group: dict[int, np.ndarray], polys, shut) -> None:
            nonlocal counter
            for (fi, cc), poly in zip(group.items(), polys):
                piece.place(fi, cc, poly)
                owner[fi] = idx
            for nb, fi, e2 in shut:
                piece.folds[e2] = fold_kind(mesh, nb, fi)
                if (nb, e2) in zone_of:
                    freed.add(zone_of[(nb, e2)])
            for fi in group:  # arestes interiors de la zona plana
                for w, nb, e2 in neigh[fi]:
                    if nb in group and e2 not in piece.folds:
                        piece.folds[e2] = "pla"
            pts = np.vstack(list(group.values()))
            box[0] = pts.min(0) if box[0] is None else np.minimum(box[0], pts.min(0))
            box[1] = pts.max(0) if box[1] is None else np.maximum(box[1], pts.max(0))
            for fi, cc in group.items():
                for w, nb, e2 in neigh[fi]:
                    if e2 in piece.folds:
                        continue
                    if tab_mm > 0:
                        A, B, C = _edge_in_face(F, fi, cc, e2)
                        zone_of[(fi, e2)] = zones.add(Polygon(tab_polygon(A, B, C, tab_mm)))
                    if owner[nb] >= 0:
                        continue
                    ncc = _child_coords(V, F, fi, cc, nb, e2)
                    if ncc is None:
                        continue
                    d = float(np.linalg.norm(ncc.mean(0) - origin)) / unit
                    counter += 1
                    heapq.heappush(heap, (w + COMPACT * d, counter, fi, nb, e2, ncc))

        rc = _root_coords(V, F[root])
        origin = rc.mean(axis=0)
        group = grow_patch(root, rc)
        commit(group, [Polygon(c) for c in group.values()], [])
        while heap:
            _, _, parent, child, e, cc = heapq.heappop(heap)
            if owner[child] >= 0:
                continue
            group = grow_patch(child, cc)
            pts = np.vstack(list(group.values()))
            if not _fits(np.minimum(box[0], pts.min(0)), np.maximum(box[1], pts.max(0)), max_size):
                continue
            polys = [Polygon(c) for c in group.values()]
            shut = closing(group)
            if blocked(group, polys, shut):
                continue
            commit(group, polys, shut)
    return pieces, owner


def _seams_have_room(F, em, pieces, owner, tab_mm: float, Q: Piece, fi: int, cc: np.ndarray,
                     poly: Polygon, fold) -> bool:
    """Comprova que, si `fi` entra a `Q`, totes les seves costures tindran lloc per a una pestanya."""
    trial = Piece(tris={**Q.tris, fi: cc})
    for k, t in trial.tris.items():
        trial.shape_of[k] = trial.shapes.add(Polygon(t) if k != fi else poly)
    f = [int(x) for x in F[fi]]
    for i in range(3):
        e = tuple(sorted((f[i], f[(i + 1) % 3])))
        if e == fold or len(em[e]) != 2:
            continue
        h = next(x for x in em[e] if x != fi)
        A, B, C = _edge_in_face(F, fi, cc, e)
        if fit_tab(trial, fi, A, B, C, tab_mm) is not None:
            continue
        H = trial if h in trial.tris else pieces[owner[h]]
        A, B, C = _edge_in_face(F, h, H.tris[h], e)
        if fit_tab(H, h, A, B, C, tab_mm) is None:
            return False
    return True


SMALL_PIECE = 3  # peces amb aquestes cares o menys s'intenten reenganxar a una veïna


def absorb_small(mesh: trimesh.Trimesh, pieces: list[Piece], owner: np.ndarray,
                 max_size: tuple[float, float] | None = None, tab_mm: float = 5.0,
                 small: int = SMALL_PIECE, region: np.ndarray | None = None) -> tuple[list[Piece], np.ndarray]:
    """Enganxa les cares de peces molt petites a una peça veïna si no s'hi solapen.

    Les cares que tanquen el ventall d'un vèrtex corbat no tenen lloc per a una pestanya
    sencera i el desplegament les deixa soles. Val més una peça amb una pestanya
    retallada que un munt de triangles solts.
    """
    V, F = mesh.vertices, mesh.faces
    em = edge_faces(F)
    changed = True
    while changed:
        changed = False
        for idx in sorted(range(len(pieces)), key=lambda i: len(pieces[i].tris)):
            p = pieces[idx]
            if not 0 < len(p.tris) <= small:
                continue
            for fi in list(p.tris):
                done = False
                f = [int(x) for x in F[fi]]
                for i in range(3):
                    e = tuple(sorted((f[i], f[(i + 1) % 3])))
                    for g in em[e]:
                        q = owner[g]
                        if g == fi or q == idx or len(pieces[q].tris) <= len(p.tris):
                            continue
                        if region is not None and region[g] != region[fi]:
                            continue
                        Q = pieces[q]
                        cc = _child_coords(V, F, g, Q.tris[g], fi, e)
                        if cc is None:
                            continue
                        pts = np.vstack(list(Q.tris.values()) + [cc])
                        if not _fits(pts.min(axis=0), pts.max(axis=0), max_size):
                            continue
                        poly = Polygon(cc)
                        if not poly.is_valid or Q.shapes.hits(poly):
                            continue
                        if not _seams_have_room(F, em, pieces, owner, tab_mm, Q, fi, cc, poly, e):
                            continue
                        # Les arestes plegades dins de la peça petita es perden: es tornen costures.
                        for e2 in [k for k in p.folds if fi in em[k]]:
                            del p.folds[e2]
                        del p.tris[fi]
                        Q.place(fi, cc, poly)
                        Q.folds[e] = fold_kind(mesh, g, fi)
                        owner[fi] = q
                        done = changed = True
                        break
                    if done:
                        break
            if not p.tris:
                continue
            # Les cares que queden poden haver perdut la connexió: refem shapes.
            p.shapes, p.shape_of = _Shapes(), {}
            for fi, t in list(p.tris.items()):
                p.shape_of[fi] = p.shapes.add(Polygon(t))
    keep = [i for i, p in enumerate(pieces) if p.tris]
    remap = {old: new for new, old in enumerate(keep)}
    return [pieces[i] for i in keep], np.array([remap[o] for o in owner])


# ---------------------------------------------------------------- zones naturals

ZONE_MIN_SHARE = 0.02  # zones amb menys d'aquesta fracció de l'àrea s'uneixen a una veïna


def _dihedral(mesh: trimesh.Trimesh, a: int, b: int) -> float:
    n = mesh.face_normals
    return float(np.degrees(np.arccos(np.clip(np.dot(n[a], n[b]), -1.0, 1.0))))


def natural_zones(mesh: trimesh.Trimesh, angle_deg: float,
                  min_share: float = ZONE_MIN_SHARE) -> np.ndarray:
    """Parteix la superfície per les línies naturals: arestes que pleguen més de `angle_deg`.

    Retorna una etiqueta per cara. Les zones molt petites s'uneixen a la veïna amb qui
    comparteixen més vora, perquè no surtin peces minúscules.
    """
    em = edge_faces(mesh.faces)
    parent = list(range(len(mesh.faces)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    lines = []
    for e, fs in em.items():
        if len(fs) != 2:
            continue
        if _dihedral(mesh, fs[0], fs[1]) < angle_deg:
            parent[find(fs[0])] = find(fs[1])
        else:
            lines.append((e, fs[0], fs[1]))

    area = mesh.area_faces
    total = float(area.sum())
    length = {e: float(np.linalg.norm(mesh.vertices[e[0]] - mesh.vertices[e[1]])) for e, _, _ in lines}
    while True:
        zone = np.array([find(i) for i in range(len(parent))])
        z_area = {}
        for fi, z in enumerate(zone):
            z_area[z] = z_area.get(z, 0.0) + area[fi]
        small = [z for z, a in z_area.items() if a < min_share * total]
        if not small or len(z_area) == 1:
            break
        z = min(small, key=lambda k: z_area[k])
        border: dict[int, float] = {}
        for e, a, b in lines:
            za, zb = zone[a], zone[b]
            if za != zb and z in (za, zb):
                other = zb if za == z else za
                border[other] = border.get(other, 0.0) + length[e]
        if not border:  # zona aïllada (una altra component): la deixem
            parent[z] = z
            min_share = min(min_share, z_area[z] / total)
            continue
        parent[find(z)] = find(max(border, key=border.get))
    _, labels = np.unique(zone, return_inverse=True)
    return labels


def _rigid(src: np.ndarray, dst: np.ndarray):
    """Gir i translació (sense mirall) que porta els punts `src` sobre `dst`."""
    cs, cd = src.mean(0), dst.mean(0)
    H = (src - cs).T @ (dst - cd)
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1] *= -1
        R = Vt.T @ U.T
    return lambda x: (x - cs) @ R.T + cd


# Dues peces només s'uneixen si el casc convex de la unió no supera aquest factor
# per la suma dels seus cascos: evita peces escampades que omplen pàgines de buit.
MERGE_SPREAD = 2.0
# Per sota d'aquesta fracció de l'àrea imprimible, la unió no es considera escampada.
MERGE_FREE = 0.25


def _hull_area(pts: np.ndarray) -> float:
    return MultiPoint([tuple(p) for p in pts]).convex_hull.area


def merge_pieces(mesh: trimesh.Trimesh, pieces: list[Piece], owner: np.ndarray,
                 max_size: tuple[float, float] | None, tab_mm: float
                 ) -> tuple[list[Piece], np.ndarray]:
    """Torna a enganxar peces senceres entre elles per una costura, si encara hi caben.

    Prova primer les costures més planes. Una peça només s'enganxa a una altra si no s'hi
    solapa, la peça resultant cap al paper sense escampar-se massa (`MERGE_SPREAD`) i
    cada costura que queda tapada encara té lloc per a una pestanya.
    """
    V, F = mesh.vertices, mesh.faces
    em = edge_faces(F)
    changed = True
    while changed:
        changed = False
        cands = []
        for e, fs in em.items():
            if len(fs) == 2 and owner[fs[0]] != owner[fs[1]]:
                cands.append((_dihedral(mesh, *fs), e, fs[0], fs[1]))
        cands.sort(key=lambda c: c[0])
        for _, e, a, b in cands:
            P, Q = pieces[owner[a]], pieces[owner[b]]
            if len(P.tris) < len(Q.tris):
                a, b, P, Q = b, a, Q, P
            target = _child_coords(V, F, a, P.tris[a], b, e)
            if target is None:
                continue
            move = _rigid(Q.tris[b], target)
            moved = {fi: move(t) for fi, t in Q.tris.items()}
            pts = np.vstack(list(P.tris.values()) + list(moved.values()))
            if max_size is not None and _fit_angle(pts, *max_size) is None:
                continue
            hull = _hull_area(pts)
            if max_size is not None and hull > MERGE_FREE * max_size[0] * max_size[1] and \
                    hull > MERGE_SPREAD * (_hull_area(np.vstack(list(P.tris.values())))
                                           + _hull_area(np.vstack(list(moved.values())))):
                continue  # la peça unida s'escamparia (una X, una L llarga) i gastaria paper
            polys = {fi: Polygon(t) for fi, t in moved.items()}
            if any(P.shapes.hits(pl) for pl in polys.values()):
                continue

            # Arestes entre P i Q que ara coincideixen: també es pleguen.
            joined = {e: fold_kind(mesh, a, b)}
            for fi, t in moved.items():
                g = [int(x) for x in F[fi]]
                for i in range(3):
                    e2 = tuple(sorted((g[i], g[(i + 1) % 3])))
                    h = next((x for x in em[e2] if x != fi), None)
                    if h is None or h not in P.tris or e2 in joined:
                        continue
                    f = [int(x) for x in F[h]]
                    if all(np.linalg.norm(t[g.index(v)] - P.tris[h][f.index(v)]) <= FOLD_SNAP
                           for v in e2):
                        joined[e2] = fold_kind(mesh, h, fi)

            merged = Piece(tris={**P.tris, **moved})
            for fi, t in merged.tris.items():
                merged.shape_of[fi] = merged.shapes.add(polys.get(fi) or Polygon(t))
            folds = {**P.folds, **Q.folds, **joined}
            ok = True
            for fi, t in merged.tris.items():  # cada costura ha de poder dur pestanya
                g = [int(x) for x in F[fi]]
                for i in range(3):
                    e2 = tuple(sorted((g[i], g[(i + 1) % 3])))
                    if e2 in folds or len(em[e2]) != 2:
                        continue
                    h = next(x for x in em[e2] if x != fi)
                    if h not in merged.tris or h < fi:  # l'altra peça, o ja comprovada
                        continue
                    if fit_tab(merged, fi, *_edge_in_face(F, fi, t, e2), tab_mm) is None and \
                            fit_tab(merged, h, *_edge_in_face(F, h, merged.tris[h], e2), tab_mm) is None:
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                continue
            merged.folds = folds
            q_idx = owner[b]
            pieces[owner[a]] = merged
            for fi in Q.tris:
                owner[fi] = owner[a]
            pieces[q_idx] = Piece()
            changed = True
            break
    keep = [i for i, p in enumerate(pieces) if p.tris]
    remap = {old: new for new, old in enumerate(keep)}
    return [pieces[i] for i in keep], np.array([remap[o] for o in owner])


# ---------------------------------------------------------------- zones que tanquen problemes

PATCH_PATH = 6     # cares màximes entre dos problemes per ajuntar-los en una mateixa zona
PATCH_ROUNDS = 4   # rondes màximes de buscar problemes nous i ampliar les zones


def problem_faces(pieces: list[Piece], region: np.ndarray | None = None) -> set[int]:
    """Cares que han quedat en peces petites (fora de zones ja fetes): on el desplegament falla."""
    return {fi for p in pieces if len(p.tris) <= SMALL_PIECE for fi in p.tris
            if region is None or region[fi] == 0}


def problem_zones(mesh: trimesh.Trimesh, problems: set[int], max_path: int = PATCH_PATH,
                  base: np.ndarray | None = None) -> np.ndarray:
    """Agrupa els problemes propers en zones petites: 0 = resta del model, 1..k = zones.

    Cada zona comença en un problema i hi va afegint el camí de cares més curt fins al
    problema lliure més proper, si és a menys de `max_path` cares. Surten tires o arbres
    estrets: tots els seus vèrtexs queden a la vora, així que es despleguen sense
    escletxes, i en treure-les de la resta, els vèrtexs problemàtics també hi queden a la vora.
    Amb `base` (zones per línies marcades), un camí no travessa d'una zona marcada a una altra.
    """
    c = mesh.triangles_center
    adj: list[list[tuple[float, int]]] = [[] for _ in mesh.faces]
    for e, fs in edge_faces(mesh.faces).items():
        if len(fs) == 2 and (base is None or base[fs[0]] == base[fs[1]]):
            a, b = fs
            d = float(np.linalg.norm(c[a] - c[b]))
            adj[a].append((d, b))
            adj[b].append((d, a))
    zone = np.zeros(len(mesh.faces), dtype=int)
    left = set(problems)
    k = 0
    for p in sorted(problems):
        if p not in left:
            continue
        k += 1
        patch = {p}
        left.discard(p)
        zone[p] = k
        while True:
            dist = {f: 0.0 for f in patch}
            hops = {f: 0 for f in patch}
            prev: dict[int, int] = {}
            heap = [(0.0, f) for f in patch]
            hit = None
            while heap:
                d, v = heapq.heappop(heap)
                if d > dist[v]:
                    continue
                if v in left:
                    hit = v
                    break
                if hops[v] >= max_path:
                    continue
                for w, u in adj[v]:
                    if zone[u] not in (0, k):
                        continue
                    if d + w < dist.get(u, math.inf):
                        dist[u], hops[u], prev[u] = d + w, hops[v] + 1, v
                        heapq.heappush(heap, (d + w, u))
            if hit is None:
                break
            v = hit
            while v not in patch:
                patch.add(v)
                zone[v] = k
                left.discard(v)
                v = prev[v]
    return zone


# ---------------------------------------------------------------- pestanyes i línies

def _edge_in_face(F, fi: int, coords: np.ndarray, e) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    f = [int(x) for x in F[fi]]
    i0, i1 = f.index(e[0]), f.index(e[1])
    return coords[i0], coords[i1], coords[3 - i0 - i1]


def tab_polygon(A: np.ndarray, B: np.ndarray, inside: np.ndarray, h: float,
                inset_frac: float | None = None) -> np.ndarray:
    """Trapezi cap enfora de l'aresta AB (allunyat del punt `inside`).

    Cada extrem s'escurça `inset_frac` × L; per defecte, prou per tenir extrems a ≥45°.
    """
    L = float(np.linalg.norm(B - A))
    u = (B - A) / L
    n = np.array([-u[1], u[0]])
    if np.dot(n, inside - A) > 0:
        n = -n
    h = min(h, 0.5 * L)
    inset = min(h, 0.3 * L) if inset_frac is None else max(min(h, 0.3 * L), inset_frac * L)
    return np.array([A, B, B - u * inset + n * h, A + u * inset + n * h])


TAB_GAP = 0.4    # mm de separació entre una pestanya retallada i la cara que la talla
TAB_MIN = 0.35   # fracció mínima de l'àrea d'una pestanya sencera perquè valgui la pena

# Quan una pestanya només topa amb altres pestanyes: si el solapament és com a molt
# aquesta fracció de la seva àrea, s'encongeix; si és més gran, es denten totes dues
# com un engranatge.
TAB_SHRINK_MAX = 0.35
# Encongiments que es proven: (fracció de l'alçada, fracció de l'aresta per a cada extrem).
TAB_SHRINKS = ((0.85, None), (0.7, 0.35), (0.85, 0.4), (0.55, 0.4))
# Amplada mínima d'una dent (mm) quan es denten dues pestanyes que es tapen; si hi cap,
# cada dent fa mitja alçada de pestanya.
TOOTH_MIN = 2.0


@dataclass
class TabFit:
    polys: list[np.ndarray]
    frac: float                                   # àrea respecte de la pestanya sencera
    how: str                                      # sencera / encongida / dentada / retallada
    reshape: dict[int, list[np.ndarray]] = field(default_factory=dict)  # altres pestanyes dentades


def _parts(geom) -> list[Polygon]:
    return [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon" and not g.is_empty]


def _attached(geom, A, B, thin: float = 0.0) -> list[Polygon]:
    """Components de `geom` que toquen l'aresta AB (la resta quedarien soltes en retallar).

    Amb `thin` > 0 abans s'eliminen les tires més primes que 2·thin, que no es poden retallar.
    """
    if thin > 0:
        geom = geom.buffer(-thin, join_style=2).buffer(thin, join_style=2)
    base = LineString([A, B])
    return [g for g in _parts(geom) if g.distance(base) < 1e-6 and g.area > 1e-6]


def _coords(polys: list[Polygon]) -> list[np.ndarray]:
    return [np.array(g.simplify(0.02).exterior.coords[:-1]) for g in polys]


def _teeth(p: Piece, own: int, A, B, full: Polygon, hit: list[int], h: float) -> TabFit | None:
    """Denta la pestanya nova i les que tapa, alternant dents com un engranatge.

    Les franges parells (perpendiculars a AB) són per a la pestanya nova; on no hi ha
    cap altra pestanya la nova es queda sencera. Les pestanyes tapades perden el que
    ocupen les dents noves (amb una mica de joc) i es queden les franges senars.
    """
    L = float(np.linalg.norm(B - A))
    u = (B - A) / L
    n = np.array([-u[1], u[0]])
    w = max(TOOTH_MIN, min(h / 2, L / 4))
    big = 3 * h + L
    even = []
    for k in range(0, int(math.ceil(L / w)) + 1, 2):
        x0, x1 = k * w + TAB_GAP / 2, (k + 1) * w - TAB_GAP / 2
        even.append(Polygon([A + u * x0 - n * big, A + u * x1 - n * big,
                             A + u * x1 + n * big, A + u * x0 + n * big]))
    others = [p.tab_of[i] for i in hit]
    occupied = unary_union([t.geom() for t in others])
    mine = unary_union([full.intersection(unary_union(even)),
                        full.difference(occupied.buffer(TAB_GAP))])
    mine = _attached(mine, A, B, TAB_GAP / 2)
    area = sum(g.area for g in mine)
    if area < TAB_MIN * full.area:
        return None
    mine_geom = unary_union(mine)
    for i in p.shapes.near(mine_geom):
        if i == own or i in hit:
            continue
        q = p.shapes.polys[i]
        if mine_geom.intersection(q).area > OVERLAP_TOL * q.area + 1e-9:
            return None
    reshape = {}
    for t in others:
        rest = _attached(t.geom().difference(mine_geom.buffer(TAB_GAP)), t.A, t.B, TAB_GAP / 2)
        if sum(g.area for g in rest) < TAB_MIN * t.full_area:
            return None
        reshape[t.shape] = _coords(rest)
    return TabFit(_coords(mine), area / full.area, "dentada", reshape)


def fit_tab(p: Piece, fi: int, A, B, C, h: float, clip: bool = True) -> TabFit | None:
    """Pestanya per a l'aresta AB de la cara `fi`.

    - "sencera" si no topa amb res;
    - "encongida" si només topa una mica amb altres pestanyes;
    - "dentada" si només topa amb altres pestanyes però molt: es denten totes, com un engranatge;
    - "retallada" (només amb `clip`) si topa amb cares o cap de les anteriors funciona.
    Sense `clip`, retorna None en aquest últim cas perquè qui crida provi l'altre costat.
    """
    full = Polygon(tab_polygon(A, B, C, h))
    own = p.shape_of[fi]
    hit = [i for i in p.shapes.near(full)
           if i != own and p.shapes.polys[i].intersection(full).area > 1e-9]
    if not hit:
        return TabFit(_coords([full]), 1.0, "sencera")
    blockers = [p.shapes.polys[i] for i in hit]

    if all(i in p.tab_of for i in hit):
        overlap = unary_union(blockers).intersection(full).area / full.area
        if overlap <= TAB_SHRINK_MAX:
            for k, inset in TAB_SHRINKS:
                small = Polygon(tab_polygon(A, B, C, h * k, inset))
                if small.is_valid and not p.shapes.hits(small):
                    return TabFit(_coords([small]), small.area / full.area, "encongida")
        fit = _teeth(p, own, A, B, full, hit, h)
        if fit is not None:
            return fit
    if not clip:
        return None

    parts = _attached(full.difference(unary_union(blockers).buffer(TAB_GAP)), A, B)
    if not parts:
        return None
    best = max(parts, key=lambda g: g.area)
    frac = best.area / full.area
    if frac < TAB_MIN:
        return None
    return TabFit(_coords([best]), frac, "retallada")


def tab_lines(t: Tab) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Plecs (on les dents s'uneixen a l'aresta) i talls (la resta) d'una pestanya."""
    base = LineString([t.A, t.B])
    zone = t.geom().buffer(1e-5)

    def segs(g) -> list[np.ndarray]:
        out = []
        for line in getattr(g, "geoms", [g]):
            if line.geom_type == "LineString" and line.length > 1e-6:
                c = np.array(line.coords)
                out += [c[i:i + 2] for i in range(len(c) - 1)]
        return out

    folds = segs(base.intersection(zone))
    cuts = segs(base.difference(zone))
    for q in t.polys:
        cuts += _outline_without(q, t.A, t.B)
    return folds, cuts


def _outline_without(poly: np.ndarray, A: np.ndarray, B: np.ndarray) -> list[np.ndarray]:
    """Segments del contorn de la pestanya excepte els que cauen sobre l'aresta AB."""
    u = (B - A) / np.linalg.norm(B - A)
    n = np.array([-u[1], u[0]])
    on = lambda q: abs(float(np.dot(q - A, n))) < 1e-4
    out = []
    for i in range(len(poly)):
        q0, q1 = poly[i], poly[(i + 1) % len(poly)]
        if not (on(q0) and on(q1)):
            out.append(np.array([q0, q1]))
    return out


def _label(A, B, C, text: str) -> tuple[np.ndarray, str, float]:
    mid = (A + B) / 2
    centroid = (A + B + C) / 3
    area = abs(_cross(B - A, C - A)) / 2
    per = np.linalg.norm(B - A) + np.linalg.norm(C - B) + np.linalg.norm(A - C)
    inr = 2 * area / per
    size = float(np.clip(min(0.25 * np.linalg.norm(B - A), 1.2 * inr), 1.0, 3.5))
    pos = mid + (centroid - mid) * min(1.0, 0.6 * size / max(np.linalg.norm(centroid - mid), 1e-9))
    return pos, text, size


def group_seams(mesh: trimesh.Trimesh, seams: list[tuple[tuple[int, int], int, int]]) -> list[int]:
    """Agrupa en una sola costura les arestes tallades contigües entre les mateixes dues zones planes.

    Una aresta de caixa partida en quatre trossos és una sola costura per a qui munta.
    """
    patch = flat_patches(mesh, edge_faces(mesh.faces))
    key = [frozenset((int(patch[a]), int(patch[b]))) for _, a, b in seams]
    parent = list(range(len(seams)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_vertex: dict[tuple[int, frozenset], int] = {}
    for i, (e, _, _) in enumerate(seams):
        for v in e:
            j = by_vertex.setdefault((v, key[i]), i)
            parent[find(i)] = find(j)
    number: dict[int, int] = {}
    return [number.setdefault(find(i), len(number) + 1) for i in range(len(seams))]


def add_tabs_and_lines(mesh: trimesh.Trimesh, pieces: list[Piece], owner: np.ndarray,
                       tab_mm: float) -> dict[str, int]:
    """Numera les costures, hi afegeix pestanyes i classifica cada aresta en tall o plec."""
    F = mesh.faces
    patch = flat_patches(mesh, edge_faces(F))
    seams = []
    for e, fs in sorted(edge_faces(F).items()):
        if len(fs) != 2:  # vora oberta o aresta no-manifold: només tall
            for fi in fs:
                p = pieces[owner[fi]]
                A, B, _ = _edge_in_face(F, fi, p.tris[fi], e)
                p.cuts.append(np.array([A, B]))
            continue
        a, b = fs
        pa = pieces[owner[a]]
        if owner[a] == owner[b] and e in pa.folds:
            if pa.folds[e] != "pla":  # dins d'una zona plana no hi ha res a doblegar
                A, B, _ = _edge_in_face(F, a, pa.tris[a], e)
                pa.fold_lines.append((np.array([A, B]), pa.folds[e]))
            continue
        seams.append((e, a, b))

    numbers = group_seams(mesh, seams)
    stats = dict(costures=len(set(numbers)), arestes_tallades=len(seams),
                 pestanyes=0, sense_pestanya=0, pestanyes_encongides=0,
                 pestanyes_dentades=0, pestanyes_canviades=0, pestanyes_retallades=0)
    # On posar el número: a l'aresta més llarga de cada costura, a cada costat.
    longest: dict[tuple[int, int], tuple[float, int]] = {}
    for i, ((e, a, b), n) in enumerate(zip(seams, numbers)):
        L = float(np.linalg.norm(mesh.vertices[e[0]] - mesh.vertices[e[1]]))
        for fi in (a, b):
            k = (n, int(patch[fi]))
            if k not in longest or L > longest[k][0]:
                longest[k] = (L, i)
    tab_side: dict[int, int] = {}

    for i, ((e, a, b), n) in enumerate(zip(seams, numbers)):
        # Pestanya al mateix costat que la resta de la costura si hi cap sencera;
        # si no, al costat on en cap més, encara que sigui retallada.
        sides = (a, b) if tab_side.get(n, patch[a]) == patch[a] else (b, a)
        # 1) sencera o una mica encongida, primer al costat preferit i si no a l'altre;
        # 2) si no, la més gran retallada dels dos costats.
        best = None
        for clip in (False, True):
            for fi in sides:
                p = pieces[owner[fi]]
                A, B, C = _edge_in_face(F, fi, p.tris[fi], e)
                fit = fit_tab(p, fi, A, B, C, tab_mm, clip)
                if fit is not None and (best is None or fit.frac > best[1].frac):
                    best = (fi, fit, A, B)
                if fit is not None and not clip:
                    break
            if best is not None:
                break
        tabbed = None
        if best is not None:
            tabbed, fit, A, B = best
            if fit.how != "sencera":
                stats[f"pestanyes_{fit.how[:-1]}es"] += 1
            if tabbed != sides[0]:
                stats["pestanyes_canviades"] += 1
            tab_side.setdefault(n, int(patch[tabbed]))
            p = pieces[owner[tabbed]]
            for idx, polys in fit.reshape.items():  # les pestanyes que s'han dentat amb aquesta
                p.tab_of[idx].polys = polys
                p.shapes.replace(idx, p.tab_of[idx].geom())
            p.add_tab(Tab(A, B, fit.polys, Polygon(tab_polygon(A, B, _edge_in_face(
                F, tabbed, p.tris[tabbed], e)[2], tab_mm)).area))
        stats["pestanyes" if tabbed is not None else "sense_pestanya"] += 1

        for fi in (a, b):
            p = pieces[owner[fi]]
            A, B, C = _edge_in_face(F, fi, p.tris[fi], e)
            if fi != tabbed:
                p.cuts.append(np.array([A, B]))
            if longest[(n, int(patch[fi]))][1] == i:
                p.labels.append(_label(A, B, C, str(n)))
    for p in pieces:
        for t in p.tabs:
            folds, cuts = tab_lines(t)
            # La pestanya es doblega enrere, sota la cara veïna.
            p.fold_lines += [(f, "muntanya") for f in folds]
            p.cuts += cuts
    return stats


# ---------------------------------------------------------------- pàgines

def _rotations(pts: np.ndarray) -> list[tuple[float, float, float]]:
    """(angle, amplada, alçada) girant perquè cada aresta del casc convex quedi horitzontal.

    Ordenades de menys a més àrea de capsa; una d'aquestes és sempre la capsa mínima.
    """
    hull = MultiPoint([tuple(p) for p in pts]).convex_hull
    if hull.geom_type != "Polygon":
        return [(0.0, float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1])))]
    ring = np.array(hull.exterior.coords)
    out = []
    for p, q in zip(ring[:-1], ring[1:]):
        ang = -math.atan2(q[1] - p[1], q[0] - p[0])
        c, s = math.cos(ang), math.sin(ang)
        r = ring @ np.array([[c, s], [-s, c]])
        out.append((ang, float(np.ptp(r[:, 0])), float(np.ptp(r[:, 1]))))
    out.append((0.0, float(np.ptp(ring[:, 0])), float(np.ptp(ring[:, 1]))))
    out.sort(key=lambda t: (round(t[1] * t[2], 9), -t[1]))
    return out


def _fit_angle(pts: np.ndarray, W: float, H: float) -> float | None:
    """Angle (el de menys àrea) amb què la peça cap en W×H, girada 90° o no; None si no hi cap."""
    for ang, w, h in _rotations(pts):
        if (w <= W and h <= H) or (h <= W and w <= H):
            return ang
    return None


def _best_rotation(pts: np.ndarray) -> float:
    """Angle que minimitza l'àrea de la capsa alineada."""
    return _rotations(pts)[0][0]


@dataclass
class Page:
    pieces: list[Piece] = field(default_factory=list)


NEST_RES = 1.0   # mm per quadre de la graella de col·locació
NEST_GAP = 3.0   # mm de separació mínima entre peces
NEST_TURNS = 24  # girs repartits que es proven, a més dels de capsa mínima
NEST_SMALL = 0.02  # peces de menys d'aquesta fracció de la pàgina: només 4 girs


def piece_outline(p):
    """Forma real de la peça: cares i pestanyes (o la forma d'una peça làser)."""
    if hasattr(p, "outline"):
        return p.outline()
    return unary_union([Polygon(t) for t in p.tris.values()] + [Polygon(q) for q in p.tab_polys()])


def _raster(geom, res: float):
    """Quadres de la graella que toca `geom` (per excés). Retorna la màscara i l'origen."""
    x0, y0, x1, y1 = geom.bounds
    w, h = int(math.ceil((x1 - x0) / res)), int(math.ceil((y1 - y0) / res))
    xs = x0 + (np.arange(w) + 0.5) * res
    ys = y0 + (np.arange(h) + 0.5) * res
    gx, gy = np.meshgrid(xs, ys)
    fat = geom.buffer(res * 0.71)  # mitja diagonal: si toca el quadre, el centre hi cau
    return shapely.contains_xy(fat, gx, gy), (x0, y0)


def _fast_len(n: int) -> int:
    """Mida ≥ n feta només de factors 2, 3 i 5: la FFT hi va molt més de pressa."""
    while True:
        m = n
        for p in (2, 3, 5):
            while m % p == 0:
                m //= p
        if m == 1:
            return n
        n += 1


def _fft_shape(shape: tuple[int, int]) -> tuple[int, int]:
    return _fast_len(shape[0]), _fast_len(shape[1])


def _occ_fft(occ: np.ndarray):
    return np.fft.rfft2(occ.astype(float), s=_fft_shape(occ.shape))


def _mask_fft(shape: tuple[int, int], mask: np.ndarray):
    return np.conj(np.fft.rfft2(mask.astype(float), s=_fft_shape(shape)))


def _free_spot(occ: np.ndarray, focc, mask: np.ndarray, fmask) -> tuple[int, int] | None:
    """Primera posició (fila, columna), de dalt a baix i d'esquerra a dreta, on `mask` no toca `occ`.

    La correlació és circular, però amb la mida de FFT ≥ la de la pàgina i només posicions
    on la màscara hi cap sencera, no hi ha cap volta.
    """
    H, W = occ.shape
    h, w = mask.shape
    if h > H or w > W:
        return None
    corr = np.fft.irfft2(focc * fmask, s=_fft_shape(occ.shape))[:H - h + 1, :W - w + 1]
    free = np.argwhere(corr < 0.5)
    if not len(free):
        return None
    i, j = free[0]  # argwhere ja va per files i després columnes
    return int(i), int(j)


def layout(pieces: list[Piece], page: tuple[float, float], margin: float = MARGIN,
           gap: float = NEST_GAP, res: float = NEST_RES, turns: int = NEST_TURNS
           ) -> tuple[list[Page], int]:
    """Col·loca les peces segons la seva forma real, no per capses.

    Converteix les coordenades a l'eix y cap avall de l'SVG fent una simetria (així el
    que es veu és la cara exterior). Cada peça, de la més gran a la més petita, prova a
    cada pàgina les orientacions de capsa més petita (girades de 90 en 90°) i `NEST_TURNS`
    girs repartits, i es queda la posició que deixa la seva vora de baix més amunt
    (a igualtat, la que ocupa més quadres: la peça més ben encaixada). La pàgina és
    una graella de quadres de `res` mm; la cerca de lloc lliure es fa amb FFT. Les peces
    idèntiques (suports repetits) comparteixen les màscares ja calculades.
    Retorna també quantes peces no caben a l'àrea imprimible.
    """
    W, H = page[0] - 2 * margin, page[1] - 2 * margin
    # La separació entre peces pot caure sobre el marge: la graella s'hi estén mitja separació.
    pad = gap / 2 - 0.05  # el contorn ampliat és poligonal: pot quedar una mica curt
    Hn, Wn = int((H + 2 * pad) // res), int((W + 2 * pad) // res)
    for p in pieces:
        p.transform(lambda x: x * np.array([1.0, -1.0]))
    order = sorted(pieces, key=lambda p: -piece_outline(p).area)

    sheets: list[list] = []  # [pàgina, ocupació, fft de l'ocupació]
    big: list[Page] = []
    cache: dict[bytes, list] = {}
    for p in order:
        outline = piece_outline(p)
        shape_key = shapely.to_wkb(shapely.set_precision(outline, 1e-3))
        options = cache.get(shape_key)
        if options is None:
            base = outline.buffer(gap / 2)
            pts = p.points()
            fit = _fit_angle(pts, W, H)
            angles = [] if fit is None else [fit, fit + math.pi / 2]
            small = outline.area < NEST_SMALL * W * H
            for ang, _, _ in _rotations(pts)[:1 if small else 2]:
                angles += [ang + k * math.pi / 2 for k in range(4)]
            if not small:  # les peces grans i ramificades encaixen millor amb més girs
                angles += [k * 2 * math.pi / turns for k in range(turns)]
            options = []
            for ang in angles:
                geom = affinity.rotate(base, ang, origin=(0, 0), use_radians=True)
                mask, origin = _raster(geom, res)
                if mask.shape[0] <= Hn and mask.shape[1] <= Wn:
                    options.append((ang, mask, origin, _mask_fft((Hn, Wn), mask)))
            cache[shape_key] = options

        placed = False
        for sheet in sheets + [None]:
            if sheet is None:  # pàgina nova
                occ = np.zeros((Hn, Wn), dtype=bool)
                sheet = [None, occ, _occ_fft(occ)]
            page_obj, occ, focc = sheet
            free = occ.size - int(occ.sum())
            best = None
            for ang, mask, origin, fmask in options:
                if mask.sum() > free:
                    continue
                spot = _free_spot(occ, focc, mask, fmask)
                if spot is not None:
                    key = (spot[0] + mask.shape[0], -int(mask.sum()), spot[1])
                    if best is None or key < best[0]:
                        best = (key, spot, ang, mask, origin)
            if best is None:
                continue
            _, (i, j), ang, mask, (ox, oy) = best
            c, s_ = math.cos(ang), math.sin(ang)
            R = np.array([[c, s_], [-s_, c]])
            dx, dy = margin - pad + j * res - ox, margin - pad + i * res - oy
            p.transform(lambda x, R=R, d=np.array([dx, dy]): x @ R + d)
            occ[i:i + mask.shape[0], j:j + mask.shape[1]] |= mask
            sheet[2] = _occ_fft(occ)
            if page_obj is None:
                sheet[0] = page_obj = Page()
                sheets.append(sheet)
            page_obj.pieces.append(p)
            placed = True
            break
        if not placed:
            # La graella va per excés: una peça molt justa pot no trobar-hi lloc. Si la forma
            # exacta hi cap girada d'alguna manera, va sola en una pàgina; si no, és massa gran.
            pts = p.points()
            ang = _fit_angle(pts, W, H)
            fits = ang is not None
            ang = _best_rotation(pts) if ang is None else ang
            c, s_ = math.cos(ang), math.sin(ang)
            p.transform(lambda x, R=np.array([[c, s_], [-s_, c]]): x @ R)
            q = p.points()
            if np.ptp(q[:, 0]) > W and np.ptp(q[:, 0]) <= H:  # girar 90° si així hi cap
                p.transform(lambda x: np.column_stack([-x[:, 1], x[:, 0]]))
            lo = p.points().min(axis=0)
            p.transform(lambda x, lo=lo: x - lo + margin)
            if fits:
                full = np.ones((Hn, Wn), dtype=bool)
                sheets.append([Page([p]), full, _occ_fft(full)])
            else:
                big.append(Page([p]))
    return [sh[0] for sh in sheets] + big, len(big)


def _pts(a: np.ndarray) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in a)


DASH = {"vall": "3,1.5", "muntanya": "3,1,0.6,1"}


def page_svg(page: Page, size: tuple[float, float], number: int, total: int,
             face_numbers: bool = False) -> str:
    W, H = size
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
           f'viewBox="0 0 {W} {H}">',
           f'<rect width="{W}" height="{H}" fill="white"/>']
    for p in page.pieces:
        out.append('<g fill="#e6e6e6" stroke="none">')
        out += [f'<polygon points="{_pts(t)}"/>' for t in p.tab_polys()]
        out.append('</g><g fill="white" stroke="none">')
        out += [f'<polygon points="{_pts(t)}"/>' for t in p.tris.values()]
        out.append('</g><g stroke="black" stroke-width="0.3" stroke-linecap="round">')
        out += [f'<line x1="{c[0,0]:.2f}" y1="{c[0,1]:.2f}" x2="{c[1,0]:.2f}" y2="{c[1,1]:.2f}"/>'
                for c in p.cuts]
        out.append('</g><g stroke="#555" stroke-width="0.25" fill="none">')
        out += [f'<line x1="{c[0,0]:.2f}" y1="{c[0,1]:.2f}" x2="{c[1,0]:.2f}" y2="{c[1,1]:.2f}" '
                f'stroke-dasharray="{DASH[k]}"/>' for c, k in p.fold_lines]
        out.append('</g><g font-family="sans-serif" fill="#c0392b" text-anchor="middle" '
                   'dominant-baseline="central">')
        out += [f'<text x="{q[0]:.2f}" y="{q[1]:.2f}" font-size="{z:.2f}">{s}</text>'
                for q, s, z in p.labels]
        out.append('</g>')
        if face_numbers:
            out.append('<g font-family="sans-serif" fill="#999" font-size="1.6" '
                       'text-anchor="middle" dominant-baseline="central">')
            out += [f'<text x="{t.mean(0)[0]:.2f}" y="{t.mean(0)[1]:.2f}">{fi + 1}</text>'
                    for fi, t in p.tris.items()]
            out.append('</g>')
    out.append(f'<text x="10" y="{H - 4}" font-family="sans-serif" font-size="3" fill="#555">'
               f'Pàgina {number}/{total} · contínua = tall · ratlles = plec de vall · '
               f'punt i ratlla = plec de muntanya · números vermells = costures que s\'uneixen</text>')
    out.append('</svg>')
    return "\n".join(out)


# ---------------------------------------------------------------- tot junt

@dataclass
class Result:
    pages: list[str]
    pieces: list[Piece]
    faces: int
    stats: dict[str, int]
    sheets: list[list[Piece]] = field(default_factory=list)  # peces de cada pàgina

    def zip_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i, svg in enumerate(self.pages, 1):
                z.writestr(f"desplegable_p{i:02d}.svg", svg)
        return buf.getvalue()


def _score(pieces: list[Piece], stats: dict) -> float:
    """Com més baix, millor: poques peces, poques de petites i pestanyes senceres."""
    small = sum(1 for p in pieces if len(p.tris) <= SMALL_PIECE)
    return (len(pieces) + 2 * small + 5 * stats["sense_pestanya"]
            + 0.5 * stats["pestanyes_retallades"])


def make_papercraft(mesh: trimesh.Trimesh, target_faces: int, size_mm: float,
                    tab_mm: float = 5.0, page: str = "A4", landscape: bool = False,
                    face_numbers: bool = False, lines_deg: float = 0.0,
                    problem_zones_on: bool = True) -> Result:
    """Desplega la malla i la posa en pàgines.

    - `lines_deg` > 0: primer parteix per les arestes que pleguen més d'aquest angle,
      desplega cada zona per separat i després torna a unir les peces mentre hi càpiguen.
    - `problem_zones_on`: on el desplegament deixa peces petites, tanca els problemes
      propers en zones pròpies (tires estretes) i torna a desplegar; ho repeteix amb els
      problemes nous i es queda el millor resultat.
    """
    m = scale_to(simplify(clean(mesh), target_faces), size_mm)
    size = PAGES[page][::-1] if landscape else PAGES[page]
    room = (size[0] - 2 * MARGIN - 2 * tab_mm, size[1] - 2 * MARGIN - 2 * tab_mm)
    lines = natural_zones(m, lines_deg) if lines_deg > 0 else None

    def attempt(region):
        pieces, owner = unfold(m, room, tab_mm, region)
        pieces, owner = absorb_small(m, pieces, owner, room, tab_mm, region=region)
        return pieces, owner

    pieces, owner = attempt(lines)
    if lines is not None:
        pieces, owner = merge_pieces(m, pieces, owner, room, tab_mm)
    best = (pieces, owner, add_tabs_and_lines(m, pieces, owner, tab_mm), 0)

    if problem_zones_on:
        problems = problem_faces(pieces)
        for _ in range(PATCH_ROUNDS):
            if not problems:
                break
            zones = problem_zones(m, problems, base=lines)
            base = lines if lines is not None else np.zeros(len(m.faces), dtype=int)
            region = np.where(zones > 0, base.max() + 1 + zones, base)
            pieces, owner = attempt(region)
            stats = add_tabs_and_lines(m, pieces, owner, tab_mm)
            if _score(pieces, stats) < _score(best[0], best[2]):
                best = (pieces, owner, stats, int(zones.max()))
            new = problem_faces(pieces, zones)
            if not new - problems:
                break
            problems |= new

    pieces, owner, stats, n_zones = best
    pages, oversize = layout(pieces, size)
    stats.update(peces=len(pieces), pagines=len(pages), massa_grans=oversize,
                 zones=n_zones, peces_petites=sum(1 for p in pieces if len(p.tris) <= SMALL_PIECE))
    svgs = [page_svg(pg, size, i, len(pages), face_numbers) for i, pg in enumerate(pages, 1)]
    return Result(svgs, pieces, len(m.faces), stats, [pg.pieces for pg in pages])
