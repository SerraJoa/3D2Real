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
import trimesh
from shapely.geometry import LineString, MultiPoint, Polygon
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


# ---------------------------------------------------------------- desplegament

@dataclass
class Piece:
    tris: dict[int, np.ndarray] = field(default_factory=dict)       # cara → 3×2
    folds: dict[tuple[int, int], str] = field(default_factory=dict)  # aresta → "vall"/"muntanya"
    tabs: list[np.ndarray] = field(default_factory=list)            # polígons N×2
    labels: list[tuple[np.ndarray, str, float]] = field(default_factory=list)
    cuts: list[np.ndarray] = field(default_factory=list)            # segments 2×2
    fold_lines: list[tuple[np.ndarray, str]] = field(default_factory=list)
    shapes: _Shapes = field(default_factory=_Shapes, repr=False)
    shape_of: dict[int, int] = field(default_factory=dict, repr=False)  # cara → índex a shapes
    tab_shapes: set[int] = field(default_factory=set, repr=False)       # índexs de pestanyes

    def place(self, fi: int, coords: np.ndarray, poly: Polygon) -> None:
        self.tris[fi] = coords
        self.shape_of[fi] = self.shapes.add(poly)

    def points(self) -> np.ndarray:
        pts = list(self.tris.values()) + self.tabs
        return np.vstack(pts)

    def transform(self, fn) -> None:
        self.tris = {k: fn(v) for k, v in self.tris.items()}
        self.tabs = [fn(t) for t in self.tabs]
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


