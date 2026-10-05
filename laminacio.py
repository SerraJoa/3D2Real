"""Branca de laminació: la figura es talla en capes del gruix del material per muntar-les apilades.

- Capes horitzontals (eix z del model) d'alçada igual al gruix; cada capa es talla pel seu pla mig.
- Columnes passants: forats rodons alineats que travessen capes consecutives per posar-hi tiges.
  Cada tros de capa en rep almenys dos (fixen posició i gir), separats entre ells i lluny de
  les vores.
- Marques gravades a la cara de dalt de cada capa: número (llegible = cara amunt), fletxa
  d'orientació comuna a totes les capes, contorn de la capa de sobre (continu) i de la de
  sota (en ratlles) on queden dins de la peça: el solapament.
"""
from __future__ import annotations

import math

import numpy as np
import shapely
import trimesh
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
import shapely.ops
from shapely.ops import polygonize, unary_union

import papercraft as pc
from laser import LaserResult, Part, nest

COLUMN_WALL = 2.0     # mm mínims de material entre un forat i la vora
COLUMN_FIT = 0.1      # mm de joc al forat respecte de la tiga
COLUMN_SEP = 2.0      # separació mínima entre centres de columnes, en diàmetres
COLUMNS_PER_PIECE = 2


def section_polygon(segments2d) -> Polygon:
    """Polígon (amb forats, parell/senar) que tanquen uns segments 2D d'una secció."""
    lines = [LineString(np.round(s, 6)) for s in segments2d if np.linalg.norm(s[0] - s[1]) > 1e-9]
    if not lines:
        return Polygon()
    faces = list(polygonize(unary_union(lines)))
    geom = Polygon()
    for f in faces:  # parell/senar: un anell dins d'un altre és un forat
        geom = geom.symmetric_difference(Polygon(f.exterior))
    return geom.buffer(0)


def slice_at(mesh: trimesh.Trimesh, z: float):
    """Secció de la malla al pla horitzontal z, com a (Multi)Polygon amb forats."""
    segs = trimesh.intersections.mesh_plane(mesh, [0, 0, 1], [0, 0, z])
    if len(segs) == 0:
        return Polygon()
    return section_polygon([s[:, :2] for s in segs])


