"""Reducció per parts: segmentació, un eix per part, seccions cada 1 %, anells eficients.

1. **Parts** (`segmenta.segment`): cada part s'aïlla i es tracta sola.
2. **Eix de la part**: el més llarg i simètric de la mateixa part (`seccions.principal_axes`),
   no un eix global del model.
3. **Mesura**: seccions de tall a cada 1 % de l'eix (100 seccions).
4. **Anell**: tots els anells d'una part tenen els mateixos N vèrtexs, als mateixos angles
   (així els vèrtexs es corresponen d'una secció a l'altra). Els angles es trien posant-los
   on el contorn s'allunya més de la corda, fins que l'error és sota la tolerància.
5. **Seccions clau**: de les 100 se'n deixen les que calen perquè interpolar entre elles
   no s'allunyi més de la tolerància de les mesurades.
6. **Pressupost**: les cares objectiu surten de la mida final i de la mida ideal de cara;
   la tolerància es busca per a cada part perquè hi càpiga. Les zones fines amb detall hi
   gasten més seccions perquè l'error de tolerància hi és més alt.
7. **Unió**: les parts, com a volums tancats, s'ajunten en una sola malla.
"""
from __future__ import annotations

import math

import numpy as np
import trimesh

import seccions as sc
import segmenta

NS = 100      # seccions de mesura: una a cada 1 % de l'eix
NTH = 360     # mostres angulars de la funció radial d'una secció


def _radial(poly, center: np.ndarray) -> np.ndarray | None:
    """Distància del centre al contorn exterior en NTH direccions (la intersecció més llunyana)."""
    if poly.is_empty:
        return None
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    Q = np.array(poly.exterior.coords)
    a, b = Q[:-1] - center, Q[1:] - center
    th = np.linspace(0, 2 * math.pi, NTH, endpoint=False)
    e = np.stack([np.cos(th), np.sin(th)], 1)                       # (T, 2)
    d = b - a                                                       # (E, 2)
    den = e[:, None, 0] * d[None, :, 1] - e[:, None, 1] * d[None, :, 0]   # (T, E)
    ok = np.abs(den) > 1e-12
    den_safe = np.where(ok, den, 1.0)
    r = (a[None, :, 0] * d[None, :, 1] - a[None, :, 1] * d[None, :, 0]) / den_safe
    s = (a[None, :, 0] * e[:, None, 1] - a[None, :, 1] * e[:, None, 0]) / den_safe
    hit = ok & (r > 0) & (s >= -1e-9) & (s <= 1 + 1e-9)
    out = np.where(hit, r, -1.0).max(1)
    if (out <= 0).mean() > 0.05:
        return None
    bad = out <= 0
    if bad.any():                                                   # forats petits: interpola
        idx = np.arange(NTH)
        out[bad] = np.interp(idx[bad], idx[~bad], out[~bad], period=NTH)
    return out


def close_holes(m: trimesh.Trimesh) -> trimesh.Trimesh:
    """Tanca els forats de la part (on s'unia a una altra) amb un ventall des del centre."""
    F = m.faces
    de = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    have = {(int(a), int(b)) for a, b in de}
    nxt: dict[int, int] = {}
    for a, b in de:
        if (int(b), int(a)) not in have:
            nxt[int(a)] = int(b)
    V = [m.vertices]
    newF = []
    seen: set[int] = set()
    for s in list(nxt):
        if s in seen:
            continue
        loop, a = [], s
        while a in nxt and a not in seen:
            seen.add(a)
            loop.append(a)
            a = nxt[a]
        if len(loop) < 3:
            continue
        c = len(m.vertices) + len(V) - 1
        V.append(m.vertices[loop].mean(0)[None])
        for i, a in enumerate(loop):
            b = loop[(i + 1) % len(loop)]
            newF.append([b, a, c])
    out = trimesh.Trimesh(np.vstack(V), np.vstack([F, np.array(newF)]) if newF else F, process=False)
    return out