def flat_patches(mesh: trimesh.Trimesh, em) -> np.ndarray:
    """Agrupa les cares coplanars connectades: cada grup es desplega sencer o gens."""
    parent = list(range(len(mesh.faces)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for fs in em.values():
        if len(fs) == 2 and fold_kind(mesh, fs[0], fs[1]) == "pla":
            parent[find(fs[0])] = find(fs[1])
    return np.array([find(i) for i in range(len(mesh.faces))])


def unfold(mesh: trimesh.Trimesh, max_size: tuple[float, float] | None = None,
           tab_mm: float = 0.0) -> tuple[list[Piece], np.ndarray]:
    """Desplega la malla en peces sense solapaments.

    Cada peça creix des de la zona plana més gran que queda lliure. Primer s'hi
    afegeixen les zones que pleguen per arestes més planes i més properes al centre
    de la peça. Una zona que solaparia la peça, o que la faria més gran que
    `max_size` (mm), no s'hi afegeix per aquella aresta (queda com a costura) i
    acaba en una altra peça.

    Amb `tab_mm` > 0 es reserva, a cada aresta lliure, l'espai d'una pestanya: cap
    cara nova no hi pot caure. Així no es formen escletxes sense lloc per enganxar.
    """
    V, F, N = mesh.vertices, mesh.faces, mesh.face_normals
    em = edge_faces(F)
    patch = flat_patches(mesh, em)
    members: dict[int, list[int]] = {}
    for fi, pid in enumerate(patch):
        members.setdefault(int(pid), []).append(fi)
    neigh: list[list[tuple[float, int, tuple[int, int]]]] = [[] for _ in F]
    for e, fs in em.items():
        if len(fs) == 2:
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
                 small: int = SMALL_PIECE) -> tuple[list[Piece], np.ndarray]:
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
# aquesta fracció de la seva àrea, s'encongeix; si és més gran, es canvia de costat.
TAB_SHRINK_MAX = 0.35
# Encongiments que es proven: (fracció de l'alçada, fracció de l'aresta per a cada extrem).
TAB_SHRINKS = ((0.85, None), (0.7, 0.35), (0.85, 0.4), (0.55, 0.4))


def fit_tab(p: Piece, fi: int, A, B, C, h: float, clip: bool = True
            ) -> tuple[np.ndarray, float, str] | None:
    """Pestanya per a l'aresta AB de la cara `fi`.

    Retorna el polígon, la fracció d'àrea respecte de la pestanya sencera i com s'ha fet:
    "sencera"; "encongida" si només topava una mica amb altres pestanyes; "retallada"
    (només amb `clip`) si topava amb cares o massa amb pestanyes. Sense `clip`, una
    pestanya que topa amb cares o que queda tapada per altres pestanyes retorna None,
    perquè qui crida provi l'altre costat de la costura.
    """
    full = Polygon(tab_polygon(A, B, C, h))
    own = p.shape_of[fi]
    hit = [i for i in p.shapes.near(full)
           if i != own and p.shapes.polys[i].intersection(full).area > 1e-9]
    if not hit:
        return np.array(full.exterior.coords[:-1]), 1.0, "sencera"
    blockers = [p.shapes.polys[i] for i in hit]

    only_tabs = all(i in p.tab_shapes for i in hit)
    if only_tabs:
        overlap = unary_union(blockers).intersection(full).area / full.area
        if overlap <= TAB_SHRINK_MAX:
            for k, inset in TAB_SHRINKS:
                small = Polygon(tab_polygon(A, B, C, h * k, inset))
                if small.is_valid and not p.shapes.hits(small):
                    return np.array(small.exterior.coords[:-1]), small.area / full.area, "encongida"
    if not clip:
        return None

    rest = full.difference(unary_union(blockers).buffer(TAB_GAP))
    base = LineString([A, B])
    parts = [g for g in getattr(rest, "geoms", [rest])
             if g.geom_type == "Polygon" and not g.is_empty]
    parts = [g for g in parts if g.intersection(base.buffer(1e-6)).length > 0
             or g.distance(base) < 1e-6]
    if not parts:
        return None
    best = max(parts, key=lambda g: g.area).simplify(0.02)
    frac = best.area / full.area
    if frac < TAB_MIN or best.geom_type != "Polygon":
        return None
    return np.array(best.exterior.coords[:-1]), frac, "retallada"


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
                 pestanyes_canviades=0, pestanyes_retallades=0)
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
                tab = fit_tab(p, fi, A, B, C, tab_mm, clip)
                if tab is not None and (best is None or tab[1] > best[1]):
                    best = (fi, tab[1], tab[0], A, B, tab[2])
                if tab is not None and not clip:
                    break
            if best is not None:
                break
        tabbed = None
        if best is not None:
            tabbed, _, poly, A, B, how = best
            if how != "sencera":
                stats[f"pestanyes_{how[:-1]}es"] += 1
            if tabbed != sides[0]:
                stats["pestanyes_canviades"] += 1
            tab_side.setdefault(n, int(patch[tabbed]))
            p = pieces[owner[tabbed]]
            p.tabs.append(poly)
            p.tab_shapes.add(p.shapes.add(Polygon(poly)))
            # La pestanya es doblega enrere, sota la cara veïna.
            p.fold_lines.append((np.array([A, B]), "muntanya"))
            p.cuts.extend(_outline_without(poly, A, B))
        stats["pestanyes" if tabbed is not None else "sense_pestanya"] += 1

        for fi in (a, b):
            p = pieces[owner[fi]]
            A, B, C = _edge_in_face(F, fi, p.tris[fi], e)
            if fi != tabbed:
                p.cuts.append(np.array([A, B]))
            if longest[(n, int(patch[fi]))][1] == i:
                p.labels.append(_label(A, B, C, str(n)))
    return stats


# ---------------------------------------------------------------- pàgines

def _best_rotation(pts: np.ndarray) -> float:
    """Angle que minimitza l'àrea de la capsa alineada (provant cada aresta del casc convex)."""
    hull = MultiPoint([tuple(p) for p in pts]).convex_hull
    if hull.geom_type != "Polygon":
        return 0.0
    ring = np.array(hull.exterior.coords)
    best, best_area = 0.0, math.inf
    for p, q in zip(ring[:-1], ring[1:]):
        ang = -math.atan2(q[1] - p[1], q[0] - p[0])
        c, s = math.cos(ang), math.sin(ang)
        r = ring @ np.array([[c, s], [-s, c]])
        w, h = np.ptp(r[:, 0]), np.ptp(r[:, 1])
        area = w * h
        if area < best_area - 1e-9 or (abs(area - best_area) <= 1e-9 and w > h):
            best, best_area = ang, area
    return best