def _islands(geom) -> list[Polygon]:
    return [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon" and g.area > 0.5]


def place_columns(layers: list[list[Polygon]], d: float):
    """Tria columnes (x, y, capa inicial, capa final) perquè cada tros en tingui prou.

    Candidats en graella; una columna ocupa capes consecutives on el punt és prou dins del
    tros (radi + paret). Cada vegada es tria la columna que cobreix més trossos que encara
    en necessiten, sense acostar-se massa a les ja triades; a igualtat, la més allunyada.
    """
    r = d / 2 + COLUMN_FIT
    allg = unary_union([g for lay in layers for g in lay])
    if allg.is_empty:
        return []
    x0, y0, x1, y1 = allg.bounds
    step = max(d, min(x1 - x0, y1 - y0) / 40)
    xs, ys = np.meshgrid(np.arange(x0 + step / 2, x1, step), np.arange(y0 + step / 2, y1, step))
    pts = [np.column_stack([xs.ravel(), ys.ravel()])]
    # Trossos estrets (cames, braços) poden quedar entre punts de la graella: cada tros hi
    # afegeix un punt interior i els dos extrems més allunyats de la seva zona segura.
    for lay in layers:
        for g in lay:
            safe = g.buffer(-(r + COLUMN_WALL))
            if safe.is_empty:
                continue
            c = np.array(safe.representative_point().coords[0])
            hull = np.array(getattr(safe.convex_hull, "exterior", safe.convex_hull).coords)
            dist = np.linalg.norm(hull[:, None] - hull[None], axis=2)
            i, j = np.unravel_index(np.argmax(dist), dist.shape)
            pts.append(np.array([c, c + 0.9 * (hull[i] - c), c + 0.9 * (hull[j] - c)]))
    xs, ys = np.vstack(pts).T
    K, N = len(layers), len(xs)
    island = np.full((K, N), -1)
    need: dict[tuple[int, int], int] = {}
    for k, lay in enumerate(layers):
        for j, g in enumerate(lay):
            safe = g.buffer(-(r + COLUMN_WALL))
            if safe.is_empty:
                continue
            inside = shapely.contains_xy(safe, xs, ys)
            island[k, inside] = j
            n_in = int(inside.sum())
            if n_in:
                far = np.ptp(xs[inside]) + np.ptp(ys[inside]) >= COLUMN_SEP * d
                need[(k, j)] = COLUMNS_PER_PIECE if far else 1
    min_sep = COLUMN_SEP * d
    columns: list[tuple[float, float, int, int]] = []
    blocked = np.zeros((K, N), dtype=bool)
    while True:
        want = np.zeros((K, N))
        for (k, j), n in need.items():
            if n > 0:
                want[k] += island[k] == j
        valid = (island >= 0) & ~blocked
        best, best_key = None, None
        for c in np.nonzero(valid.any(0) & (want.sum(0) > 0))[0]:
            k = 0
            while k < K:
                if not valid[k, c]:
                    k += 1
                    continue
                k0 = k
                while k < K and valid[k, c]:
                    k += 1
                gain = want[k0:k, c].sum()
                if gain <= 0:
                    continue
                spread = min((math.hypot(xs[c] - x, ys[c] - y) for x, y, a, b in columns
                              if a < k and b >= k0), default=1e9)
                key = (gain, min(spread, 1e6), k - k0)
                if best_key is None or key > best_key:
                    best_key, best = key, (int(c), k0, k - 1)
        if best is None:
            break
        c, k0, k1 = best
        columns.append((float(xs[c]), float(ys[c]), k0, k1))
        for k in range(k0, k1 + 1):
            j = island[k, c]
            if need.get((k, j), 0) > 0:
                need[(k, j)] -= 1
            blocked[k] |= np.hypot(xs - xs[c], ys - ys[c]) < min_sep
    return columns


def _arrow(p: np.ndarray, size: float) -> list[np.ndarray]:
    """Fletxa cap a +y (el davant del model) per orientar totes les capes igual."""
    x, y = p
    h = size / 2
    return [np.array([(x, y - h), (x, y + h)]),
            np.array([(x - h / 2, y + h / 2), (x, y + h), (x + h / 2, y + h / 2)])]


def _lines(geom) -> list[np.ndarray]:
    out = []
    for g in getattr(geom, "geoms", [geom]):
        if g.geom_type in ("LineString", "LinearRing") and g.length > 0.5:
            out.append(np.array(g.coords))
    return out


def _dashed(lines: list[np.ndarray], dash: float = 2.0, space: float = 1.5) -> list[np.ndarray]:
    """Talla cada polilínia en traços: el gravat en ratlles distingeix la capa de sota."""
    out = []
    for c in lines:
        line = LineString(c)
        pos = 0.0
        while pos < line.length:
            seg = shapely.ops.substring(line, pos, min(pos + dash, line.length))
            if seg.length > 0.1:
                out.append(np.array(seg.coords))
            pos += dash + space
    return out


def hollow(geoms: list, wall: float, thickness: float, columns=(), column_d: float = 0.0) -> list:
    """Buida les capes deixant una paret de `wall` mm per tots costats, també per dalt i baix.

    El forat de cada capa és la seva secció retirada `wall`, intersecada amb la de les capes
    veïnes fins a `wall` mm amunt i avall: així la cavitat no arriba mai a la superfície, i
    les primeres i últimes capes (o les de sota d'un sostre pla) queden massisses.

    Al voltant de cada columna que passa per la cavitat es deixa una anella de material
    unida a la paret per un pont: les columnes no es mouen i cada capa continua sent una peça.
    """
    r = column_d / 2 + COLUMN_FIT
    K = len(geoms)
    reach = max(1, int(math.ceil(wall / thickness)))
    eroded = [g.buffer(-wall) if not g.is_empty else Polygon() for g in geoms]
    out = []
    for k, g in enumerate(geoms):
        hole = eroded[k]
        for j in range(k - reach, k + reach + 1):
            if hole.is_empty:
                break
            hole = hole.intersection(eroded[j]) if 0 <= j < K else Polygon()
        hole = hole.buffer(0)
        keep = []
        for x, y, a, b in columns:
            if a <= k <= b and not hole.is_empty and hole.buffer(r + COLUMN_WALL).contains(Point(x, y)):
                p = Point(x, y)
                edge = shapely.ops.nearest_points(p, g.exterior if g.geom_type == "Polygon"
                                                  else g.boundary)[1]
                keep += [p.buffer(r + COLUMN_WALL + 1.0, 32),
                         LineString([p, edge]).buffer(max(wall, 2 * COLUMN_WALL) / 2)]
        if keep:
            hole = hole.difference(unary_union(keep))
        # Forats massa petits no valen la pena.
        hole = unary_union([h for h in getattr(hole, "geoms", [hole])
                            if h.geom_type == "Polygon" and h.area > wall * wall])
        out.append(_reconnect(g, g.difference(hole), max(wall, 2 * COLUMN_WALL))
                   if not hole.is_empty else g)
    return out


def _reconnect(solid, hollowed, width: float):
    """Si buidar ha partit un tros en diversos, els torna a unir amb ponts de paret."""
    pieces = []
    for isl in _islands(solid):
        parts = [p for p in _islands(hollowed.intersection(isl))]
        for _ in range(len(parts) + 2):
            if len(parts) <= 1:
                break
            parts.sort(key=lambda p: p.area)
            small, rest = parts[0], unary_union(parts[1:])
            a, b = shapely.ops.nearest_points(small, rest)
            # El pont s'allarga una mica perquè trepitgi les dues parts i no quedi tocant.
            ab = np.array(b.coords[0]) - np.array(a.coords[0])
            n = np.linalg.norm(ab)
            ext = ab / n * width / 2 if n > 1e-9 else np.zeros(2)
            line = LineString([np.array(a.coords[0]) - ext, np.array(b.coords[0]) + ext])
            bridge = line.buffer(width / 2, cap_style=2).intersection(isl)
            joined = _islands(unary_union([small, rest, bridge]))
            if len(joined) >= len(parts):  # no s'ha pogut unir: es deixa com està
                break
            parts = joined
        pieces += parts
    return unary_union(pieces) if pieces else hollowed


SPINE_FIT = 0.1   # mm de joc a les osques de la costella


def spine(solid: list, geoms: list, t: float, wall: float):
    """Costella vertical que alinea totes les capes buidades a través d'osques a les parets.

    La costella passa per la cavitat seguint l'eix llarg de la cavitat més gran. A cada
    capa té una dent que entra a les osques de les dues parets, de manera que fixa la capa
    en totes direccions i en el gir. Es parteix en trams on l'amplada només creix o només
    decreix, perquè cada capa s'hi pugui enfilar des de l'extrem estret; dos trams
    consecutius comparteixen la capa més ampla (mitja alçada de dent cadascun).

    Retorna (peces de costella, osques per capa {k: [polígons]}, notes de muntatge).
    """
    K = len(solid)
    cav = [solid[k].difference(geoms[k]) for k in range(K)]
    big = max(range(K), key=lambda k: cav[k].area)
    if cav[big].is_empty:
        return [], {}, []
    rect = np.array(cav[big].minimum_rotated_rectangle.exterior.coords)
    sides = [rect[i + 1] - rect[i] for i in range(2)]
    axis = max(sides, key=np.linalg.norm)
    axis = axis / np.linalg.norm(axis)
    c = np.array(cav[big].centroid.coords[0])
    far = 10000.0
    start = c - axis * far
    line = LineString([start, c + axis * far])
    perp = np.array([-axis[1], axis[0]])
    d = max(wall / 2, 1.0)
    half = t / 2 + SPINE_FIT

    teeth: list[tuple[int, float, float]] = []
    notches: dict[int, list] = {}
    for k in range(K):
        inter = cav[k].intersection(line)
        for g in getattr(inter, "geoms", [inter]):
            if g.geom_type != "LineString" or g.length < 2 * t:
                continue
            s0, s1 = sorted(line.project(shapely.geometry.Point(q)) for q in g.coords[::len(g.coords) - 1])
            teeth.append((k, s0 - d, s1 + d))
            for a, b in ((s0 - d, s0 + 0.5), (s1 - 0.5, s1 + d)):
                pa, pb = start + axis * a, start + axis * b
                notches.setdefault(k, []).append(
                    Polygon([pa - perp * half, pb - perp * half, pb + perp * half, pa + perp * half]))
    if not teeth:
        return [], {}, []

    # Peces connexes de la costella (dents de capes consecutives que se solapen).
    teeth.sort()
    groups: list[list] = []
    for k, a, b in teeth:
        for grp in groups:
            pk, pa, pb = grp[-1]
            if pk == k - 1 and a < pb and b > pa:
                grp.append((k, a, b))
                break
        else:
            groups.append([(k, a, b)])

    parts, notes = [], []
    for gi, grp in enumerate(groups):
        widths = [b - a for _, a, b in grp]
        # Trams monòtons: es talla a cada canvi de tendència.
        cuts, trend = [0], 0
        for i in range(1, len(grp)):
            dw = widths[i] - widths[i - 1]
            sign = (dw > 1e-6) - (dw < -1e-6)
            if sign and trend and sign != trend:
                cuts.append(i - 1)  # la capa de gir es comparteix
            if sign:
                trend = sign
        cuts.append(len(grp) - 1)
        runs = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)] or [(0, 0)]
        for ri, (i0, i1) in enumerate(runs):
            rects = []
            for i in range(i0, i1 + 1):
                k, a, b = grp[i]
                lo, hi = k * t, (k + 1) * t
                if i == i0 and ri > 0:
                    lo += t / 2   # comparteix la capa de gir amb el tram de sota
                if i == i1 and ri < len(runs) - 1:
                    hi -= t / 2   # i amb el de sobre
                rects.append(shapely.geometry.box(a, lo, b, hi))
            shape = unary_union(rects)
            if shape.is_empty:
                continue
            name = f"R{gi + 1}" + (chr(ord("a") + ri) if len(runs) > 1 else "")
            part = Part(name, shape)
            for i in range(i0, i1 + 1):
                k, a, b = grp[i]
                part.labels.append((np.array([(a + b) / 2, (k + 0.5) * t]), f"L{k + 1}",
                                    float(min(2.0, 0.7 * t))))
            parts.append(part)
            ks = [grp[i][0] for i in range(i0, i1 + 1)]
            ws = widths[i0:i1 + 1]
            if ws[-1] >= ws[0]:
                order, end = f"L{ks[-1] + 1}…L{ks[0] + 1}", "per baix"
            else:
                order, end = f"L{ks[0] + 1}…L{ks[-1] + 1}", "per dalt"
            notes.append(f"  costella {name}: capes L{ks[0] + 1}–L{ks[-1] + 1}; enfila-hi les capes "
                         f"{end}, en aquest ordre: {order}")
    return parts, notches, notes


