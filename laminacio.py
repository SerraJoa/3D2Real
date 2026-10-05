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


def make_layers(mesh: trimesh.Trimesh, target_faces: int, size_mm: float, thickness: float = 3.0,
                column_d: float = 5.0, sheet=(600.0, 400.0)) -> LaserResult:
    m = pc.scale_to(pc.simplify(pc.clean(mesh), target_faces), size_mm)
    z0, z1 = m.bounds[0][2], m.bounds[1][2]
    K = max(1, int(math.ceil((z1 - z0) / thickness - 1e-9)))
    geoms = [slice_at(m, z0 + (k + 0.5) * thickness + 1e-7) for k in range(K)]
    layers = [_islands(g) for g in geoms]
    columns = place_columns(layers, column_d)
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
            if not mine:
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

    title = f"Laminació · capes de {thickness:g} mm"
    svgs, groups, oversize = nest(parts, sheet, title)
    notes = [f"{K} capes de {thickness:g} mm ({len(parts)} peces). Munta de L1 (a baix) cap amunt,",
             "amb el número llegible a dalt i totes les fletxes cap al mateix costat.",
             "El contorn continu gravat a cada capa mostra on va la de sobre; el de ratlles, on és la de sota.",
             f"Tiges de Ø{column_d:g} mm (forats de Ø{2 * r:g} mm):"]
    for i, (x, y, a, b) in enumerate(columns, 1):
        notes.append(f"  columna {i}: capes L{a + 1}–L{b + 1}, llargada {(b - a + 1) * thickness:g} mm")
    stats = dict(capes=K, peces=len(parts), columnes=len(columns),
                 peces_amb_una_columna=one, peces_sense_columna=none, planxes=len(svgs),
                 massa_grans=oversize)
    return LaserResult(svgs, parts, stats, notes, groups)