def choose_axis(part: trimesh.Trimesh):
    """L'eix més llarg i simètric entre els de la caixa orientada de la part (o els del món si
    la caixa orientada no hi guanya: una part en bloc no gira per no res)."""
    from trimesh.bounds import oriented_bounds
    V = part.vertices
    T, _ = oriented_bounds(V)
    axes = np.vstack([np.eye(3), T[:3, :3]])               # eixos del món i de la caixa orientada
    pts, _ = trimesh.sample.sample_surface(part, 1200, seed=11)
    ref, _ = trimesh.sample.sample_surface(part, 6000, seed=12)
    c = pts.mean(0)
    diag = float(np.linalg.norm(part.extents))
    sc_ = [float(np.ptp(pts @ a)) / diag - 2.0 * sc._symmetry_about(pts, ref, c, a, diag)
           - (0.0 if i < 3 else 0.06) for i, a in enumerate(axes)]   # el món té preferència
    k = int(np.argmax(sc_))
    return axes[k] / np.linalg.norm(axes[k]), axes[3:] if k >= 3 else axes[:3]


def is_plate(part: trimesh.Trimesh, axes: np.ndarray, ratio: float = 0.12) -> int | None:
    """Índex de l'eix prim si la part és una làmina (gruix < ratio × la mida més gran)."""
    e = np.array([float(np.ptp(part.vertices @ a)) for a in axes])
    return int(np.argmin(e)) if e.min() < ratio * e.max() else None


def plate(part: trimesh.Trimesh, normal: np.ndarray, budget: int):
    """Làmina: el contorn de la silueta, simplificat, extrusionat pel gruix."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    u, v = sc._basis(normal)
    V = part.vertices
    P = np.stack([V @ u, V @ v], 1)
    sil = unary_union([Polygon(P[f]).buffer(0) for f in part.faces if Polygon(P[f]).area > 1e-12])
    size = max(sil.bounds[2] - sil.bounds[0], sil.bounds[3] - sil.bounds[1])
    sil = sil.buffer(0.02 * size).buffer(-0.02 * size)
    if sil.geom_type != "Polygon":
        sil = max(sil.geoms, key=lambda g: g.area)
    sil = Polygon(sil.exterior)
    kmax = max(3, (budget + 4) // 4)
    tol = 0.001 * size
    while True:
        s = sil.simplify(tol, preserve_topology=True)
        if len(s.exterior.coords) - 1 <= kmax:
            break
        tol *= 1.15
    ring = np.array(s.exterior.coords)[:-1]
    if not Polygon(ring).exterior.is_ccw:
        ring = ring[::-1]
    h = V @ normal
    z0, z1 = np.percentile(h, [1, 99])
    k = len(ring)
    from shapely.ops import triangulate
    poly = Polygon(ring)
    tris = [t for t in triangulate(poly) if poly.buffer(1e-9).contains(t.centroid)]
    idx = {tuple(np.round(p, 9)): i for i, p in enumerate(ring)}
    verts = np.vstack([np.c_[ring, np.full(k, z1)], np.c_[ring, np.full(k, z0)]])
    W = verts[:, 0:1] * u + verts[:, 1:2] * v + verts[:, 2:3] * normal
    F = []
    for t in tris:
        a = [idx[tuple(np.round(c, 9))] for c in list(t.exterior.coords)[:3]]
        F += [a, [i + k for i in a[::-1]]]
    for i in range(k):
        j = (i + 1) % k
        F += [[i, i + k, j + k], [i, j + k, j]]
    m = trimesh.Trimesh(W, np.array(F), process=True)
    if m.volume < 0:
        m.invert()
    return m, dict(tipus="placa", punts=k)


def section_closed(part: trimesh.Trimesh, n, t, u, v):
    """Polígon de la secció a l'alçada t. Si el contorn és obert (la part no té superfície on
    s'unia a una altra), es tanca amb una corda: com un tall pla a la unió."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import linemerge, polygonize, unary_union
    segs = trimesh.intersections.mesh_plane(part, n, n * t)
    if len(segs) == 0:
        return Polygon()
    o = n * t
    lines = [LineString(np.round(np.column_stack([(s - o) @ u, (s - o) @ v]), 6))
             for s in segs if np.linalg.norm(s[0] - s[1]) > 1e-9]
    if not lines:
        return Polygon()
    union = unary_union(lines)
    faces = list(polygonize(union))
    geom = Polygon()
    for f in faces:
        geom = geom.symmetric_difference(Polygon(f.exterior))
    if geom.is_empty or geom.area <= 1e-9:                   # contorn obert: tanca cada cadena
        merged = union if union.geom_type == "LineString" else linemerge(union)
        chains = list(getattr(merged, "geoms", [merged]))
        polys = [Polygon(c.coords) for c in chains if len(c.coords) >= 3]
        polys = [q.buffer(0) for q in polys if q.area > 1e-9]
        geom = max(polys, key=lambda q: q.area) if polys else Polygon()
    return geom.buffer(0)