ALIGNS = ("columnes", "costella")


def make_layers(mesh: trimesh.Trimesh, target_faces: int, size_mm: float, thickness: float = 3.0,
                column_d: float = 5.0, sheet=(600.0, 400.0), wall: float = 0.0,
                align: str = "columnes") -> LaserResult:
    """Capes per apilar. Amb `wall` > 0 es buiden deixant una paret d'aquest gruix (mm).

    `align`: "columnes" (tiges passants) o "costella" (només capes buidades: una costella
    vertical dins la cavitat que encaixa en osques de les parets de cada capa).
    """
    m = pc.scale_to(pc.simplify(pc.clean(mesh), target_faces), size_mm)
    z0, z1 = m.bounds[0][2], m.bounds[1][2]
    K = max(1, int(math.ceil((z1 - z0) / thickness - 1e-9)))
    solid = [slice_at(m, z0 + (k + 0.5) * thickness + 1e-7) for k in range(K)]
    use_spine = align == "costella" and wall > 0
    # Les columnes es trien sobre les capes massisses i el buidat les respecta.
    columns = [] if use_spine else place_columns([_islands(g) for g in solid], column_d)
    geoms = hollow(solid, wall, thickness, columns, column_d) if wall > 0 else solid
    ribs, spine_notes, notches = [], [], {}
    if use_spine:
        ribs, notches, spine_notes = spine(solid, geoms, thickness, wall)
        geoms = [g.difference(unary_union(notches[k])) if k in notches else g
                 for k, g in enumerate(geoms)]
        # Els trossos que la costella no toca (tapes, braços massissos) van amb columnes.
        loose = [[g for g in _islands(geoms[k])
                  if k not in notches or not g.buffer(0.5).intersects(unary_union(notches[k]))]
                 for k in range(K)]
        columns = place_columns(loose, column_d)
    layers = [_islands(g) for g in geoms]
    r = column_d / 2 + COLUMN_FIT

    parts: list[Part] = []
    one = none = 0
    for k, lay in enumerate(layers):
        above = geoms[k + 1] if k + 1 < K else Polygon()
        below = geoms[k - 1] if k > 0 else Polygon()
        holes = [Point(x, y).buffer(r, 32) for x, y, a, b in columns if a <= k <= b]
        for j, g in enumerate(lay):
            name = f"L{k + 1}" + (chr(ord("a") + j) if len(lay) > 1 else "")
            mine = [h for h in holes if g.contains(h)]
            spined = k in notches and g.buffer(0.5).intersects(unary_union(notches[k]))
            if spined:
                pass  # l'alinea la costella
            elif not mine:
                none += 1
            elif len(mine) < COLUMNS_PER_PIECE:
                one += 1
            shape = g.difference(unary_union(mine)) if mine else g
            part = Part(name, shape)
            # Contorn continu: on va la capa de sobre. En ratlles: on és la de sota (útil
            # quan la de sobre és més gran i no deixa veure res).
            if not above.is_empty:
                part.engraves += _lines(above.boundary.intersection(g))
            if not below.is_empty:
                part.engraves += _dashed(_lines(below.boundary.intersection(g)))
            size = float(np.clip(math.sqrt(g.area) / 6, 2.0, 8.0))
            room = shape.buffer(-size)  # lluny de les vores i dels forats de les columnes
            spot = room.representative_point() if not room.is_empty else shape.representative_point()
            p = np.array(spot.coords[0])
            part.labels.append((p, name, size))
            part.engraves += _arrow(p + np.array([size * 1.8, 0.0]), size * 1.6)
            parts.append(part)

    parts += ribs
    title = f"Laminació · capes de {thickness:g} mm"
    svgs, groups, oversize = nest(parts, sheet, title)
    notes = [f"{K} capes de {thickness:g} mm ({len(parts)} peces). Munta de L1 (a baix) cap amunt,",
             *([f"Buidades amb parets de {wall:g} mm: el contorn gravat de la capa veïna inclou el seu forat."]
               if wall > 0 else []),
             "amb el número llegible a dalt i totes les fletxes cap al mateix costat.",
             "El contorn continu gravat a cada capa mostra on va la de sobre; el de ratlles, on és la de sota.",
             ]
    if use_spine:
        notes += ["Costelles (R): les dents entren a les osques de la paret de cada capa (el",
                  "número de capa és gravat a cada dent). Les peces que no toca cap costella",
                  "(tapes, trossos massissos) van amb columnes.", *spine_notes]
    if columns:
        notes.append(f"Tiges de Ø{column_d:g} mm (forats de Ø{2 * r:g} mm):")
        for i, (x, y, a, b) in enumerate(columns, 1):
            notes.append(f"  columna {i}: capes L{a + 1}–L{b + 1}, llargada "
                         f"{(b - a + 1) * thickness:g} mm")
    full = sum(g.area for g in solid)
    stats = dict(capes=K, peces=len(parts) - len(ribs), columnes=len(columns), costelles=len(ribs),
                 estalvi=round(100 * (1 - sum(g.area for g in geoms) / full)) if full else 0,
                 peces_amb_una_columna=one, peces_sense_columna=none, planxes=len(svgs),
                 massa_grans=oversize)
    return LaserResult(svgs, parts, stats, notes, groups)
