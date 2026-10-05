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
from shapely.geometry import LineString, Polygon
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

    brackets = 0
    no_bracket = 0
    slots = 0
    footprints: dict[int, list] = {k: [] for k in range(n_plates)}

    def footprint(k: int, seam: Seam, c, s: float, reach: float) -> Polygon:
        a3 = seam.a if k == seam.p else seam.b
        d3 = (seam.e1 - seam.e0) / np.linalg.norm(seam.e1 - seam.e0)
        return Polygon(to2d(k, np.array([c + d3 * dt + a3 * da for dt, da in
                       ((-thickness / 2, s), (thickness / 2, s), (thickness / 2, s + reach),
                        (-thickness / 2, s + reach))])))

    # Ordre: primer les arestes d'un arbre que uneix totes les plaques (les més llargues
    # primer), després la resta. Cada suport s'escurça fins que no toca cap altre suport de
    # les mateixes plaques (en plaques estretes, els d'arestes veïnes es creuarien).
    parent = list(range(n_plates))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_len = sorted(seams, key=lambda sm: -np.linalg.norm(sm.e1 - sm.e0))
    tree, rest = [], []
    for sm in by_len:
        if find(sm.p) != find(sm.q):
            parent[find(sm.p)] = find(sm.q)
            tree.append(sm)
        else:
            rest.append(sm)
    parent = list(range(n_plates))  # ara compta les unions que de debò porten suport
    for seam in tree + rest:
        L = float(np.linalg.norm(seam.e1 - seam.e0))
        s = seam.inset + gap / 2
        count = max(1, int(round(L / BRACKET_SPACING)))
        d3 = (seam.e1 - seam.e0) / L
        leg, centers = None, []
        for f in (1.0, 0.75, 0.55, 0.4, 0.3):  # primer moure'l al llarg de l'aresta, després escurçar-lo
            cand = min(bracket_mm, 0.5 * L) * f
            if cand < 1.5 * thickness:
                break
            for shift in (0.0, -0.2, 0.2, -0.35, 0.35):
                fr = [float(np.clip((i + 0.5 + shift) / count, 0.12, 0.88)) for i in range(count)]
                cs = [seam.e0 + d3 * L * x for x in fr]
                rects = [footprint(k, seam, c, s, cand) for k in (seam.p, seam.q) for c in cs]
                if not any(r.buffer(0.5).intersects(o) for r in rects
                           for k in (seam.p, seam.q) for o in footprints[k]):
                    leg, centers = cand, cs
                    break
            if leg is not None:
                break
        if leg is None:
            no_bracket += 1
            continue
        for k in (seam.p, seam.q):
            footprints[k] += [footprint(k, seam, c, s, leg) for c in centers]
        parent[find(seam.p)] = find(seam.q)

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
            reach = leg
            for c in centers:
                ring = [c + d3 * dt + a3 * da for dt, da in
                        ((-thickness / 2, s), (thickness / 2, s), (thickness / 2, s + reach),
                         (-thickness / 2, s + reach), (-thickness / 2, s))]
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

    # Les marques van a la cara interior, que queda amunt en tallar: vista des de dins.
    for part in plates.values():
        part.transform(lambda x: x * np.array([-1.0, 1.0]))

    title = f"Cares · gruix {thickness:g} mm"
    svgs, groups, oversize = nest(parts, sheet, title)
    groups_ = len({find(k) for k in plates})
    stats = dict(plaques=len(plates), suports=brackets, ranures=slots, arestes=len(seams),
                 grups_de_plaques=groups_,
                 arestes_sense_suport=no_bracket, plaques_perdudes=lost,
                 planxes=len(svgs), massa_grans=oversize)
    notes = [f"Gruix del material: {thickness:g} mm · espai entre cares: {gap:g} mm",
             f"{len(plates)} plaques (C) i {brackets} suports (S).",
             "Les marques gravades van per dins. Cada suport porta el número d'aresta (a) i va",
             "a les dues plaques que tenen aquell número, sobre el rectangle gravat"
             + (": els tenons entren a les ranures." if joint == "encaix" else ", enganxat.")]
    return LaserResult(svgs, parts, stats, notes, groups)
