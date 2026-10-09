"""Reducció per seccions: la forma base a partir dels eixos principals del model.

1. **Eixos**: el primer és la direcció de màxima llargada (amb la simetria al voltant de l'eix
   per desempatar); el segon, perpendicular, el de màxima llargada entre els perpendiculars;
   el tercer, perpendicular als dos.
2. **Seccions clau**: per cada eix, de 0 a 100 %, es fan moltes seccions de prova i se'n
   mesura la forma (àrea, perímetre, centre, amplades). Es trien les que cobreixen més: les
   que més s'allunyen del que donaria interpolar entre les ja triades (com Douglas–Peucker
   sobre el perfil). La quantitat la decideix la fidelitat.
3. **Punts clau**: a cada secció clau, els punts del contorn que en conserven més la forma
   (es treu sempre el punt que menys àrea aporta, fins que en queden els que diu la
   fidelitat, repartits entre els contorns segons el perímetre).
4. **Malla**: els punts clau dels tres eixos queden fixos com a vèrtexs i la resta de la
   malla es col·lapsa (reduccio.qem amb vèrtexs fixos), que garanteix una superfície tancada.
"""
from __future__ import annotations

import math

import numpy as np
import trimesh
from shapely.geometry import Polygon

import reduccio as rd


def _fibonacci(n: int) -> np.ndarray:
    """Direccions repartides per mitja esfera."""
    i = np.arange(n) + 0.5
    z = 1 - i / n          # només z ≥ 0: d i −d són el mateix eix
    r = np.sqrt(1 - z ** 2)
    phi = i * math.pi * (3 - math.sqrt(5))
    return np.column_stack([r * np.cos(phi), r * np.sin(phi), z])


def _symmetry_about(pts: np.ndarray, tree_pts: np.ndarray, c: np.ndarray, d: np.ndarray,
                    diag: float, planes: int = 6) -> float:
    """Error de simetria respecte d'un eix: el millor pla de mirall que el conté (0 = perfecte)."""
    u = np.cross(d, [1.0, 0, 0] if abs(d[0]) < 0.9 else [0, 1.0, 0])
    u /= np.linalg.norm(u)
    w = np.cross(d, u)
    best = math.inf
    for k in range(planes):
        a = math.pi * k / planes
        n = math.cos(a) * u + math.sin(a) * w
        mir = pts - 2 * ((pts - c) @ n)[:, None] * n
        best = min(best, float(np.percentile(rd._nearest(mir, tree_pts), 90)) / diag)
    return best


def principal_axes(mesh: trimesh.Trimesh, sym_weight: float = 2.0):
    """(centre, [eix1, eix2, eix3]). Puntuació d'un eix: llargada relativa − pes × error de
    simetria al voltant de l'eix (la simetria desempata entre llargades semblants)."""
    pts, _ = trimesh.sample.sample_surface(mesh, 1200, seed=11)
    ref, _ = trimesh.sample.sample_surface(mesh, 12000, seed=12)
    w = mesh.area_faces
    c = (mesh.triangles_center * w[:, None]).sum(0) / w.sum()
    diag = float(np.linalg.norm(mesh.extents))

    def score(d):
        h = pts @ d
        return float(np.ptp(h)) / diag - sym_weight * _symmetry_about(pts, ref, c, d, diag)

    evecs = np.linalg.eigh(np.cov((pts - c).T))[1].T
    cands = list(_fibonacci(120)) + list(evecs) + list(np.eye(3))
    # Primer per llargada (barat), i la simetria només entre les més llargues.
    ext = np.array([np.ptp(pts @ d) for d in cands])
    top = np.argsort(-ext)[:24]
    a1 = max((cands[i] for i in top), key=score)
    a1 = a1 / np.linalg.norm(a1)
    # Segon eix: perpendicular al primer.
    u = np.cross(a1, [1.0, 0, 0] if abs(a1[0]) < 0.9 else [0, 1.0, 0])
    u /= np.linalg.norm(u)
    v = np.cross(a1, u)
    perp = [math.cos(t) * u + math.sin(t) * v for t in np.linspace(0, math.pi, 36, endpoint=False)]
    ext2 = np.array([np.ptp(pts @ d) for d in perp])
    top2 = np.argsort(-ext2)[:8]
    a2 = max((perp[i] for i in top2), key=score)
    a3 = np.cross(a1, a2)
    return c, [a1, a2 / np.linalg.norm(a2), a3 / np.linalg.norm(a3)]


def _basis(n: np.ndarray):
    u = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0])
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def _section(mesh, origin, n, u, v):
    from laminacio import section_polygon
    segs = trimesh.intersections.mesh_plane(mesh, n, origin)
    if len(segs) == 0:
        return Polygon()
    to2 = lambda p: np.column_stack([(p - origin) @ u, (p - origin) @ v])
    return section_polygon([to2(s) for s in segs])


def _signature(poly, scale: float) -> np.ndarray:
    """Forma d'una secció en uns quants números (àrea, perímetre, centre, amplades)."""
    if poly.is_empty:
        return np.zeros(6)
    x0, y0, x1, y1 = poly.bounds
    c = poly.centroid
    return np.array([math.sqrt(poly.area) / scale, poly.length / (4 * scale), c.x / scale,
                     c.y / scale, (x1 - x0) / scale, (y1 - y0) / scale])