def measure(part: trimesh.Trimesh, ns: int = NS, convex: bool = False):
    """(n, u, v, ts, centres, R): eix, base, posicions i funcions radials de cada secció."""
    n, _ = choose_axis(part)
    u, v = sc._basis(n)
    h = part.vertices @ n
    lo, hi = float(h.min()), float(h.max())
    ts = lo + (hi - lo) * (np.arange(ns) + 0.5) / ns
    keep_t, cen, R = [], [], []
    for t in ts:
        poly = section_closed(part, n, t, u, v)
        if convex and not poly.is_empty:
            poly = poly.convex_hull        # volum inflat: les entrades i els forats s'uneixen amb rectes
        if poly.is_empty or poly.area <= 1e-9:
            continue
        c = np.array(poly.centroid.coords[0])
        if not poly.contains(poly.centroid):
            c = np.array(poly.representative_point().coords[0])
        r = _radial(poly, c)
        if r is None:
            continue
        keep_t.append(t)
        cen.append(c)
        R.append(r)
    return n, u, v, np.array(keep_t), np.array(cen), np.array(R)


def _chord_dev(R: np.ndarray, i0: int, i1: int) -> np.ndarray:
    """(S, k) desviació radial entre el contorn i la corda de l'angle i0 a l'i1 (cíclic)."""
    k = (i1 - i0) % NTH
    k = k if k else NTH
    ang = 2 * math.pi / NTH
    idx = (i0 + np.arange(1, k)) % NTH
    r0, r1 = R[:, i0][:, None], R[:, i1 % NTH][:, None]
    dth = k * ang
    s = np.arange(1, k)[None, :] * ang
    den = r0 * np.sin(dth - s) + r1 * np.sin(s)
    rc = r0 * r1 * math.sin(dth) / np.maximum(den, 1e-12)
    return np.abs(R[:, idx] - rc), idx


def choose_angles(R: np.ndarray, tol: float, n_min: int = 4, n_max: int = 24) -> list[int]:
    """Índexs d'angle dels vèrtexs de l'anell: s'afegeix sempre on el contorn més s'allunya
    de la corda (com Douglas-Peucker en polars), fins que cap secció s'allunya més de `tol`."""
    ang = [int(NTH * q / 4) for q in range(4)]
    while True:
        best = (0.0, None)
        devs = []
        for a, b in zip(ang, ang[1:] + [ang[0] + NTH]):
            if (b - a) < 2:
                continue
            dev, idx = _chord_dev(R, a % NTH, b % NTH)
            devs.append(dev.ravel())
            tot = dev.sum(0)
            j = int(np.argmax(tot))
            if tot[j] > best[0]:
                best = (float(tot[j]), int(idx[j]))
        worst = float(np.percentile(np.concatenate(devs), 90)) if devs else 0.0   # robust: sense soroll
        if best[1] is None or (worst <= tol and len(ang) >= n_min) or len(ang) >= n_max:
            return sorted(set(a % NTH for a in ang))
        ang = sorted(set(a % NTH for a in ang) | {best[1]})


