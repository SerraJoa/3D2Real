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
import shapely
import trimesh
from shapely.geometry import LineString, MultiPoint, Polygon
from shapely.ops import unary_union

import papercraft as pc
from laser import LaserResult, Part, chamfer, nest, placed, pose, solid

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


ARCH_DEPTH = (1.25, 4.0)  # gruix de l'arc cap a dins: max(factor × gruix, mínim en mm)
KITE_DEPTH = 0.3          # fondària de l'estel, respecte del braç


def _cut_corner(p: np.ndarray, a: np.ndarray, b: np.ndarray, d: float,
                frac: float = 0.95) -> list[np.ndarray]:
    """La cantonada `p` (entre els veïns `a` i `b`) amb un xamfrà de `d` mm, com a molt `frac`
    de cada costat (a l'escletxa, els veïns són els cantells de les plaques: pot arribar-hi)."""
    la, lb = np.linalg.norm(a - p), np.linalg.norm(b - p)
    k = min(d, frac * la, frac * lb)
    if k <= 1e-6:
        return [p]
    return [p + (a - p) / la * k, p + (b - p) / lb * k]


def bracket_shape(seam: Seam, t: float, s: float, leg: float, corner: float = 0.0) -> Polygon | None:
    """Suport en forma d'estel al pla perpendicular a l'aresta (coordenades de la secció).

    Recolza en la cara interior de les dues plaques des del seu cantell (a `s`) fins a
    `s + leg`, i s'obre cap a l'interior del model. Si les plaques estan separades, la punta
    del suport omple l'escletxa i es veu: hi va un xamfrà de `corner` mm.
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
    C = P0 + m * leg * KITE_DEPTH
    tip = [P0]
    uB0 = float((P0 - nb2 * t) @ b2)
    if corner > 0 and s > P0[0] + 1e-3 and s > uB0 + 1e-3:  # punta a l'escletxa
        tip = _cut_corner(P0, B_end, A_end, corner)
    poly = Polygon(tip + [A_end, C, B_end])
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
                 tenons_p: list, tenons_q: list, tip: float = 0.0,
                 corner: float = 0.0) -> Polygon | None:
    """Suport en arc amb tenons, al pla perpendicular a l'aresta (coordenades de la secció).

    La vora de fora ressegueix la cara interior de les dues plaques des del seu cantell
    (a `s`) fins a `s + length`; els tenons travessen les plaques per les ranures; la vora
    de dins és un arc tangent a les dues bandes; als racons còncaus, un arc de cercle per
    darrere la cantonada (o un colze recte si l'arc no hi cap).

    `tip`: xamfrà a les puntes dels tenons (entren més fàcilment a les ranures). `corner`:
    xamfrà a la cantonada del suport quan omple l'escletxa entre plaques separades (es veu).
    """
    b2, nb2 = _section(seam, t)
    P0 = _inner_corner(b2, nb2, t)
    w = max(ARCH_DEPTH[0] * t, ARCH_DEPTH[1])
    Pw = _inner_corner(b2, nb2, t + w)
    if P0 is None or Pw is None:
        return None
    A = lambda u: np.array([u, t])
    B = lambda u: b2 * u + nb2 * t
    out_a, out_b = np.array([0.0, -1.0]), -nb2

    chain = [A(s + length) + np.array([0.0, w]), A(s + length)]
    def peg(P, out, u0, u1):
        """Tenó de u0 a u1 (en aquest ordre), amb la punta xamfranada."""
        c = min(tip, 0.4 * abs(u1 - u0), 0.4 * t)
        if c <= 1e-6:
            return [P(u0), P(u0) + out * t, P(u1) + out * t, P(u1)]
        sg = 1.0 if u1 > u0 else -1.0
        return [P(u0), P(u0) + out * (t - c), P(u0 + sg * c) + out * t,
                P(u1 - sg * c) + out * t, P(u1) + out * (t - c), P(u1)]

    for u0, u1 in sorted(tenons_p, reverse=True):  # de l'extrem cap a l'aresta
        chain += peg(A, out_a, u1, u0)
    # Cap al racó: si les plaques comencen abans de la cantonada interior (sense espai entre
    # cares), es va directe a la cantonada; si no, es ressegueix el cantell fins allà.
    uA0 = P0[0]
    uB0 = float((P0 - nb2 * t) @ b2)
    gap_a, gap_b = s > uA0 + 1e-3, s > uB0 + 1e-3
    if gap_a:
        chain.append(A(s))
    if corner > 0 and gap_a and gap_b:  # la punta omple l'escletxa entre plaques: es veu
        chain += _cut_corner(P0, A(s), B(s), corner)
    else:
        chain.append(P0)
    if gap_b:
        chain.append(B(s))
    for u0, u1 in sorted(tenons_q):
        chain += peg(B, out_b, u0, u1)
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
RIB_SAME_DIR = math.cos(math.radians(2.0))  # direccions de costella que es consideren iguals
RIB_AXES = 6          # eixos de grups solts que es proven (a més de x, y, z), els més grans
RIB_HEIGHTS = 20      # alçades que es proven per a cada direcció
RIB_SECONDS = 10.0    # temps màxim de la cerca de costelles: amb molts grups solts, s'atura


def half_lap(c: np.ndarray, seam: Seam, shape: Polygon, plane, t: float):
    """Encaix a mitja fusta entre un suport (a `c`) i una costella que es creuen.

    Retorna (osques del suport en coordenades de la seva secció, [(peça de costella, osca)]),
    ([], []) si no es toquen, o None si no es pot fer (cap extrem del creuament queda a la
    vora d'una peça i a la vora de l'altra).
    """
    origin, N, u, v, rib_parts = plane
    d3 = (seam.e1 - seam.e0) / np.linalg.norm(seam.e1 - seam.e0)
    X, Y = seam.a, -seam.np_
    a, b, d0 = float(X @ N), float(Y @ N), float((c - origin) @ N)
    ab = math.hypot(a, b)
    rib = unary_union([p.shape for p in rib_parts])
    pts3 = np.array([c + X * x + Y * y + d3 * z for x, y in np.array(shape.exterior.coords)
                     for z in (-t / 2, t / 2)])
    dist = (pts3 - origin) @ N
    if dist.min() > t / 2 + SLOT_FIT or dist.max() < -t / 2 - SLOT_FIT:
        return [], []
    if ab < 0.2:  # plans gairebé paral·lels: no es poden creuar a mitja fusta
        return None
    # Línia on es tallen els plans mitjans, en coordenades de la secció del suport.
    base = -d0 * np.array([a, b]) / ab ** 2
    dirb = np.array([-b, a]) / ab
    to3 = lambda q: c + X * q[0] + Y * q[1]
    to_rib = lambda p: np.array([(p - origin) @ u, (p - origin) @ v])
    far = 1000.0
    line_b = LineString([base - dirb * far, base + dirb * far])
    p_a, p_b = to3(base - dirb * far), to3(base + dirb * far)
    line_r = LineString([to_rib(p_a), to_rib(p_b)])

    # Amplades de les osques: el gruix de l'altra peça vist de biaix, amb joc.
    sin = float(np.linalg.norm(np.cross(d3, N)))
    if sin < 0.2:
        return None
    wb = (t / 2 + SLOT_FIT) / ab + (t / 2) * abs(float(d3 @ N)) / ab
    wr = (t / 2 + SLOT_FIT) / sin + (t / 2) * abs(float(d3 @ N)) / sin

    def spans(geom, line, half: float) -> list[tuple[float, float]]:
        """Trams de la línia on la franja de l'osca (no només la línia) toca la peça."""
        out = []
        inter = geom.intersection(line.buffer(half, cap_style=2))
        for g in getattr(inter, "geoms", [inter]):
            if g.geom_type == "Polygon" and g.area > 1e-6:
                ps = [line.project(shapely.geometry.Point(q)) for q in g.exterior.coords]
                out.append((min(ps), max(ps)))
        return out

    sb, sr = spans(shape, line_b, wb), spans(rib, line_r, wr)
    if not sb or not sr:
        return [], []
    nb = np.array([-dirb[1], dirb[0]])
    r_dir = (to_rib(p_b) - to_rib(p_a)) / np.linalg.norm(to_rib(p_b) - to_rib(p_a))
    nr = np.array([-r_dir[1], r_dir[0]])
    notch_b, notch_r = [], []
    for b0, b1 in sb:
        for r0, r1 in sr:
            lo, hi = max(b0, r0), min(b1, r1)
            if hi - lo < 1e-6:
                continue
            mid = (lo + hi) / 2
            # Cada osca ha de sortir a fora de la seva peça per un extrem (si no, seria un
            # forat tancat i no es podrien encaixar).
            at_b = lambda d: base - dirb * far + dirb * d
            at_r = lambda d: to_rib(p_a) + r_dir * d
            out_b = lambda d: not shape.buffer(-1e-3).contains(shapely.geometry.Point(at_b(d)))
            out_r = lambda d: not rib.buffer(-1e-3).contains(shapely.geometry.Point(at_r(d)))
            if out_b(lo - 0.5) and out_r(hi + 0.5):    # suport osca pel principi, costella pel final
                fb, fr = (lo - 1.0, mid), (mid, hi + 1.0)
            elif out_b(hi + 0.5) and out_r(lo - 0.5):
                fb, fr = (mid, hi + 1.0), (lo - 1.0, mid)
            else:
                return None
            pb0, pb1 = base - dirb * far + dirb * fb[0], base - dirb * far + dirb * fb[1]
            notch_b.append(Polygon([pb0 - nb * wb, pb1 - nb * wb, pb1 + nb * wb, pb0 + nb * wb]))
            pr0, pr1 = to_rib(p_a) + r_dir * fr[0], to_rib(p_a) + r_dir * fr[1]
            notch_r.append(Polygon([pr0 - nr * wr, pr1 - nr * wr, pr1 + nr * wr, pr0 + nr * wr]))
    if not notch_b:
        return [], []
    hits = []
    for n_ in notch_r:
        for p in rib_parts:
            if p.shape.intersects(n_):
                hits.append((p, n_))
    return notch_b, hits


def _plane_basis(N: np.ndarray):
    hint = np.array([1.0, 0, 0]) if abs(N[0]) < 0.9 else np.array([0, 1.0, 0])
    return _basis(N, hint)


def rib_candidate(m, plate_of, plates, normals, to2d, origin, N, t: float, solid_of=None,
                  tip: float = 0.0):
    """Costella al pla (origin, N): forma, tenons i ranures a cada placa que travessa.

    Retorna (components, ranures per placa) o None. Cada component és (forma 2D,
    plaques que hi encaixen, base 3D per tornar al pla). `solid_of(k)` dona la placa k en
    3D: la costella es retalla amb la secció de totes les plaques que talla (també les que hi
    passen massa de biaix per encaixar-hi), perquè no en trepitgi cap.
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
        # De biaix, la costella travessa el gruix en diagonal: a la cara interior (fondària t)
        # el seu pla mig s'ha desplaçat `shift` dins la placa.
        shift = t * float(N @ n) / float(N @ g)
        g0, g1 = min(0.0, shift) - half, max(0.0, shift) + half
        slot = Polygon(to2d(k, np.array([M3 + ell * a + g * b for a, b in
                       ((-tw / 2 - SLOT_FIT, g0), (tw / 2 + SLOT_FIT, g0),
                        (tw / 2 + SLOT_FIT, g1), (-tw / 2 - SLOT_FIT, g1))])))
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
    if solid_of is not None:
        across = []
        for k in plates:
            pm = solid_of(k)
            if pm is None:
                continue
            h = (pm.vertices - origin) @ N
            if h.min() >= t / 2 or h.max() <= -t / 2:
                continue
            for dz in np.linspace(-t / 2, t / 2, 5):  # tot el gruix de la costella
                sg = trimesh.intersections.mesh_plane(pm, N, origin + N * dz)
                if len(sg):
                    across.append(section_polygon([to_plane(x) for x in sg]))
        if across:
            body = body.difference(unary_union(across).buffer(SLOT_FIT, join_style=2))
    def peg(M, e, inw, tw):
        """Tenó des de la cara de fora (M) cap a dins, amb la punta (a fora) xamfranada."""
        D = depth_max + 1.0
        c = min(tip, 0.4 * tw, 0.4 * t)
        if c <= 1e-6:
            return Polygon([M - e * tw / 2, M + e * tw / 2, M + e * tw / 2 + inw * D, M - e * tw / 2 + inw * D])
        return Polygon([M - e * (tw / 2 - c), M + e * (tw / 2 - c), M + e * tw / 2 + inw * c,
                        M + e * tw / 2 + inw * D, M - e * tw / 2 + inw * D, M - e * tw / 2 + inw * c])

    pegs = {k: peg(*v) for k, v in tenons.items()}
    shape = unary_union([body] + list(pegs.values()))
    comps = []
    for g in getattr(shape, "geoms", [shape]):
        ks = [k for k, p in pegs.items() if g.intersection(p).area > 0.5 * p.area]
        if len(ks) >= 2:
            comps.append((g, ks))
    return (comps, slots) if comps else None


def add_ribs(m, plate_of, plates, normals, to2d, parent: list[int], t: float, solid_of=None,
             fast: bool = False, tip: float = 0.0):
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

    import time
    # Ràpid (opcional): menys plans i un temps màxim. Amb molts grups solts la cerca
    # completa creix amb el quadrat dels grups, però pot unir-ne més.
    deadline = time.monotonic() + RIB_SECONDS if fast else math.inf
    plate_pts = {k: m.vertices[np.unique(m.faces[plate_of == k])] for k in plates}
    # Una placa només pot rebre el tenó d'una costella si hi cap la ranura (d'amplada ≥ t, a
    # 0,5 mm de la vora): encongida t/2 + 0,5 mm encara n'ha de quedar alguna cosa.
    roomy = {k for k, p in plates.items() if not p.shape.buffer(-(t / 2 + 0.5)).is_empty}
    # Les costelles candidates es guarden d'una ronda a l'altra: en afegir una costella només
    # canvien les plaques on entra (ranures noves), i només cal refer les que hi tenien tenó.
    tried: dict[tuple, tuple | None] = {}
    ribs: list[Part] = []
    n_slots = 0
    planes, cuts, links = [], {}, []
    for _ in range(RIB_MAX):
        if time.monotonic() > deadline:
            break
        groups: dict[int, list[int]] = {}
        for k in plates:
            groups.setdefault(find(k), []).append(k)
        if len(groups) < 2:
            break
        main = max(groups, key=lambda g: len(groups[g]))
        normals_c, offsets = [np.eye(3)[i] for i in range(3)], []
        loose = sorted((g for g in groups if g != main), key=lambda g: -len(groups[g]))
        for gid in (loose[:RIB_AXES] if fast else loose):
            ks = groups[gid]
            fs = np.isin(plate_of, ks)
            ns = m.face_normals[fs]
            axis = np.linalg.svd(ns, full_matrices=False)[2][-1]
            axis = axis / np.linalg.norm(axis)
            # Direccions gairebé iguals (a menys de 2°) donen els mateixos plans: només una.
            if all(abs(float(axis @ n_)) < RIB_SAME_DIR for n_ in normals_c):
                normals_c.append(axis)
            offsets.append(m.vertices[np.unique(m.faces[fs])])
        # Quins grups pot unir cada pla, com a molt: els de les plaques que talla (es veu
        # només amb l'alçada dels vèrtexs). Es construeixen les costelles dels plans que en
        # poden unir més primer, i es descarten els que ja no poden igualar la millor.
        ks_all = sorted(roomy)
        gid = np.array([find(k) for k in ks_all])
        tries = []
        for N in normals_c:
            heights = set()
            for pts in offsets:
                h = pts @ N
                heights |= {round(float(x), 3) for x in np.linspace(h.min(), h.max(), 16)[1:-1]}
            # Alçades a menys de mig gruix l'una de l'altra donen pràcticament la mateixa
            # costella: només la primera (amb molts grups petits, n'hi ha milers d'arrambades).
            kept = []
            for h_ in sorted(heights):
                if not kept or h_ - kept[-1] >= t / 2:
                    kept.append(h_)
            heights = kept
            if fast and len(heights) > RIB_HEIGHTS:  # molts grups: una mostra repartida
                heights = [heights[i] for i in np.linspace(0, len(heights) - 1, RIB_HEIGHTS).astype(int)]
            proj = [plate_pts[k] @ N for k in ks_all]
            lo = np.array([p.min() for p in proj])
            hi = np.array([p.max() for p in proj])
            # Una placa gairebé paral·lela al pla no pot rebre tenó.
            slanted = np.array([np.linalg.norm(np.cross(normals[k], N)) >= RIB_MIN_SIN for k in ks_all],
                               dtype=bool)
            for hgt in heights:
                crossed = gid[(lo < hgt) & (hi > hgt) & slanted]
                bound = len(set(crossed.tolist())) - 1
                if bound > 0:
                    tries.append((bound, len(tries), N, hgt))
        found = []
        top = 0
        for bound, idx, N, hgt in sorted(tries, key=lambda x: (-x[0], x[1])):
            if bound < top or time.monotonic() > deadline:
                break
            origin = N * hgt
            key_ = (*np.round(N, 9).tolist(), hgt)
            if key_ not in tried:
                tried[key_] = rib_candidate(m, plate_of, plates, normals, to2d, origin, N, t, tip=tip)
            cand = tried[key_]
            if cand is None:
                continue
            comps, slots = cand
            merged = sum(len({find(k) for k in ks}) - 1 for _, ks in comps)
            area = sum(g.area for g, _ in comps)
            if merged > 0:
                top = max(top, merged)
                found.append(((merged, -area), idx, N, origin))
        found = [(key, N, origin) for key, idx, N, origin in
                 sorted(found, key=lambda x: (-x[0][0], -x[0][1], x[1]))]
        # Els millors plans, ara retallats amb la secció exacta de les plaques que travessen.
        best, best_key = None, None
        for key, N, origin in found[:6]:
            if best_key is not None and key[0] < best_key[0]:
                break
            cand = rib_candidate(m, plate_of, plates, normals, to2d, origin, N, t, solid_of, tip)
            if cand is None:
                continue
            comps, slots = cand
            merged = sum(len({find(k) for k in ks}) - 1 for _, ks in comps)
            key = (merged, -sum(g.area for g, _ in comps))
            if merged > 0 and (best_key is None or key > best_key):
                best_key, best = key, (N, origin, comps, slots)
        if best is None:
            break
        N, origin, comps, slots = best
        changed = {k for _, ks in comps for k in ks}
        tried = {key_: c for key_, c in tried.items() if c is None or not (set(c[1]) & changed)}
        u, v = _plane_basis(N)
        plane_parts: list[Part] = []
        planes.append((origin, N, u, v, plane_parts))
        for g, ks in comps:
            links.append(ks)
            name = f"K{len(ribs) + 1}"
            part = Part(name, g)
            part.pose = pose(u, v, N, origin, -t / 2, t / 2)
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
            plane_parts.append(part)
    return ribs, n_slots, planes, cuts, links


def _basis(n: np.ndarray, hint: np.ndarray):
    u = hint - (hint @ n) * n
    if np.linalg.norm(u) < 1e-9:
        u = np.cross(n, [1.0, 0.0, 0.0])
        if np.linalg.norm(u) < 1e-9:
            u = np.cross(n, [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def decorate_plates(m, plates: dict, to2d, footprints: dict, decor: dict | None, texture):
    """Grava i/o talla les decoracions de cada cara a la seva placa.

    Retorna (imatges per a les planxes, plaques amb gravat decoratiu, forats tallats).
    Els forats sempre deixen un marc (decor.CUT_MIN_FRAME) i 2 mm lliures al voltant de
    ranures i suports.
    """
    import dataclasses
    import shapely
    import decor as dc
    images: dict = {}
    face_up: set[int] = set()
    n_holes = 0
    if not decor:
        return images, face_up, n_holes
    V, F = m.vertices, m.faces
    frames = dc.face_frames(m)
    for k, spec in decor.items():
        if k not in plates or k >= len(frames):
            continue
        fr, part = frames[k], plates[k]
        f0 = fr.faces[0]
        M = dc.affine_from(fr.to_local(V[F[f0]]), to2d(k, V[F[f0]]))
        to_plate = lambda g, M=M: shapely.transform(g, lambda q: dc.apply_affine(M, q))
        if spec.laser in ("gravar", "gravar i tallar"):
            if spec.kind == "textura":
                if texture is None:
                    continue
                images["tex"] = (dc._png(texture.image.convert("L")), *texture.image.size)
                clip_l = fr.shape.buffer(-spec.frame) if spec.frame > 0 else fr.shape
                for f, Mt in dc.texture_ops(fr, m, texture, spec):
                    tri = Polygon(to2d(k, V[F[f]])).buffer(0.05)
                    clip = tri.intersection(to_plate(clip_l)).intersection(part.shape)
                    part.decor.append(dc.DecorOp(
                        f'<use href="#tex" transform="{dc.svg_matrix(Mt)}"/>', M, clip))
            else:
                src = dc.build_source(fr, spec)
                for key, png, w, h, _ in src.images:
                    images[key] = (dc._png(__import__("PIL.Image", fromlist=["Image"]).open(
                        __import__("io").BytesIO(png)).convert("L")), w, h)
                part.decor.append(dc.DecorOp(dc.engrave_content(src, spec), M,
                                             to_plate(src.clip).intersection(part.shape)))
            face_up.add(k)
        if spec.laser in ("tallar", "gravar i tallar") and spec.kind != "textura":
            src = dc.build_source(fr, dataclasses.replace(spec, frame=max(spec.frame,
                                                                          dc.CUT_MIN_FRAME)))
            if src.holes is None or src.holes.is_empty:
                continue
            keep = [o.buffer(2.0) for o in footprints.get(k, [])]
            keep += [Polygon(h).buffer(2.0) for g in getattr(part.shape, "geoms", [part.shape])
                     for h in g.interiors]
            # El marc es mesura des de la vora de la placa (ja retirada pel gruix), no de la cara.
            inner = unary_union([Polygon(g.exterior) for g in getattr(part.shape, "geoms", [part.shape])])
            holes = to_plate(src.holes).intersection(
                inner.buffer(-max(spec.frame, dc.CUT_MIN_FRAME), join_style=2))
            if keep:
                holes = holes.difference(unary_union(keep))
            holes = [h for h in getattr(holes, "geoms", [holes])
                     if h.geom_type == "Polygon" and h.area > 1.0]
            if holes:
                part.shape = part.shape.difference(unary_union(holes))
                n_holes += len(holes)
    return images, face_up, n_holes


JOINTS = ("encaix", "cola")


def make_faces(mesh: trimesh.Trimesh, target_faces: int, size_mm: float, thickness: float = 3.0,
               gap: float = 0.0, bracket_mm: float = 25.0, sheet=(600.0, 400.0),
               joint: str = "encaix", decor: dict | None = None, texture=None,
               fast_ribs: bool = False, bracket_spacing: float = BRACKET_SPACING,
               chamfer_mm: float = 0.0, tenon_chamfer: float = 0.0) -> LaserResult:
    """Plaques i suports per a làser.

    `joint`: "encaix" = suports en arc amb tenons que entren en ranures de les plaques (com
    més ferm; els tenons es veuen com a petits rectangles a la cara de fora); "cola" =
    suports en estel enganxats per dins (del tot invisibles).

    `decor` ({índex de placa: decor.DecorSpec}) grava o talla textures, imatges, patrons o
    dibuixos a les cares; `texture` és la decor.Texture de la malla original.

    `chamfer_mm`: xamfrà a les cantonades convexes del contorn de les plaques (no als forats ni
    a les ranures), per a l'efecte (sobretot amb llum a dins); també a la punta dels suports
    quan omple l'escletxa entre plaques separades, que es veu. `tenon_chamfer`: xamfrà a les
    puntes dels tenons de suports i costelles, perquè entrin més fàcilment (0,5–1 mm).

    `bracket_spacing`: mm d'aresta per suport (menys i més grans, o més i més petits, combinat
    amb `bracket_mm`). `fast_ribs` limita la cerca de costelles (menys plans, com a molt RIB_SECONDS): molt més
    ràpid amb molts grups de plaques solts, però en pot deixar més sense unir.
    """
    if texture is not None:
        import decor as dc
        m, texture = dc.prepare(mesh, target_faces, size_mm, texture)
    else:
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
        o, u, v = frames[k]
        part.pose = pose(u, v, -normals[k], o, 0.0, thickness)  # el gruix creix cap endins
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

    def laps(c, seam: Seam, shape: Polygon, planes):
        """Osques a mitja fusta amb totes les costelles que creua; None si n'hi ha cap d'impossible."""
        notch_b, notch_r = [], []
        for plane in planes:
            res = half_lap(c, seam, shape, plane, thickness)
            if res is None:
                return None
            notch_b += res[0]
            notch_r += res[1]
        return notch_b, notch_r

    # Ordre: primer les arestes d'un arbre que uneix totes les plaques (les més llargues
    # primer), després la resta.
    by_len = sorted(seams, key=lambda sm: -np.linalg.norm(sm.e1 - sm.e0))

    def envelope(seam: Seam, s: float, leg: float):
        """Tot el que pot ocupar el suport a la seva secció: l'arc amb tots els tenons i l'estel."""
        shapes = [bracket_shape(seam, thickness, s, leg)]
        if joint == "encaix":
            spans = tenon_spans(s, leg, thickness)
            shapes.append(arch_bracket(seam, thickness, s, leg, spans, spans))
        shapes = [g for g in shapes if g is not None]
        return unary_union(shapes) if shapes else None

    def body(seam: Seam, c, env):
        """El suport en 3D (amb 0,3 mm de marge pels costats), per veure si xoca."""
        d3 = (seam.e1 - seam.e0) / np.linalg.norm(seam.e1 - seam.e0)
        return solid(env, pose(seam.a, -seam.np_, d3, c, 0, 0)[0], -thickness / 2 - 0.3,
                     thickness / 2 + 0.3)

    plate_solids: dict[int, tuple] = {}

    def plate_solid(k: int):
        shape = plates[k].shape
        if k not in plate_solids or plate_solids[k][0] is not shape:
            o, u, v = frames[k]
            plate_solids[k] = (shape, solid(shape, pose(u, v, -normals[k], o, 0, 0)[0], 0.0, thickness))
        return plate_solids[k][1]

    def near(a, objs: list) -> list:
        """Els objectes la capsa dels quals toca la d'`a` (filtre ràpid abans de l'operació 3D)."""
        objs = [o for o in objs if o is not None]
        if a is None or not objs:
            return []
        B = np.array([o.bounds for o in objs])
        ok = np.all(B[:, 0] <= a.bounds[1], axis=1) & np.all(B[:, 1] >= a.bounds[0], axis=1)
        return [o for o, k in zip(objs, ok) if k]

    def clash(a, b) -> bool:
        if a is None or b is None:
            return False
        inter = trimesh.boolean.intersection([a, b], engine="manifold")
        if inter.is_empty:
            return False
        # Si només es toquen per una cara, la intersecció no té volum i trimesh avisaria
        # (divisió per zero en calcular el centre de massa).
        with np.errstate(divide="ignore", invalid="ignore"):
            return inter.volume > 0.05

    grown: dict[int, tuple] = {}

    def fits(k: int, rect: Polygon, taken: list) -> bool:
        """La petjada cap dins la placa (eixamplada 0,3 mm, calculada un sol cop per forma) i
        queda a més de 0,5 mm de les altres petjades i ranures de la placa (totes alhora)."""
        if k in plates:
            shape = plates[k].shape
            if k not in grown or grown[k][0] is not shape:
                g = shape.buffer(0.3)
                shapely.prepare(g)
                grown[k] = (shape, g)
            if not grown[k][1].contains(rect):
                return False
        return not taken or not shapely.dwithin(rect, np.array(taken, dtype=object), 0.5).any()

    def plan(footprints: dict[int, list], parent: list[int], planes, upgrade: bool = True) -> list:
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
        bodies = []  # suports ja posats, en 3D
        legs = [bracket_mm * f for f in (1.0, 0.75, 0.55, 0.4, 0.3)] + [2 * thickness,
                                                                        1.5 * thickness]
        # El braç va cap a dins de la placa: la mida la limita la placa, no l'aresta.
        legs = sorted({round(x, 3) for x in legs if x >= 1.5 * thickness}, reverse=True)

        def place(seam: Seam, s: float, options):
            """Primera opció (braç, nombre de suports) que hi cap: (braç, centres, cossos 3D)."""
            L = float(np.linalg.norm(seam.e1 - seam.e0))
            if L < thickness + 1.0:
                return None
            d3 = (seam.e1 - seam.e0) / L
            others = None  # plaques en 3D: només si algun suport cap a les plaques (és car)
            envs: dict[float, Polygon | None] = {}
            for cand, n in options:
                rough = bracket_shape(seam, thickness, s, cand) if planes else None
                for shift in (0.0, -0.2, 0.2, -0.35, 0.35):
                    fr = [float(np.clip((i + 0.5 + shift) / n, 0.12, 0.88)) for i in range(n)]
                    cs = [seam.e0 + d3 * L * x for x in fr]
                    if not all(fits(k, footprint(k, seam, c, s, cand), footprints[k])
                               for k in (seam.p, seam.q) for c in cs):
                        continue
                    if n > 1:  # els suports de la mateixa aresta tampoc es poden tocar entre ells
                        own = [footprint(seam.p, seam, c, s, cand) for c in cs]
                        if any(own[i].distance(own[j]) < 0.5 for i in range(n) for j in range(i)):
                            continue
                    # Els suports deixen pas a les costelles (mitja fusta); si no es pot, l'esquiven.
                    if rough is not None and any(laps(c, seam, rough, planes) is None for c in cs):
                        continue
                    # Dins del model, l'arc no pot tocar cap altre suport ni cap altra placa
                    # (als vèrtexs on es troben moltes plaques, com la punta d'un con).
                    if others is None:
                        others = [plate_solid(k) for k in plates if k not in (seam.p, seam.q)]
                    if cand not in envs:
                        envs[cand] = envelope(seam, s, cand)
                    env = envs[cand]
                    news = [body(seam, c, env) for c in cs] if env is not None else []
                    if any(clash(nb, o) for nb in news for o in near(nb, bodies + others)):
                        continue
                    return cand, cs, news
            return None

        def more(seam: Seam, count: int, above: float):
            """Opcions amb més suports i més petits que donen més braç total que `above`:
            primer les de més braç total (fins al del suport triat) i, a igualtat, menys suports."""
            L = float(np.linalg.norm(seam.e1 - seam.e0))
            most = min(3 * count, int(L // (thickness + 4.0)))
            opts = [(c, n) for c in legs for n in range(count + 1, most + 1)
                    if min(c * n, bracket_mm * count) > above + 1e-6]
            return sorted(opts, key=lambda o: (-min(o[0] * o[1], bracket_mm * count), o[1], -o[0]))

        def put(seam: Seam, s: float, got) -> tuple:
            leg, centers, news = got
            fps = {k: [footprint(k, seam, c, s, leg) for c in centers] for k in (seam.p, seam.q)}
            for k, fs in fps.items():
                footprints[k] += fs
            bodies.extend(news)
            return fps, news

        # 1) Un suport (o els que toquin per la distància triada) a cada aresta, el més gran que
        #    hi càpiga; si no n'hi cap cap, més suports i més petits.
        placed = []
        for seam in tree + rest:
            L = float(np.linalg.norm(seam.e1 - seam.e0))
            s = seam.inset + gap / 2
            count = max(1, int(round(L / bracket_spacing)))
            got = place(seam, s, [(c, count) for c in legs]) or place(seam, s, more(seam, count, 0.0))
            if got is None:
                continue
            fps, news = put(seam, s, got)
            parent[find(seam.p)] = find(seam.q)
            placed.append([seam, s, count, got, fps, news])
        # 2) Quan ja totes les arestes tenen el seu, les que s'han quedat amb suports petits
        #    proven més suports de mitjans (sense treure lloc a cap altra aresta).
        for item in placed if upgrade else []:
            seam, s, count, got, fps, news = item
            total = got[0] * len(got[1])
            if total >= 0.75 * bracket_mm * count:
                continue
            for k, fs in fps.items():
                footprints[k] = [f for f in footprints[k] if all(f is not g for g in fs)]
            bodies[:] = [b for b in bodies if all(b is not g for g in news)]
            better = place(seam, s, more(seam, count, total))
            item[3:] = [better or got, *put(seam, s, better or got)]
        return [(seam, s, got[0], got[1]) for seam, s, count, got, fps, news in placed]

    def groups_of(parent: list[int]) -> dict[int, int]:
        def find(x: int) -> int:
            while parent[x] != x:
                x = parent[x]
            return x
        return {k: find(k) for k in range(n_plates)}

    first: dict = {}

    def final(ribs_on: bool):
        """Suports definitius (i costelles, si cal). Retorna tot el que fa falta per emetre."""
        # 1) Suports sense costelles: diuen quins grups queden solts i, si no cal cap
        #    costella (o les costelles no milloren res), ja són els definitius. Es calculen
        #    un sol cop.
        if not first:
            trial = list(range(n_plates))
            fps_t = {k: [] for k in range(n_plates)}
            first.update(plans=plan(fps_t, trial, []), parent=trial, fps=fps_t)
        trial = first["parent"]
        before = len(set(groups_of(trial).values()))
        if ribs_on and before > 1:
            # 2) Costelles per a aquests grups, amb les plaques encara lliures de suports.
            rib_data = add_ribs(m, plate_of, plates, normals, to2d, trial[:], thickness, plate_solid,
                                fast_ribs, tenon_chamfer)
            ribs_, rib_slots_, planes_, cuts_, links_ = rib_data
            if ribs_:
                # 3) Suports que esquiven les ranures i el gruix de les costelles.
                parent_ = list(range(n_plates))
                for ks in links_:
                    for k in ks[1:]:
                        g = groups_of(parent_)
                        parent_[g[ks[0]]] = g[k]
                fps = {k: list(cuts_.get(k, [])) for k in range(n_plates)}
                plans_ = plan(fps, parent_, planes_)
                return plans_, groups_of(parent_), fps, rib_data, before
        return first["plans"], groups_of(trial), first["fps"], ([], 0, [], {}, []), before

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
    laps_made = [0]
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
            shape = arch_bracket(seam, thickness, s, leg, keep[seam.p], keep[seam.q],
                                 tip=tenon_chamfer, corner=chamfer_mm)
            if shape is not None and rib_planes and any(laps(c, seam, shape, rib_planes) is None
                                                        for c in centers):
                shape = None  # l'arc no pot encaixar amb una costella: estel enganxat
            if shape is None:
                cut = {}
        if shape is None and L > thickness:  # estel enganxat: també és el pla B de l'encaix
            shape = bracket_shape(seam, thickness, s, leg, corner=chamfer_mm)

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
        for i, c in enumerate(centers):
            lap = laps(c, seam, shape, rib_planes) if rib_planes else ([], [])
            own = shape
            if lap is None:
                continue
            if lap[0]:  # osca per deixar pas a la costella, i l'osca complementària a la costella
                own = shape.difference(unary_union(lap[0]))
                for rib_part, notch in lap[1]:
                    rib_part.shape = rib_part.shape.difference(notch)
                laps_made[0] += len(lap[0])
            part = Part(f"S{seam.number}.{i + 1}", own)
            part.pose = pose(seam.a, -seam.np_, d3, c, -thickness / 2, thickness / 2)
            spot = own.buffer(-1.2)
            spot = spot.representative_point() if not spot.is_empty else own.representative_point()
            part.labels.append((np.array(spot.coords[0]), f"a{seam.number}", 2.5))
            parts.append(part)
            brackets += 1
    parts += ribs
    for part in plates.values():  # abans de decorar: el marc de la decoració segueix el xamfrà
        part.shape = chamfer(part.shape, chamfer_mm)

    images, face_up, decor_holes = decorate_plates(m, plates, to2d, footprints, decor, texture)

    # Les marques van a la cara interior, que queda amunt en tallar: vista des de dins. Les
    # plaques amb gravat decoratiu es tallen amb la cara de fora amunt (marques de referència).
    assembly = placed(parts)  # abans de girar-les per a la planxa
    for k, part in plates.items():
        if k in face_up:
            part.to_guides()
        else:
            part.transform(lambda x: x * np.array([-1.0, 1.0]))

    title = f"Cares · gruix {thickness:g} mm"
    svgs, groups, oversize = nest(parts, sheet, title, images)
    groups_ = len({find(k) for k in plates})
    stats = dict(plaques=len(plates), suports=brackets, costelles=len(ribs), ranures=slots,
                 arestes=len(seams),
                 grups_de_plaques=groups_, mitges_fustes=laps_made[0],
                 decorades=len({k for k in (decor or {}) if k in plates}),
                 forats_decoratius=decor_holes,
                 arestes_sense_suport=no_bracket, plaques_perdudes=lost,
                 planxes=len(svgs), massa_grans=oversize)
    notes = [f"Gruix del material: {thickness:g} mm · espai entre cares: {gap:g} mm",
             f"{len(plates)} plaques (C), {brackets} suports (S) i {len(ribs)} costelles (K).",
             "Cada costella (K) travessa amb un tenó les plaques que tenen gravat el seu número.",
             "Les marques gravades van per dins. Cada suport porta el número d'aresta (a) i va",
             *([f"Les plaques {', '.join(f'C{k + 1}' for k in sorted(face_up))} porten gravat "
                "decoratiu: es tallen amb la cara de fora amunt i les seves marques de muntatge "
                "(en verd) són només de referència."] if face_up else []),
             "a les dues plaques que tenen aquell número, sobre el rectangle gravat"
             + (": els tenons entren a les ranures." if joint == "encaix" else ", enganxat.")]
    res = LaserResult(svgs, parts, stats, notes, groups)
    # Per a vistes i diagnosi: a quina placa va cada cara i a quin grup de plaques unides.
    res.extra = dict(mesh=m, plate_of=plate_of, assembly=assembly,
                     group={k: find(k) for k in range(n_plates)},
                     supports={k: sum(1 for fp in footprints[k]) for k in range(n_plates)})
    return res