def key_sections(sigs: np.ndarray, count: int) -> list[int]:
    """Les `count` seccions que cobreixen més el perfil: es comença pels extrems i s'afegeix
    sempre la que més s'allunya de la interpolació entre les dues triades del voltant."""
    n = len(sigs)
    chosen = {0, n - 1}
    while len(chosen) < min(count, n):
        ks = sorted(chosen)
        best, best_err = None, -1.0
        for a, b in zip(ks, ks[1:]):
            for i in range(a + 1, b):
                t = (i - a) / (b - a)
                err = float(np.linalg.norm(sigs[i] - ((1 - t) * sigs[a] + t * sigs[b])))
                if err > best_err:
                    best, best_err = i, err
        if best is None:
            break
        chosen.add(best)
    return sorted(chosen)


def key_points(poly, count: int) -> list[np.ndarray]:
    """Els `count` punts del contorn que en conserven més la forma (Visvalingam: es treu
    sempre el punt que forma el triangle més petit amb els seus veïns), repartits entre els
    contorns (exteriors i forats) segons el perímetre, com a mínim 3 per contorn."""
    rings = []
    for g in getattr(poly, "geoms", [poly]):
        if g.geom_type != "Polygon" or g.is_empty:
            continue
        rings += [np.array(g.exterior.coords)[:-1]] + [np.array(r.coords)[:-1] for r in g.interiors]
    rings = [r for r in rings if len(r) >= 3]
    if not rings:
        return []
    per = np.array([np.linalg.norm(np.diff(np.vstack([r, r[:1]]), axis=0), axis=1).sum() for r in rings])
    alloc = np.maximum(3, np.round(count * per / per.sum()).astype(int))
    out = []
    for r, k in zip(rings, alloc):
        pts = list(r)
        while len(pts) > k:
            m = len(pts)
            areas = [abs(np.cross(pts[i] - pts[i - 1], pts[(i + 1) % m] - pts[i - 1])) for i in range(m)]
            pts.pop(int(np.argmin(areas)))
        out += pts
    return out


def fidelity_plan(fidelity: float) -> tuple[int, int]:
    """(seccions clau per eix, punts per secció) per a una fidelitat de 0 a 100."""
    f = float(np.clip(fidelity, 0, 100)) / 100
    return int(round(3 + 9 * f)), int(round(5 + 15 * f))


def keypoints(mesh: trimesh.Trimesh, fidelity: float, samples: int = 48):
    """Punts clau (3D) de les seccions clau dels tres eixos principals, i la informació."""
    c, axes = principal_axes(mesh)
    n_sec, n_pts = fidelity_plan(fidelity)
    diag = float(np.linalg.norm(mesh.extents))
    out, info = [], {"eixos": [a.round(3).tolist() for a in axes], "seccions": []}
    for k, n in enumerate(axes):
        u, v = _basis(n)
        h = mesh.vertices @ n
        lo, hi = float(h.min()), float(h.max())
        span = hi - lo
        ts = lo + span * (np.arange(samples) + 0.5) / samples
        polys = [_section(mesh, n * t, n, u, v) for t in ts]
        sigs = np.array([_signature(p, diag) for p in polys])
        sel = key_sections(sigs, n_sec)
        info["seccions"].append([round(float((ts[i] - lo) / span) * 100, 1) for i in sel])
        for i in sel:
            for p in key_points(polys[i], n_pts):
                out.append(n * ts[i] + u * p[0] + v * p[1])
    return np.array(out), info


def reduce(mesh: trimesh.Trimesh, fidelity: float = 50.0, merge: float = 0.35):
    """Malla reduïda per seccions: els punts clau queden fixos i la resta es col·lapsa.

    `merge`: els punts clau més a prop que aquesta fracció de la separació típica es fusionen
    (les seccions de dos eixos es creuen i hi deixen punts gairebé iguals).
    """
    import papercraft as pc
    base = pc.clean(mesh)
    kp, info = keypoints(base, fidelity)
    pre = pc.simplify(base, max(rd.PRE_MIN, 12 * len(kp))) if len(base.faces) > max(rd.PRE_MIN, 12 * len(kp)) \
        else base
    if len(kp) == 0:
        return pre, info
    # Cada punt clau es fixa al vèrtex més proper de la malla.
    idx = np.unique(rd._nearest_index(kp, pre.vertices))
    spacing = math.sqrt(pre.area / max(len(idx), 1))
    keep = []
    for i in idx:  # fusiona els massa propers
        if all(np.linalg.norm(pre.vertices[i] - pre.vertices[j]) > merge * spacing for j in keep):
            keep.append(i)
    lock = np.zeros(len(pre.vertices), bool)
    lock[keep] = True
    out = rd.qem(pre.vertices, pre.faces, 4, np.ones(len(pre.vertices)), locked=lock)
    info["punts_clau"] = len(keep)
    return pc.clean(out), info