def choose_stations(ring: np.ndarray, ts: np.ndarray, tol: float, m_min: int = 2,
                    m_max: int = 40) -> list[int]:
    """Seccions clau: s'afegeix la que més s'allunya de la interpolació de les veïnes."""
    chosen = [0, len(ts) - 1]
    while len(chosen) < m_max:
        best, err = None, -1.0
        for a, b in zip(chosen, chosen[1:]):
            for i in range(a + 1, b):
                t = (ts[i] - ts[a]) / (ts[b] - ts[a])
                e = float(np.sqrt((np.linalg.norm(ring[i] - ((1 - t) * ring[a] + t * ring[b]), axis=1) ** 2).mean()))
                if e > err:
                    best, err = i, e
        if best is None or (err <= tol and len(chosen) >= m_min):
            break
        chosen = sorted(chosen + [best])
    return chosen


def loft(part: trimesh.Trimesh, meas, tol: float, n_max: int = 24, m_max: int = 40):
    """Volum tancat de la part: anells de N vèrtexs a M seccions, més dues tapes."""
    n, u, v, ts, cen, R = meas
    ang = choose_angles(R, tol, n_max=n_max)
    th = np.array(ang) * 2 * math.pi / NTH
    e = np.stack([np.cos(th), np.sin(th)], 1)
    p2 = cen[:, None, :] + R[:, ang][:, :, None] * e[None]            # (S, N, 2)
    ring = ts[:, None, None] * n + p2[..., :1] * u + p2[..., 1:] * v  # (S, N, 3)
    st = choose_stations(ring, ts, tol, m_max=m_max)
    Rg = ring[st]
    M, N = Rg.shape[:2]
    V = [Rg.reshape(-1, 3)]
    F = []
    for i in range(M - 1):
        for k in range(N):
            j = (k + 1) % N
            a, b, c, d = i * N + k, i * N + j, (i + 1) * N + j, (i + 1) * N + k
            F += [[a, b, c], [a, c, d]]
    for i, flip in ((0, True), (M - 1, False)):                        # tapes en ventall
        ctr = sum(len(x) for x in V)
        V.append(Rg[i].mean(0)[None])
        for k in range(N):
            j = (k + 1) % N
            F.append([ctr, i * N + j, i * N + k] if flip else [ctr, i * N + k, i * N + j])
    m = trimesh.Trimesh(np.vstack(V), np.array(F), process=False)
    if m.volume < 0:
        m.invert()
    return m, dict(anells=M, vertexs_anell=N, tol=tol)


def fit_budget(part: trimesh.Trimesh, meas, budget: int, tol_lo: float = 0.05,
               tol_hi: float = 20.0, n_max: int = 24):
    """La tolerància més petita (la forma més fidel) que cap dins del pressupost de triangles."""
    best = None
    lo, hi = math.log(tol_lo), math.log(tol_hi)
    for _ in range(14):
        mid = (lo + hi) / 2
        m, info = loft(part, meas, math.exp(mid), n_max=n_max)
        if len(m.faces) <= budget:
            best, hi = (m, info), mid
        else:
            lo = mid
    if best is None:
        best = loft(part, meas, math.exp(hi), n_max=n_max)
    return best


def reduce_parts(mesh: trimesh.Trimesh, target: int, parts: np.ndarray | None = None):
    """Malla reduïda a uns `target` triangles: una per part, repartits per àrea.

    `mesh` ja ha d'estar a la mida final (mm). Retorna (peces, info): les peces són volums
    tancats, una per part, sense unir encara.
    """
    lab = segmenta.segment(mesh) if parts is None else parts
    area = np.bincount(lab, weights=mesh.area_faces)
    out, info = [], []
    for k in range(lab.max() + 1):
        sub = trimesh.Trimesh(mesh.vertices, mesh.faces[lab == k], process=False)
        sub.remove_unreferenced_vertices()
        sub = close_holes(sub)
        budget = max(24, int(round(target * area[k] / area.sum())))
        _, axes = choose_axis(sub)
        thin = is_plate(sub, axes)
        if thin is not None:
            m, i = plate(sub, axes[thin] / np.linalg.norm(axes[thin]), budget)
        else:
            m, i = fit_budget(sub, measure(sub), budget)
        out.append(m)
        info.append(dict(part=k, **i, triangles=len(m.faces), pressupost=budget,
                         area=float(area[k] / area.sum())))
    return out, info