@dataclass
class Page:
    pieces: list[Piece] = field(default_factory=list)


def layout(pieces: list[Piece], page: tuple[float, float], margin: float = MARGIN,
           gap: float = 4.0) -> tuple[list[Page], int]:
    """Gira cada peça a la capsa mínima i les col·loca en prestatges per pàgines.

    Converteix les coordenades a l'eix y cap avall de l'SVG fent una simetria
    (així el que es veu és la cara exterior). Retorna també quantes peces no
    caben a l'àrea imprimible.
    """
    W, H = page[0] - 2 * margin, page[1] - 2 * margin
    sized = []
    for p in pieces:
        pts = p.points()
        # Capsa mínima primer; si no hi cap, el marc del desplegament (que sí que hi cap).
        for ang in (_best_rotation(pts), 0.0):
            c, s = math.cos(ang), math.sin(ang)
            R = np.array([[c, s], [-s, c]]) @ np.diag([1.0, -1.0])
            r = pts @ R
            w, h = np.ptp(r[:, 0]), np.ptp(r[:, 1])
            if (w <= W and h <= H) or (h <= W and w <= H):
                break
        p.transform(lambda x, R=R: x @ R)
        if w > W and h <= W and w <= H:  # girar 90° si així hi cap
            p.transform(lambda x: np.column_stack([-x[:, 1], x[:, 0]]))
            w, h = h, w
        lo = p.points().min(axis=0)
        p.transform(lambda x, lo=lo: x - lo)
        sized.append((h, w, p))

    sized.sort(key=lambda t: -t[0])
    pages: list[Page] = [Page()]
    big: list[Page] = []
    x = y = shelf = 0.0
    for h, w, p in sized:
        if w > W or h > H:  # no hi cap: pàgina pròpia i avís
            p.transform(lambda q: q + margin)
            big.append(Page([p]))
            continue
        if x + w > W:
            x, y, shelf = 0.0, y + shelf + gap, 0.0
        if y + h > H:
            pages.append(Page())
            x = y = shelf = 0.0
        p.transform(lambda q, dx=margin + x, dy=margin + y: q + np.array([dx, dy]))
        pages[-1].pieces.append(p)
        x += w + gap
        shelf = max(shelf, h)
    return [pg for pg in pages if pg.pieces] + big, len(big)


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
        out += [f'<polygon points="{_pts(t)}"/>' for t in p.tabs]
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

    def zip_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i, svg in enumerate(self.pages, 1):
                z.writestr(f"desplegable_p{i:02d}.svg", svg)
        return buf.getvalue()


def make_papercraft(mesh: trimesh.Trimesh, target_faces: int, size_mm: float,
                    tab_mm: float = 5.0, page: str = "A4", landscape: bool = False,
                    face_numbers: bool = False) -> Result:
    m = scale_to(simplify(clean(mesh), target_faces), size_mm)
    size = PAGES[page][::-1] if landscape else PAGES[page]
    room = (size[0] - 2 * MARGIN - 2 * tab_mm, size[1] - 2 * MARGIN - 2 * tab_mm)
    pieces, owner = unfold(m, room, tab_mm)
    pieces, owner = absorb_small(m, pieces, owner, room, tab_mm)
    stats = add_tabs_and_lines(m, pieces, owner, tab_mm)
    pages, oversize = layout(pieces, size)
    stats.update(peces=len(pieces), pagines=len(pages), massa_grans=oversize)
    svgs = [page_svg(pg, size, i, len(pages), face_numbers) for i, pg in enumerate(pages, 1)]
    return Result(svgs, pieces, len(m.faces), stats)
