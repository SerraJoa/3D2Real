"""Branca de cares: cada zona plana del model es talla com una placa independent.

- La cara exterior de cada placa és la superfície del model; el gruix creix cap endins.
- A cada aresta, les dues plaques es retiren el mínim perquè els gruixos no xoquin
  (depèn de l'angle; funciona amb arestes convexes i còncaves), més mitja separació si
  es vol un espai entre cares (làmpades).
- Suports en forma d'estel, perpendiculars a l'aresta, enganxats a la cara interior de
  les dues plaques: queden per dins i no es veuen.
- Les marques (número de placa, d'aresta i on van els suports) es graven a la cara
  interior, que és la que queda amunt en tallar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import trimesh
from shapely.geometry import LineString, MultiPoint, Polygon
from shapely.ops import unary_union

import papercraft as pc
from laser import LaserResult, Part, nest

BRACKET_SPACING = 80.0  # mm d'aresta per suport (com a mínim un per aresta)
BIG = 1000.0


@dataclass
class Seam:
    """Aresta (o tram recte d'arestes) entre dues plaques."""
    number: int
    p: int                 # placa a cada costat
    q: int
    e0: np.ndarray         # extrems en 3D
    e1: np.ndarray
    a: np.ndarray          # direcció dins el pla de p, perpendicular a l'aresta, cap a dins de p
    b: np.ndarray          # el mateix per a q
    np_: np.ndarray        # normals exteriors
    nq: np.ndarray
    inset: float = 0.0     # quant es retira cada placa des de l'aresta (sense la separació)


def _section(seam: Seam, t: float):
    """Base del pla perpendicular a l'aresta: X = a (dins de p), Y = cap endins de p.

    Retorna la direcció de q i la seva normal interior en aquesta base.
    """
    X, Y = seam.a, -seam.np_
    b2 = np.array([seam.b @ X, seam.b @ Y])
    nb2 = np.array([-seam.nq @ X, -seam.nq @ Y])
    return b2, nb2


def _slabs(seam: Seam, t: float, s: float):
    b2, nb2 = _section(seam, t)
    A = Polygon([(s, 0), (BIG, 0), (BIG, t), (s, t)])
    B = Polygon([b2 * s, b2 * BIG, b2 * BIG + nb2 * t, b2 * s + nb2 * t])
    return A, B


def min_inset(seam: Seam, t: float) -> float:
    """Mínim que s'han de retirar les dues plaques des de l'aresta perquè no xoquin."""
    def clash(s: float) -> bool:
        A, B = _slabs(seam, t, s)
        return A.intersection(B).area > 1e-9
    if not clash(0.0):
        return 0.0
    lo, hi = 0.0, t
    while clash(hi):
        hi *= 2
        if hi > 100 * t:
            return hi
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if clash(mid) else (lo, mid)
    return hi


def bracket_shape(seam: Seam, t: float, s: float, leg: float) -> Polygon | None:
    """Suport en forma d'estel al pla perpendicular a l'aresta (coordenades de la secció).

    Recolza en la cara interior de les dues plaques des del seu cantell (a `s`) fins a
    `s + leg`, i s'obre cap a l'interior del model.
    """
    b2, nb2 = _section(seam, t)
    if abs(b2[1]) < 1e-6:
        return None
    # Intersecció de les dues cares interiors: (u1, t) = b2·u2 + nb2·t
    u2 = (t - nb2[1] * t) / b2[1]
    u1 = nb2[0] * t + b2[0] * u2
    P0 = np.array([u1, t])
    A_end = np.array([s + leg, t])
    B_end = b2 * (s + leg) + nb2 * t
    m = (A_end - P0) + (B_end - P0)
    if np.linalg.norm(m) < 1e-9:
        return None
    m /= np.linalg.norm(m)
    inward = np.array([0.0, 1.0]) + nb2
    if m @ inward < 0:
        m = -m
    C = P0 + m * leg * 0.6
    poly = Polygon([P0, A_end, C, B_end])
    if not poly.is_valid or poly.area < 1e-3:
        return None
    A, B = _slabs(seam, t, s)
    if poly.intersection(A).area > 1e-6 or poly.intersection(B).area > 1e-6:
        return None
    return poly


SLOT_FIT = 0.1      # mm de joc a cada costat de les ranures
TENONS_PER_ARM = 2


def _inner_corner(b2, nb2, depth: float):
    """On es tallen les rectes paral·leles a les cares interiors, a `depth` de la cara exterior."""
    if abs(b2[1]) < 1e-6:
        return None
    u2 = (depth - nb2[1] * depth) / b2[1]
    return np.array([nb2[0] * depth + b2[0] * u2, depth])


def tenon_spans(s: float, length: float, t: float) -> list[tuple[float, float]]:
    """Trams (u0, u1) de cada tenó al llarg d'un braç, comptant des de l'aresta."""
    w = float(np.clip(length * 0.2, 2 * t, 3 * t))
    out = []
    for f in (0.35, 0.8)[:TENONS_PER_ARM]:
        c = s + length * f
        u0, u1 = c - w / 2, c + w / 2
        if u0 >= s + t:
            out.append((u0, u1))
    return out


def _arc_around(c: np.ndarray, p0: np.ndarray, p1: np.ndarray, through: np.ndarray,
                n: int = 24) -> list[np.ndarray]:
    """Arc al voltant de `c` de `p0` a `p1`, pel costat que mira cap a `through`."""
    a0 = math.atan2(*(p0 - c)[::-1])
    a1 = math.atan2(*(p1 - c)[::-1])
    am = math.atan2(*through[::-1])
    sweep = (a1 - a0) % (2 * math.pi)            # sentit antihorari
    if (am - a0) % (2 * math.pi) > sweep:         # el costat bo és l'altre
        sweep -= 2 * math.pi
    r0, r1 = np.linalg.norm(p0 - c), np.linalg.norm(p1 - c)
    out = []
    for f in np.linspace(0, 1, n + 1)[1:-1]:
        a, r = a0 + sweep * f, r0 + (r1 - r0) * f
        out.append(c + r * np.array([math.cos(a), math.sin(a)]))
    return out


def arch_bracket(seam: Seam, t: float, s: float, length: float,
                 tenons_p: list, tenons_q: list) -> Polygon | None:
    """Suport en arc amb tenons, al pla perpendicular a l'aresta (coordenades de la secció).

    La vora de fora ressegueix la cara interior de les dues plaques des del seu cantell
    (a `s`) fins a `s + length`; els tenons travessen les plaques per les ranures; la vora
    de dins és un arc tangent a les dues bandes; als racons còncaus, un arc de cercle per
    darrere la cantonada (o un colze recte si l'arc no hi cap).
    """
    b2, nb2 = _section(seam, t)
    P0 = _inner_corner(b2, nb2, t)
    w = max(2.5 * t, 8.0)
    Pw = _inner_corner(b2, nb2, t + w)
    if P0 is None or Pw is None:
        return None
    A = lambda u: np.array([u, t])
    B = lambda u: b2 * u + nb2 * t
    out_a, out_b = np.array([0.0, -1.0]), -nb2

    chain = [A(s + length) + np.array([0.0, w]), A(s + length)]
    for u0, u1 in sorted(tenons_p, reverse=True):  # de l'extrem cap a l'aresta
        chain += [A(u1), A(u1) + out_a * t, A(u0) + out_a * t, A(u0)]
    # Cap al racó: si les plaques comencen abans de la cantonada interior (sense espai entre
    # cares), es va directe a la cantonada; si no, es ressegueix el cantell fins allà.
    uA0 = P0[0]
    uB0 = float((P0 - nb2 * t) @ b2)
    if s > uA0 + 1e-3:
        chain.append(A(s))
    chain.append(P0)
    if s > uB0 + 1e-3:
        chain.append(B(s))
    for u0, u1 in sorted(tenons_q):
        chain += [B(u0), B(u0) + out_b * t, B(u1) + out_b * t, B(u1)]
    B_in = B(s + length) + nb2 * w
    A_in = A(s + length) + np.array([0.0, w])
    chain += [B(s + length), B_in]
    arc = [(1 - f) ** 2 * B_in + 2 * f * (1 - f) * Pw + f ** 2 * A_in  # Bézier tangent a les bandes
           for f in np.linspace(0, 1, 17)[1:-1]]
    poly = Polygon(chain + arc)
    if not poly.is_valid:
        # En un racó còncau la corba de dins retallaria el racó i entraria a les plaques: la
        # vora passa per darrere la cantonada, en arc de cercle centrat al racó interior o,
        # si no, recta (colze).
        poly = Polygon(chain + _arc_around(P0, B_in, A_in, np.array([0.0, 1.0]) + nb2))
        if not poly.is_valid:
            poly = Polygon(chain + [Pw])
    if not poly.is_valid or poly.area < 1e-3:
        return None
    slab_a, slab_b = _slabs(seam, t, s)
    pegs = [Polygon([A(u0), A(u1), A(u1) + out_a * t, A(u0) + out_a * t]) for u0, u1 in tenons_p]
    pegs += [Polygon([B(u0), B(u1), B(u1) + out_b * t, B(u0) + out_b * t]) for u0, u1 in tenons_q]
    body = poly.difference(unary_union(pegs).buffer(1e-6)) if pegs else poly
    if body.intersection(slab_a).area > 1e-4 or body.intersection(slab_b).area > 1e-4:
        return None
    return poly


# ---------------------------------------------------------------- costelles

RIB_MAX = 12          # costelles màximes
RIB_MIN_SIN = 0.3     # una placa gairebé paral·lela al pla de la costella no hi encaixa


def _plane_basis(N: np.ndarray):
    hint = np.array([1.0, 0, 0]) if abs(N[0]) < 0.9 else np.array([0, 1.0, 0])
    return _basis(N, hint)


def rib_candidate(m, plate_of, plates, normals, to2d, origin, N, t: float):
    """Costella al pla (origin, N): forma, tenons i ranures a cada placa que travessa.

    Retorna (components, ranures per placa) o None. Cada component és (forma 2D,
    plaques que hi encaixen, base 3D per tornar al pla).
    """
    from laminacio import section_polygon
    segs, faces = trimesh.intersections.mesh_plane(m, N, origin, return_faces=True)
    if len(segs) == 0:
        return None
    u, v = _plane_basis(N)
    to_plane = lambda p: np.column_stack([(np.atleast_2d(p) - origin) @ u, (np.atleast_2d(p) - origin) @ v])
    S = section_polygon([to_plane(sg) for sg in segs])
    if S.is_empty:
        return None
    # Per a cada placa, la part de la seva vora exterior que talla el pla.
    by_plate: dict[int, list] = {}
    for sg, f in zip(segs, faces):
        by_plate.setdefault(int(plate_of[f]), []).append(sg)
    tenons, slots, depth_max = {}, {}, 0.0
    for k, sgs in by_plate.items():
        if k not in plates:
            continue
        n = normals[k]
        nproj = n - (n @ N) * N
        sin = float(np.linalg.norm(nproj))
        if sin < RIB_MIN_SIN:
            continue
        pts3 = np.vstack(sgs)
        ell = np.cross(n, N)
        ell /= np.linalg.norm(ell)
        proj = pts3 @ ell
        P1, P2 = pts3[np.argmin(proj)], pts3[np.argmax(proj)]
        Ls = float(proj.max() - proj.min())
        tw = float(np.clip(0.4 * Ls, t, 3 * t))
        if Ls < tw + t:
            continue
        depth = t / sin
        depth_max = max(depth_max, depth)
        M3 = (P1 + P2) / 2
        inward3 = -nproj / sin
        g = np.cross(ell, n)  # dins el pla de la placa, perpendicular a la línia de tall
        half = (t / 2) / sin + SLOT_FIT
        slot = Polygon(to2d(k, np.array([M3 + ell * a + g * b for a, b in
                       ((-tw / 2 - SLOT_FIT, -half), (tw / 2 + SLOT_FIT, -half),
                        (tw / 2 + SLOT_FIT, half), (-tw / 2 - SLOT_FIT, half))])))
        if not plates[k].shape.buffer(-0.5).contains(slot):
            continue
        M, e, inw = to_plane(M3)[0], to_plane(M3 + ell)[0] - to_plane(M3)[0], \
            to_plane(M3 + inward3)[0] - to_plane(M3)[0]
        tenons[k] = (M, e, inw, tw)
        slots[k] = slot
    if not tenons:
        return None
    body = S.buffer(-(depth_max + SLOT_FIT), join_style=2)
    if body.is_empty:
        return None
    w = max(2.5 * t, 8.0)
    hole = S.buffer(-(depth_max + w), join_style=2)
    if not hole.is_empty:
        body = body.difference(hole)  # costella buidada: una anella
    pegs = {k: Polygon([M - e * tw / 2, M + e * tw / 2, M + e * tw / 2 + inw * (depth_max + 1.0),
                        M - e * tw / 2 + inw * (depth_max + 1.0)])
            for k, (M, e, inw, tw) in tenons.items()}
    shape = unary_union([body] + list(pegs.values()))
    comps = []
    for g in getattr(shape, "geoms", [shape]):
        ks = [k for k, p in pegs.items() if g.intersection(p).area > 0.5 * p.area]
        if len(ks) >= 2:
            comps.append((g, ks))
    return (comps, slots) if comps else None


def add_ribs(m, plate_of, plates, normals, to2d, parent: list[int], t: float):
    """Costelles interiors per unir els grups de plaques que els suports no han pogut unir.

    Una costella és una secció del model (menys el gruix de les plaques, buidada per dins)
    amb un tenó a cada placa que travessa. Es proven plans perpendiculars i paral·lels a
    l'eix de cada grup solt i als eixos x, y, z, passant pel grup; es queda el que uneix
    més grups i, a igualtat, la costella més petita.

    `parent` diu quins grups han deixat els suports (es va actualitzant). Retorna les
    costelles, el nombre de ranures, els plans (origen, normal), les ranures de cada placa
    i, per a cada costella, les plaques que uneix.
    """
    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ribs: list[Part] = []
    n_slots = 0
    planes, cuts, links = [], {}, []
    for _ in range(RIB_MAX):
        groups: dict[int, list[int]] = {}
        for k in plates:
            groups.setdefault(find(k), []).append(k)
        if len(groups) < 2:
            break
        main = max(groups, key=lambda g: len(groups[g]))
        normals_c, offsets = [np.eye(3)[i] for i in range(3)], []
        for gid, ks in groups.items():
            if gid == main:
                continue
            fs = np.isin(plate_of, ks)
            ns = m.face_normals[fs]
            axis = np.linalg.svd(ns, full_matrices=False)[2][-1]
            normals_c.append(axis / np.linalg.norm(axis))
            offsets.append(m.vertices[np.unique(m.faces[fs])])
        best, best_key = None, None
        for N in normals_c:
            heights = set()
            for pts in offsets:
                h = pts @ N
                heights |= {round(float(x), 3) for x in np.linspace(h.min(), h.max(), 16)[1:-1]}
            for hgt in sorted(heights):
                origin = N * hgt
                cand = rib_candidate(m, plate_of, plates, normals, to2d, origin, N, t)
                if cand is None:
                    continue
                comps, slots = cand
                merged = sum(len({find(k) for k in ks}) - 1 for _, ks in comps)
                area = sum(g.area for g, _ in comps)
                key = (merged, -area)
                if merged > 0 and (best_key is None or key > best_key):
                    best_key, best = key, (N, origin, comps, slots)
        if best is None:
            break
        N, origin, comps, slots = best
        u, v = _plane_basis(N)
        planes.append((origin, N, u, v, unary_union([g for g, _ in comps])))
        for g, ks in comps:
            links.append(ks)
            name = f"K{len(ribs) + 1}"
            part = Part(name, g)
            spot = g.buffer(-2.0)
            spot = spot.representative_point() if not spot.is_empty else g.representative_point()
            part.labels.append((np.array(spot.coords[0]), name, 3.0))
            for k in ks:
                plates[k].shape = plates[k].shape.difference(slots[k])
                cuts.setdefault(k, []).append(slots[k])
                c = np.array(slots[k].centroid.coords[0])
                plates[k].labels.append((c + np.array([0.0, 4.0]), name, 2.5))
                parent[find(k)] = find(ks[0])
                n_slots += 1
            ribs.append(part)
    return ribs, n_slots, planes, cuts, links


def _basis(n: np.ndarray, hint: np.ndarray):
    u = hint - (hint @ n) * n
    if np.linalg.norm(u) < 1e-9:
        u = np.cross(n, [1.0, 0.0, 0.0])
        if np.linalg.norm(u) < 1e-9:
            u = np.cross(n, [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


JOINTS = ("encaix", "cola")


def make_faces(mesh: trimesh.Trimesh, target_faces: int, size_mm: float, thickness: float = 3.0,
               gap: float = 0.0, bracket_mm: float = 25.0, sheet=(600.0, 400.0),
               joint: str = "encaix") -> LaserResult:
    """Plaques i suports per a làser.

    `joint`: "encaix" = suports en arc amb tenons que entren en ranures de les plaques (com
    més ferm; els tenons es veuen com a petits rectangles a la cara de fora); "cola" =
    suports en estel enganxats per dins (del tot invisibles).
    """
    m = pc.scale_to(pc.simplify(pc.clean(mesh), target_faces), size_mm)
    V, F = m.vertices, m.faces
    em = pc.edge_faces(F)
    patch = pc.flat_patches(m, em)
    ids = {pid: i for i, pid in enumerate(dict.fromkeys(int(x) for x in patch))}
    plate_of = np.array([ids[int(x)] for x in patch])
    n_plates = len(ids)

    normals, frames = [], []
    for k in range(n_plates):
        fs = np.nonzero(plate_of == k)[0]
        n = (m.face_normals[fs] * m.area_faces[fs, None]).sum(0)
        n /= np.linalg.norm(n)
        o = V[F[fs[0]][0]]
        u, v = _basis(n, V[F[fs[0]][1]] - o)
        normals.append(n)
        frames.append((o, u, v))

    def to2d(k: int, p3: np.ndarray) -> np.ndarray:
        o, u, v = frames[k]
        d = np.atleast_2d(p3) - o
        return np.column_stack([d @ u, d @ v])

    # Arestes entre plaques, agrupades en trams rectes.
    raw = [(e, fs[0], fs[1]) for e, fs in sorted(em.items())
           if len(fs) == 2 and plate_of[fs[0]] != plate_of[fs[1]]]
    numbers = pc.group_seams(m, raw) if raw else []
    chains: dict[int, list] = {}
    for (e, a, b), n_ in zip(raw, numbers):
        chains.setdefault(n_, []).append((e, a, b))
    seams: list[Seam] = []
    for n_, items in chains.items():
        e, a, b = items[0]
        p, q = int(plate_of[a]), int(plate_of[b])
        pts = np.array([V[v] for e2, _, _ in items for v in e2])
        d = V[e[1]] - V[e[0]]
        d /= np.linalg.norm(d)
        proj = (pts - V[e[0]]) @ d
        e0, e1 = V[e[0]] + d * proj.min(), V[e[0]] + d * proj.max()

        def inward(face: int) -> np.ndarray:
            w = m.triangles_center[face] - e0
            w = w - (w @ d) * d
            return w / np.linalg.norm(w)

        seam = Seam(n_, p, q, e0, e1, inward(a), inward(b), normals[p], normals[q])
        seam.inset = min_inset(seam, thickness)
        seams.append(seam)

    # Plaques: zona plana projectada, retirada a cada aresta.
    shapes = []
    for k in range(n_plates):
        fs = np.nonzero(plate_of == k)[0]
        shapes.append(unary_union([Polygon(to2d(k, V[F[f]])) for f in fs]).buffer(0))
    cuts: dict[int, list] = {k: [] for k in range(n_plates)}
    for seam in seams:
        r = seam.inset + gap / 2
        if r <= 0:
            continue
        for k in (seam.p, seam.q):
            seg = LineString(to2d(k, np.array([seam.e0, seam.e1])))
            cuts[k].append(seg.buffer(r, cap_style=1))

    parts: list[Part] = []
    plates: dict[int, Part] = {}
    lost = 0
    for k in range(n_plates):
        shape = shapes[k]
        if cuts[k]:
            shape = shape.difference(unary_union(cuts[k]))
        if shape.is_empty or shape.area < 1.0:
            lost += 1
            continue
        part = Part(f"C{k + 1}", shape)
        size = float(np.clip(math.sqrt(shape.area) / 6, 2.0, 10.0))
        part.labels.append((np.array(shape.representative_point().coords[0]), f"C{k + 1}", size))
        plates[k] = part
        parts.append(part)

    def footprint(k: int, seam: Seam, c, s: float, reach: float) -> Polygon:
        a3 = seam.a if k == seam.p else seam.b
        d3 = (seam.e1 - seam.e0) / np.linalg.norm(seam.e1 - seam.e0)
        return Polygon(to2d(k, np.array([c + d3 * dt + a3 * da for dt, da in
                       ((-thickness / 2, s), (thickness / 2, s), (thickness / 2, s + reach),
                        (-thickness / 2, s + reach))])))

    def crosses(c, seam: Seam, shape: Polygon, planes) -> bool:
        """El suport (a `c`, amb aquesta secció) travessa el gruix d'alguna costella?"""
        d3 = (seam.e1 - seam.e0) / np.linalg.norm(seam.e1 - seam.e0)
        X, Y = seam.a, -seam.np_
        pts3 = np.array([c + X * x + Y * y + d3 * z for x, y in np.array(shape.exterior.coords)
                         for z in (-thickness / 2, thickness / 2)])
        for origin, N, u, v, rib in planes:
            dist = (pts3 - origin) @ N
            if dist.min() <= thickness / 2 + 0.5 and dist.max() >= -thickness / 2 - 0.5:
                flat = np.column_stack([(pts3 - origin) @ u, (pts3 - origin) @ v])
                if MultiPoint([tuple(p) for p in flat]).convex_hull.buffer(0.5).intersects(rib):
                    return True
        return False

    # Ordre: primer les arestes d'un arbre que uneix totes les plaques (les més llargues
    # primer), després la resta.
    by_len = sorted(seams, key=lambda sm: -np.linalg.norm(sm.e1 - sm.e0))

    def plan(footprints: dict[int, list], parent: list[int], planes) -> list:
        """Tria on va cada suport: llargada del braç i posicions al llarg de l'aresta.

        Cada suport es mou al llarg de l'aresta o s'escurça fins que cap dins les dues
        plaques i no toca cap altre suport, cap ranura ni cap costella.
        """
        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        tmp = parent[:]
        tree, rest = [], []
        for sm in by_len:
            fp, fq = find(sm.p), find(sm.q)
            if fp != fq:
                parent[fp] = fq
                tree.append(sm)
            else:
                rest.append(sm)
        parent[:] = tmp  # ara només compten les unions que de debò porten suport (o costella)
        plans = []
        for seam in tree + rest:
            L = float(np.linalg.norm(seam.e1 - seam.e0))
            s = seam.inset + gap / 2
            count = max(1, int(round(L / BRACKET_SPACING)))
            d3 = (seam.e1 - seam.e0) / L
            leg, centers = None, []
            # El braç va cap a dins de la placa: la mida la limita la placa, no l'aresta.
            legs = [bracket_mm * f for f in (1.0, 0.75, 0.55, 0.4, 0.3)] + [2 * thickness,
                                                                            1.5 * thickness]
            for cand in sorted({round(x, 3) for x in legs if x >= 1.5 * thickness}, reverse=True):
                if L < thickness + 1.0:
                    break
                rough = bracket_shape(seam, thickness, s, cand) if planes else None
                for shift in (0.0, -0.2, 0.2, -0.35, 0.35):
                    fr = [float(np.clip((i + 0.5 + shift) / count, 0.12, 0.88)) for i in range(count)]
                    cs = [seam.e0 + d3 * L * x for x in fr]
                    rects = {k: [footprint(k, seam, c, s, cand) for c in cs] for k in (seam.p, seam.q)}
                    inside = all(k not in plates or plates[k].shape.buffer(0.3).contains(r)
                                 for k, rs in rects.items() for r in rs)
                    if not inside or any(r.buffer(0.5).intersects(o) for k, rs in rects.items()
                                         for r in rs for o in footprints[k]):
                        continue
                    if rough is not None and any(crosses(c, seam, rough, planes) for c in cs):
                        continue
                    leg, centers = cand, cs
                    break
                if leg is not None:
                    break
            if leg is None:
                continue
            for k in (seam.p, seam.q):
                footprints[k] += [footprint(k, seam, c, s, leg) for c in centers]
            parent[find(seam.p)] = find(seam.q)
            plans.append((seam, s, leg, centers))
        return plans

    def groups_of(parent: list[int]) -> dict[int, int]:
        def find(x: int) -> int:
            while parent[x] != x:
                x = parent[x]
            return x
        return {k: find(k) for k in range(n_plates)}

    def final(ribs_on: bool):
        """Suports definitius (i costelles, si cal). Retorna tot el que fa falta per emetre."""
        # 1) Suports només per saber quins grups queden solts.
        trial = list(range(n_plates))
        plan({k: [] for k in range(n_plates)}, trial, [])
        rib_data = ([], 0, [], {}, [])
        if ribs_on and len(set(groups_of(trial).values())) > 1:
            # 2) Costelles per a aquests grups, amb les plaques encara lliures de suports.
            rib_data = add_ribs(m, plate_of, plates, normals, to2d, trial[:], thickness)
        ribs_, rib_slots_, planes_, cuts_, links_ = rib_data
        # 3) Suports que esquiven les ranures i el gruix de les costelles.
        parent_ = list(range(n_plates))
        for ks in links_:
            for k in ks[1:]:
                g = groups_of(parent_)
                parent_[g[ks[0]]] = g[k]
        fps = {k: list(cuts_.get(k, [])) for k in range(n_plates)}
        plans_ = plan(fps, parent_, planes_)
        return plans_, groups_of(parent_), fps, rib_data, len(set(groups_of(trial).values()))

    saved = {k: (p.shape, list(p.labels)) for k, p in plates.items()}
    plans, group, footprints, rib_data, before = final(True)
    if rib_data[0] and len(set(group.values())) >= before:
        # Les costelles no han millorat res (bloquegen més suports dels que estalvien).
        for k, (shape_, labels_) in saved.items():
            plates[k].shape, plates[k].labels = shape_, labels_
        plans, group, footprints, rib_data, _ = final(False)
    ribs, rib_slots, rib_planes, rib_cuts, rib_links = rib_data

    def find(x: int) -> int:
        return group[x]

    brackets = 0
    slots = rib_slots
    planned = {id(seam) for seam, *_ in plans}
    no_bracket = sum(1 for sm in seams if id(sm) not in planned)
    for seam, s, leg, centers in plans:
        L = float(np.linalg.norm(seam.e1 - seam.e0))
        d3 = (seam.e1 - seam.e0) / L
        count = len(centers)
        shape, cut = None, {}
        if L > thickness and joint == "encaix":
            # Un tenó només es queda si la seva ranura cap dins la placa a tots els suports.
            spans = tenon_spans(s, leg, thickness)
            keep = {}
            for k in (seam.p, seam.q):
                a3 = seam.a if k == seam.p else seam.b
                ok = []
                for u0, u1 in spans:
                    rects = [Polygon(to2d(k, np.array([
                        c + d3 * dt + a3 * du for dt, du in
                        ((-thickness / 2 - SLOT_FIT, u0 - SLOT_FIT), (thickness / 2 + SLOT_FIT, u0 - SLOT_FIT),
                         (thickness / 2 + SLOT_FIT, u1 + SLOT_FIT), (-thickness / 2 - SLOT_FIT, u1 + SLOT_FIT))]))
                        ) for c in centers]
                    if k in plates and all(plates[k].shape.buffer(-0.5).contains(r) for r in rects):
                        ok.append((u0, u1))
                        cut.setdefault(k, []).extend(rects)
                keep[k] = ok
            shape = arch_bracket(seam, thickness, s, leg, keep[seam.p], keep[seam.q])
            if shape is not None and rib_planes and any(crosses(c, seam, shape, rib_planes)
                                                        for c in centers):
                shape = None  # l'arc topa amb una costella: estel enganxat
            if shape is None:
                cut = {}
        if shape is None and L > thickness:  # estel enganxat: també és el pla B de l'encaix
            shape = bracket_shape(seam, thickness, s, leg)

        for k in (seam.p, seam.q):  # número d'aresta, ranures i on van els suports
            if k not in plates:
                continue
            part = plates[k]
            a3 = seam.a if k == seam.p else seam.b
            mid = (seam.e0 + seam.e1) / 2
            if count % 2:  # hi ha un suport al mig: el número va al costat
                mid = mid + d3 * min(L / 4, thickness / 2 + 6.0)
            pos = to2d(k, mid + a3 * (s + max(3.0, min(6.0, leg))))[0]
            part.labels.append((pos, f"a{seam.number}", 3.0))
            if k in cut:
                part.shape = part.shape.difference(unary_union(cut[k]))
                slots += len(cut[k])
            if shape is None:
                continue
            for c in centers:
                ring = [c + d3 * dt + a3 * da for dt, da in
                        ((-thickness / 2, s), (thickness / 2, s), (thickness / 2, s + leg),
                         (-thickness / 2, s + leg), (-thickness / 2, s))]
                part.engraves.append(to2d(k, np.array(ring)))
        if shape is None:
            no_bracket += 1
            continue
        for i in range(count):
            part = Part(f"S{seam.number}.{i + 1}", shape)
            spot = shape.buffer(-1.2)
            spot = spot.representative_point() if not spot.is_empty else shape.representative_point()
            part.labels.append((np.array(spot.coords[0]), f"a{seam.number}", 2.5))
            parts.append(part)
            brackets += 1
    parts += ribs

    # Les marques van a la cara interior, que queda amunt en tallar: vista des de dins.
    for part in plates.values():
        part.transform(lambda x: x * np.array([-1.0, 1.0]))

    title = f"Cares · gruix {thickness:g} mm"
    svgs, groups, oversize = nest(parts, sheet, title)
    groups_ = len({find(k) for k in plates})
    stats = dict(plaques=len(plates), suports=brackets, costelles=len(ribs), ranures=slots,
                 arestes=len(seams),
                 grups_de_plaques=groups_,
                 arestes_sense_suport=no_bracket, plaques_perdudes=lost,
                 planxes=len(svgs), massa_grans=oversize)
    notes = [f"Gruix del material: {thickness:g} mm · espai entre cares: {gap:g} mm",
             f"{len(plates)} plaques (C), {brackets} suports (S) i {len(ribs)} costelles (K).",
             "Cada costella (K) travessa amb un tenó les plaques que tenen gravat el seu número.",
             "Les marques gravades van per dins. Cada suport porta el número d'aresta (a) i va",
             "a les dues plaques que tenen aquell número, sobre el rectangle gravat"
             + (": els tenons entren a les ranures." if joint == "encaix" else ", enganxat.")]
    res = LaserResult(svgs, parts, stats, notes, groups)
    # Per a vistes i diagnosi: a quina placa va cada cara i a quin grup de plaques unides.
    res.extra = dict(mesh=m, plate_of=plate_of,
                     group={k: find(k) for k in range(n_plates)},
                     supports={k: sum(1 for fp in footprints[k]) for k in range(n_plates)})
    return res
