"""Segmentació guiada per un model de visió (VL): el VL diu *què* és cada part i *on* és; la
geometria diu on acaba (els plecs còncaus).

Flux (primera passada, volums generals):
1. `render_view`: vista ortogràfica de la malla amb ombrejat pla i, per a cada píxel, la cara
   que s'hi veu.
2. El VL rep cada imatge i la llista de parts («cap», «orella esquerra», «braç»...) i respon un
   punt per part visible: `{part: [x, y]}` en píxels. Aquest mòdul no crida cap model: rep els
   punts ja decidits (`seeds_from_points`), de manera que qualsevol VL els pot donar.
3. Cada punt és la cara que es veu en aquell píxel: una llavor de la part.
4. `segment_seeded`: cada cara va a la llavor que hi arriba amb menys cost; el cost d'una aresta
   és l'angle només si és còncava. Els plecs frenen i les parts convexes s'omplen.

La segona passada (detalls: ulls, nas, boca) repeteix el mateix en un retall de la zona.
"""
from __future__ import annotations

import math

import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

VIEWS = [(0, 10), (90, 10), (180, 10), (270, 10), (35, 30), (215, 30)]   # (azimut°, elevació°)


def camera(mesh: trimesh.Trimesh, az: float, el: float, size: int = 640):
    """Càmera ortogràfica cap al centre de la malla des de (azimut, elevació), amb Y amunt.
    Retorna (R, centre, escala): p_cam = R @ (p − centre); píxel = (size/2 + s·x, size/2 − s·y)."""
    a, e = math.radians(az), math.radians(el)
    f = -np.array([math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e)])
    r = np.cross(f, [0.0, 1.0, 0.0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    R = np.stack([r, u, -f])                     # files: x, y i z (cap a l'observador) de la càmera
    scale = 0.9 * size / float(np.linalg.norm(mesh.extents))
    return R, mesh.bounds.mean(0), scale


def render_view(mesh: trimesh.Trimesh, az: float, el: float, size: int = 640):
    """(imatge RGB uint8, ids de cara per píxel (−1 = cap), càmera)."""
    R, c, s = camera(mesh, az, el, size)
    P = (mesh.vertices - c) @ R.T
    px = np.stack([size / 2 + s * P[:, 0], size / 2 - s * P[:, 1]], 1)
    N = mesh.face_normals @ R.T
    light = np.array([0.35, 0.55, 0.75])
    shade = np.clip(N @ (light / np.linalg.norm(light)), 0, 1) * 0.75 + 0.2
    zb = np.full((size, size), -np.inf)
    ids = np.full((size, size), -1, np.int32)
    for fi in np.where(N[:, 2] > 0)[0]:
        a, b, d = mesh.faces[fi]
        (x0, y0), (x1, y1), (x2, y2) = px[a], px[b], px[d]
        xa, xb = max(int(math.floor(min(x0, x1, x2))), 0), min(int(math.ceil(max(x0, x1, x2))), size - 1)
        ya, yb = max(int(math.floor(min(y0, y1, y2))), 0), min(int(math.ceil(max(y0, y1, y2))), size - 1)
        if xb < xa or yb < ya:
            continue
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
        l0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / den
        l1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / den
        l2 = 1 - l0 - l1
        inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not inside.any():
            continue
        z = l0 * P[a, 2] + l1 * P[b, 2] + l2 * P[d, 2]
        sub_z = zb[ya:yb + 1, xa:xb + 1]
        win = inside & (z > sub_z)
        sub_z[win] = z[win]
        ids[ya:yb + 1, xa:xb + 1][win] = fi
    img = np.full((size, size, 3), 40, np.uint8)
    seen = ids >= 0
    img[seen] = (shade[ids[seen]][:, None] * 255).astype(np.uint8)
    return img, ids, (R, c, s)


def _faces_at(ids: np.ndarray, x: float, y: float, radius: int) -> list[int]:
    h, w = ids.shape
    x0, x1 = max(int(x) - radius, 0), min(int(x) + radius + 1, w)
    y0, y1 = max(int(y) - radius, 0), min(int(y) + radius + 1, h)
    f = ids[y0:y1, x0:x1].ravel()
    return sorted(set(int(i) for i in f[f >= 0]))


def seeds_from_points(mesh: trimesh.Trimesh, ids_by_view: list[np.ndarray],
                      points_by_view: list[dict[str, list]], radius: int = 4) -> dict[str, list[int]]:
    """Llavors (cares) de cada part a partir dels punts que el VL ha donat a cada vista.

    El VL només dona la *classe* (`{"orella": [[x, y], [x, y]], "cos": [[x, y]]}`): «l'orella de
    l'esquerra de la imatge» no és la mateixa en totes les vistes. Les instàncies les decideix
    la geometria: n'hi ha tantes com punts de la classe en la vista que en té més, i cada punt
    de les altres vistes va a la instància més propera en 3D.
    """
    C = mesh.triangles_center
    seeds: dict[str, list[int]] = {}
    classes = sorted({c for pts in points_by_view for c in pts})
    for cls in classes:
        per_view = []
        for ids, pts in zip(ids_by_view, points_by_view):
            raw = pts.get(cls, [])
            raw = [raw] if raw and not isinstance(raw[0], (list, tuple)) else raw
            per_view.append([f for f in (_faces_at(ids, x, y, radius) for x, y in raw) if f])
        k = max((len(v) for v in per_view), default=0)
        if k == 0:
            continue
        ref = per_view[int(np.argmax([len(v) for v in per_view]))]
        centers = [C[f].mean(0) for f in ref]
        groups: list[set[int]] = [set() for _ in range(k)]
        for v in per_view:
            for f in v:
                g = int(np.argmin([np.linalg.norm(C[f].mean(0) - c) for c in centers]))
                groups[g].update(f)
        for g, fs in enumerate(groups):
            seeds[cls if k == 1 else f"{cls}_{g}"] = sorted(fs)
    return seeds


def segment_seeded(mesh: trimesh.Trimesh, seeds: dict[str, list[int]]):
    """(etiqueta de cada cara, noms): cada cara va a la part de la llavor que hi arriba amb
    menys cost (angle només a les arestes còncaves + un terme petit de longitud)."""
    names = list(seeds)
    n = len(mesh.faces)
    adj = mesh.face_adjacency
    convex = mesh.face_adjacency_convex
    C = mesh.triangles_center
    d = np.linalg.norm(C[adj[:, 0]] - C[adj[:, 1]], axis=1)
    diag = float(np.linalg.norm(mesh.extents))
    w = np.where(convex, 0.0, mesh.face_adjacency_angles) + 0.02 * d / diag + 1e-9
    G = coo_matrix((np.r_[w, w], (np.r_[adj[:, 0], adj[:, 1]], np.r_[adj[:, 1], adj[:, 0]])),
                   shape=(n, n)).tocsr()
    src_face, src_label = [], []
    for k, nm in enumerate(names):
        for f in seeds[nm]:
            src_face.append(f)
            src_label.append(k)
    _, _, src = dijkstra(G, indices=src_face, min_only=True, return_predecessors=True)
    pos = {f: i for i, f in enumerate(src_face)}
    lab = np.array([src_label[pos[s]] if s in pos else -1 for s in src])
    if (lab < 0).any():                                    # peces no connexes: la cara etiquetada més propera
        ok = np.where(lab >= 0)[0]
        lab[lab < 0] = lab[ok[cKDTree(C[ok]).query(C[lab < 0])[1]]]
    return lab, names


def segment_from_points(mesh: trimesh.Trimesh, ids_by_view: list[np.ndarray],
                        points_by_view: list[list], radius: int = 4, **kw) -> np.ndarray:
    """Procediment genèric (sense noms de parts): cada punt que el VL dona a cada vista és una
    llavor. `segmenta.segment` fa créixer les regions pels plecs i ajunta les llavors que són
    de la mateixa part (vora plana o convexa entre elles). Dues llavors de la mateixa vista són
    parts diferents (el VL les ha dit per separat) i no es fusionen mai; les de vistes diferents
    sí, si no hi ha cap plec entremig."""
    import segmenta
    faces, groups = [], []
    for g, (ids, pts) in enumerate(zip(ids_by_view, points_by_view)):
        for x, y in pts:
            f = _faces_at(ids, x, y, radius)
            if f:
                faces.append(f[len(f) // 2])
                groups.append(g)
    if not faces:
        raise ValueError("El VL no ha donat cap punt vàlid.")
    return segmenta.clean_labels(mesh, segmenta.segment(mesh, seeds=faces, seed_groups=groups, **kw))


# ------------------------------------------------------------------ segona passada: detalls
def render_part(mesh: trimesh.Trimesh, mask: np.ndarray, az: float, el: float, size: int = 640):
    """Vista d'una sola part, encuadrada perquè l'ompli (els ids són cares de `mesh`)."""
    import reduccio_parts as rp
    keep = np.where(mask)[0]
    sub = trimesh.Trimesh(mesh.vertices, mesh.faces[keep], process=False)
    sub.remove_unreferenced_vertices()
    n_real = len(sub.faces)
    sub = rp.close_holes(sub)               # els forats d'unió es tanquen: no són detalls
    img, ids, cam = render_view(sub, az, el, size)
    real = (ids >= 0) & (ids < n_real)
    ids = np.where(real, keep[np.clip(ids, 0, n_real - 1)], -1)
    return img, ids.astype(np.int32), cam


def best_views(mesh: trimesh.Trimesh, mask: np.ndarray, count: int = 2):
    """Les `count` vistes de VIEWS des d'on es veu més àrea de la part (per ordre)."""
    N = mesh.face_normals[mask]
    A = mesh.area_faces[mask]
    score = []
    for az, el in VIEWS:
        a, e = math.radians(az), math.radians(el)
        d = np.array([math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e)])
        score.append(float((A * np.clip(N @ d, 0, None)).sum()))
    return [VIEWS[i] for i in np.argsort(score)[::-1][:count]]


def faces_in_box(ids: np.ndarray, box: list, norm: float = 1000.0) -> list[int]:
    """Cares visibles dins d'un quadre [x1, y1, x2, y2] normalitzat 0-`norm`."""
    h, w = ids.shape
    x1, y1, x2, y2 = (float(box[0]) / norm * w, float(box[1]) / norm * h,
                      float(box[2]) / norm * w, float(box[3]) / norm * h)
    sub = ids[max(int(y1), 0):min(int(y2) + 1, h), max(int(x1), 0):min(int(x2) + 1, w)].ravel()
    return sorted(set(int(i) for i in sub[sub >= 0]))


def merge_patches(mesh: trimesh.Trimesh, patches: list[dict], iou: float = 0.4):
    """Ajunta les zones de detall que són la mateixa: el mateix detall vist des de dues vistes
    (intersecció / unió de les cares ≥ `iou`). No s'encadena: la zona resultant mai creix més
    del doble de la més gran que hi entra."""
    patches = sorted(patches, key=lambda p: len(p["faces"]))
    out: list[dict] = []
    for p in patches:
        s = set(p["faces"])
        for q in out:
            u = len(s | q["faces_set"])
            if len(s & q["faces_set"]) >= iou * u and u <= 2 * max(len(s), q["biggest"]):
                q["faces_set"] |= s
                q["names"].append(p["name"])
                q["biggest"] = max(q["biggest"], len(s))
                q["vistes"] = q.get("vistes", 1) + 1
                break
        else:
            out.append(dict(names=[p["name"]], faces_set=set(s), biggest=len(s), vistes=1))
    for q in out:
        f = np.array(sorted(q["faces_set"]))
        a = mesh.area_faces[f]
        q["faces"] = f.tolist()
        q["centre"] = ((mesh.triangles_center[f] * a[:, None]).sum(0) / a.sum()).tolist()
        q["area"] = float(a.sum())
        q["normal"] = (mesh.face_normals[f] * a[:, None]).sum(0).tolist()
        del q["faces_set"], q["biggest"]
    return out


def border_faces(mesh: trimesh.Trimesh, lab: np.ndarray, k: int, rings: int = 1) -> np.ndarray:
    """Cares de la part `k` que toquen una altra part o la vora oberta de la malla (+ `rings` veïnes)."""
    adj = mesh.face_adjacency
    deg = np.bincount(adj.ravel(), minlength=len(mesh.faces))
    border = (deg < 3) & (lab == k)
    cross = lab[adj[:, 0]] != lab[adj[:, 1]]
    for a, b in adj[cross]:
        for f in (a, b):
            if lab[f] == k:
                border[f] = True
    for _ in range(rings):
        grow = border.copy()
        for a, b in adj:
            if border[a] and lab[b] == k:
                grow[b] = True
            if border[b] and lab[a] == k:
                grow[a] = True
        border = grow
    return border


def filter_patches(mesh: trimesh.Trimesh, lab: np.ndarray, patches: list[dict],
                   max_area: float = 0.25, max_border: float = 0.3) -> list[dict]:
    """Treu les zones que no són un detall: massa grans per a la seva part o enganxades a la seva
    vora (unió amb una altra part, forat obert)."""
    out = []
    borders = {}
    for p in patches:
        k = p["part"]
        f = np.array(p["faces"])
        part_area = mesh.area_faces[lab == k].sum()
        if mesh.area_faces[f].sum() > max_area * part_area:
            continue
        if k not in borders:
            borders[k] = border_faces(mesh, lab, k)
        if borders[k][f].mean() > max_border:
            continue
        out.append(p)
    return out


def faces_in_mask(ids: np.ndarray, mask: np.ndarray, cover: float = 0.5) -> list[int]:
    """Cares visibles que queden dins d'una màscara (SAM): les que tenen almenys `cover` dels seus
    píxels visibles dins la màscara."""
    seen = ids >= 0
    n_all = np.bincount(ids[seen], minlength=int(ids.max()) + 1)
    inside = ids[seen & mask]
    n_in = np.bincount(inside, minlength=len(n_all)) if len(inside) else np.zeros(len(n_all), int)
    return [int(i) for i in np.where((n_all > 0) & (n_in >= cover * n_all))[0]]
