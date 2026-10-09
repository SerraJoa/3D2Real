"""Reducció de malla que respecta la forma.

La simplificació per error quadràtic (QEM) treu primer el que menys canvia la forma global:
els detalls petits (ulls, boca, nas) hi compten poc i desapareixen abans, i com que les
arestes es treuen d'una en una, les dues meitats d'una figura simètrica acaben diferents.
Aquí es fa el mateix QEM amb dues coses més:

- **Detalls**: cada vèrtex té un pes d'importància (curvatura: vores, plecs i forats com els
  ulls; i, si hi ha textura, el contrast del dibuix, com uns ulls o una boca pintats). El cost
  de moure'l es multiplica pel pes: les zones importants es conserven.
- **Per rondes**: a cada ronda es fan alhora els col·lapses més barats que no es toquen entre
  ells. Dues zones equivalents (un ull i l'altre) es tracten igual a la mateixa ronda, en
  lloc que l'ordre d'una cua decideixi quina perd abans.
- **Simetria** (opcional, desactivada per defecte): si el model ja és simètric, se'n
  simplifica una meitat i s'hi fa el mirall. No s'inventa: si no ho és, no s'aplica.

Per anar de pressa, primer es fa una reducció ràpida (fast-simplification) fins a unes
`PRE_FACTOR` vegades l'objectiu, que encara conserva els detalls, i després la fina.
"""
from __future__ import annotations

import math

import numpy as np
import trimesh

PRE_FACTOR = 12        # la reducció ràpida para a tantes vegades l'objectiu
PRE_MIN = 3000         # ... i mai per sota d'aquestes cares
SHAPE_TOL = 0.02      # si la versió simètrica s'allunya més que això de la forma, es prova sense
SYM_PCT = 97          # percentil de la distància al mirall: els detalls petits també compten
SYM_TOL = 0.012        # simetria acceptada: distància típica (percentil 80) / diagonal
ROUND_SHARE = 6       # a cada ronda es col·lapsa com a molt 1/6 de les arestes
BOUNDARY_WEIGHT = 50.0  # les vores obertes (i el tall de simetria) gairebé no es mouen
AXES = {"x": np.array([1.0, 0, 0]), "y": np.array([0, 1.0, 0]), "z": np.array([0, 0, 1.0])}


# ---------------------------------------------------------------- simetria

try:
    from scipy.spatial import cKDTree
except ImportError:  # sense scipy va igual, però més lent
    cKDTree = None


def _nearest(a: np.ndarray, b: np.ndarray, chunk: int = 2048) -> np.ndarray:
    """Distància de cada punt de `a` al punt més proper de `b`."""
    if cKDTree is not None:
        return cKDTree(b).query(a)[0]
    out = np.empty(len(a))
    b2 = (b ** 2).sum(1)
    for i in range(0, len(a), chunk):
        x = a[i:i + chunk]
        d2 = (x ** 2).sum(1)[:, None] + b2[None, :] - 2 * x @ b.T
        out[i:i + chunk] = np.sqrt(np.maximum(d2.min(1), 0))
    return out


def find_symmetry(mesh: trimesh.Trimesh, axis: str = "auto", samples: int = 1500,
                  dense: int = 40000):
    """Pla de simetria (punt, normal, error relatiu) o None si el model no és simètric.

    Es proven els plans pel centre de la superfície perpendiculars als eixos x, y, z i als
    eixos principals; l'error és el percentil SYM_PCT de la distància entre la superfície i la
    seva imatge al mirall, respecte de la diagonal del model. `axis` força un eix ("x", "y",
    "z") o "auto".
    """
    # Una mostra petita al mirall contra una de molt densa: la distància és gairebé la de la
    # superfície, no el soroll de dues mostres a l'atzar.
    pts, _ = trimesh.sample.sample_surface(mesh, samples, seed=1)
    ref, _ = trimesh.sample.sample_surface(mesh, dense, seed=2)
    w = mesh.area_faces
    c = (mesh.triangles_center * w[:, None]).sum(0) / w.sum()
    diag = float(np.linalg.norm(mesh.extents))
    if axis in AXES:
        cands = [AXES[axis]]
    else:
        evecs = np.linalg.eigh(np.cov((pts - c).T))[1].T
        cands = list(AXES.values()) + [v / np.linalg.norm(v) for v in evecs]
    best = None
    for n in cands:
        # El pla pot no passar pel centre de la superfície (si el model no és simètric en
        # densitat): es prova el centre i el punt mig de l'extensió en aquesta direcció.
        h = pts @ n
        for c0 in (c, c + n * ((h.min() + h.max()) / 2 - c @ n)):
            mir = pts - 2 * ((pts - c0) @ n)[:, None] * n
            err = float(np.percentile(_nearest(mir, ref), SYM_PCT)) / diag
            if best is None or err < best[2]:
                best = (c0, n, err)
    if best is None or (axis == "auto" and best[2] > SYM_TOL):
        return None
    return best


def split_half(mesh: trimesh.Trimesh, c: np.ndarray, n: np.ndarray):
    """La meitat de la malla al costat positiu del pla; els triangles tallats es retallen i
    els vèrtexs del tall queden exactament sobre el pla. Retorna (vèrtexs, cares)."""
    V = mesh.vertices
    d = (V - c) @ n
    eps = 1e-7 * float(np.linalg.norm(mesh.extents))
    d = np.where(np.abs(d) < eps, 0.0, d)
    V = V - np.where(d == 0, (V - c) @ n, 0)[:, None] * n  # els del pla, exactament al pla
    verts = list(V)
    cut: dict[tuple[int, int], int] = {}

    def on_edge(i: int, j: int) -> int:
        key = (min(i, j), max(i, j))
        if key not in cut:
            t = d[i] / (d[i] - d[j])
            p = V[i] + t * (V[j] - V[i])
            p = p - ((p - c) @ n) * n
            cut[key] = len(verts)
            verts.append(p)
        return cut[key]

    faces = []
    for f in mesh.faces:
        s = d[f]
        if (s >= 0).all():
            faces.append(list(f))
            continue
        if (s <= 0).all():
            continue
        poly = []  # Sutherland–Hodgman contra el semiespai d ≥ 0
        for k in range(3):
            i, j = int(f[k]), int(f[(k + 1) % 3])
            if d[i] >= 0:
                poly.append(i)
            if (d[i] > 0 and d[j] < 0) or (d[i] < 0 and d[j] > 0):
                poly.append(on_edge(i, j))
        for k in range(1, len(poly) - 1):
            faces.append([poly[0], poly[k], poly[k + 1]])
    return np.array(verts), np.array(faces, dtype=np.int64)


# ---------------------------------------------------------------- importància

def _relief(mesh: trimesh.Trimesh, radius: float) -> np.ndarray:
    """Relleu a l'escala `radius` (0–1): quant es desvia la normal de cada vèrtex de la mitjana
    del seu voltant, respecte de la desviació típica del model. Una esfera llisa dona 0 a tot
    arreu; unes conques d'ulls, una boca o un nas, a prop d'1."""
    V = mesh.vertices
    N = np.zeros_like(V)  # normals per vèrtex ponderades per àrea (sense scipy)
    fn = mesh.face_normals * mesh.area_faces[:, None]
    for k in range(3):
        np.add.at(N, mesh.faces[:, k], fn)
    N /= np.maximum(np.linalg.norm(N, axis=1), 1e-12)[:, None]
    if cKDTree is not None:
        pairs = cKDTree(V).query_pairs(radius, output_type="ndarray")
        m = N.copy()
        np.add.at(m, pairs[:, 0], N[pairs[:, 1]])
        np.add.at(m, pairs[:, 1], N[pairs[:, 0]])
        m /= np.maximum(np.linalg.norm(m, axis=1), 1e-12)[:, None]
        dev = np.arccos(np.clip((m * N).sum(1), -1, 1))
    else:
        dev = np.empty(len(V))
        v2 = (V ** 2).sum(1)
        for i in range(0, len(V), 1024):
            a = V[i:i + 1024]
            near = ((a ** 2).sum(1)[:, None] + v2[None] - 2 * a @ V.T) < radius ** 2
            m = near.astype(float) @ N
            m /= np.maximum(np.linalg.norm(m, axis=1), 1e-12)[:, None]
            dev[i:i + 1024] = np.arccos(np.clip((m * N[i:i + 1024]).sum(1), -1, 1))
    base, top = np.median(dev), np.percentile(dev, 97)
    return np.clip((dev - base) / max(top - base, math.radians(5)), 0, 1)


def importance(mesh: trimesh.Trimesh, texture=None, texture_mesh: trimesh.Trimesh | None = None,
               target: int | None = None) -> np.ndarray:
    """Pes de 0 a ~2 per vèrtex: forma (arestes vives, punxes i relleu a l'escala dels
    triangles que quedaran: conques, plecs) i contrast de la textura (si n'hi ha:
    `texture_mesh` és la malla on són les UV de `texture`)."""
    nv = len(mesh.vertices)
    feat = np.zeros(nv)
    if target:
        edge = math.sqrt(4 * mesh.area / (math.sqrt(3) * target))  # aresta dels triangles finals
        feat = _relief(mesh, 0.6 * edge)
    if len(mesh.face_adjacency):
        ang = np.clip(mesh.face_adjacency_angles / (math.pi / 3), 0, 1)
        e = mesh.face_adjacency_edges
        np.maximum.at(feat, e[:, 0], ang)
        np.maximum.at(feat, e[:, 1], ang)
    # Punxes i clots: defecte angular (2π − suma d'angles), normalitzat.
    defect = np.full(nv, 2 * math.pi)
    np.subtract.at(defect, mesh.faces.ravel(), mesh.face_angles.ravel())
    boundary = np.zeros(nv, bool)
    lone = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
    boundary[mesh.edges_sorted[lone].ravel()] = True
    defect[boundary] = 0  # a les vores obertes no vol dir res
    feat = np.maximum(feat, np.clip(np.abs(defect) / (math.pi / 4), 0, 1))
    if texture is not None and texture_mesh is not None:
        feat = feat + _texture_contrast(texture, texture_mesh, mesh)
    return feat


def _texture_contrast(texture, src: trimesh.Trimesh, dst: trimesh.Trimesh) -> np.ndarray:
    """Contrast del dibuix de la textura a prop de cada vèrtex de `dst` (0–1)."""
    img = np.asarray(texture.image.convert("L"), dtype=float) / 255.0
    h, w = img.shape
    uv = texture.face_uv  # (F, 3, 2)
    bary = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1 / 3, 1 / 3, 1 / 3],
                     [0.5, 0.5, 0], [0, 0.5, 0.5], [0.5, 0, 0.5]])
    p = np.einsum("kj,fjd->fkd", bary, uv) % 1.0
    x = np.clip((p[..., 0] * (w - 1)).round().astype(int), 0, w - 1)
    y = np.clip(((1 - p[..., 1]) * (h - 1)).round().astype(int), 0, h - 1)
    lum = img[y, x]                                  # (F, 7)
    contrast = np.clip((lum.max(1) - lum.min(1)) * 2.5, 0, 1)
    per_v = np.zeros(len(src.vertices))
    for k in range(3):
        np.maximum.at(per_v, src.faces[:, k], contrast)
    # Cada vèrtex de `dst` pren el del vèrtex original més proper.
    return per_v[_nearest_index(dst.vertices, src.vertices)]


# ---------------------------------------------------------------- QEM amb pesos

def qem(V: np.ndarray, F: np.ndarray, target: int, weight: np.ndarray,
        plane: tuple[np.ndarray, np.ndarray] | None = None, locked: np.ndarray | None = None):
    """Simplificació per col·lapse d'arestes (Garland–Heckbert) amb un pes per vèrtex.

    `locked`: vèrtexs fixos (punts clau): no es mouen ni desapareixen; el que s'hi ajunta
    queda al seu lloc.
    `plane` (punt, normal): els vèrtexs que hi són hi queden (tall de simetria). Les vores
    obertes porten quadriques de restricció i no es pleguen. Es comprova que cap triangle no
    es giri i que la malla segueixi sent una superfície (condició d'enllaç).
    """
    V = V.astype(float).copy()
    F = F.copy()
    nv = len(V)
    alive = np.ones(len(F), bool)
    vfaces: list[set] = [set() for _ in range(nv)]
    for fi, f in enumerate(F):
        for v in f:
            vfaces[v].add(fi)

    tri = V[F]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(nrm, axis=1)
    nrm = nrm / np.maximum(area, 1e-12)[:, None]
    p = np.column_stack([nrm, -(nrm * tri[:, 0]).sum(1)])
    K = (area / 2)[:, None, None] * p[:, :, None] * p[:, None, :]
    Q = np.zeros((nv, 4, 4))
    for k in range(3):
        np.add.at(Q, F[:, k], K)
    # Vores obertes: un pla perpendicular a la cara per cada aresta de vora.
    edges = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
    owner = np.tile(np.arange(len(F)), 3)
    uniq, inv, cnt = np.unique(edges, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    scale = float(np.mean(area)) if len(area) else 1.0
    bound_v = np.zeros(nv, bool)
    for ei in np.nonzero(cnt == 1)[0]:
        a, b = uniq[ei]
        fi = owner[np.nonzero(inv == ei)[0][0]]
        e = V[b] - V[a]
        bn = np.cross(e, nrm[fi])
        ln = np.linalg.norm(bn)
        if ln < 1e-12:
            continue
        bn /= ln
        bp = np.append(bn, -bn @ V[a])
        Kb = BOUNDARY_WEIGHT * scale * np.outer(bp, bp)
        Q[a] += Kb
        Q[b] += Kb
        bound_v[[a, b]] = True
    Q *= weight[:, None, None]
    on_plane = np.zeros(nv, bool)
    if plane is not None:
        c, n = plane
        on_plane = np.abs((V - c) @ n) < 1e-9 * max(1.0, float(np.abs(V).max()))

    def to_plane(x):
        if plane is None:
            return x
        return x - ((x - plane[0]) @ plane[1]) * plane[1]

    def cost_of(q, x):
        h = np.append(x, 1.0)
        return float(h @ q @ h)

    fixed = np.zeros(nv, bool) if locked is None else locked.astype(bool).copy()

    def best(a: int, b: int):
        q = Q[a] + Q[b]
        if fixed[a] and fixed[b]:
            return math.inf, None
        if fixed[a] or fixed[b]:
            x = V[a] if fixed[a] else V[b]
            return cost_of(q, x), x
        if on_plane[a] != on_plane[b]:  # el del pla no se'n pot moure
            x = V[a] if on_plane[a] else V[b]
            return cost_of(q, x), x
        cands = [V[a], V[b], (V[a] + V[b]) / 2]
        try:
            x = np.linalg.solve(q[:3, :3], -q[:3, 3])
            if np.all(np.isfinite(x)) and np.linalg.norm(x - (V[a] + V[b]) / 2) < \
                    3 * np.linalg.norm(V[a] - V[b]) + 1e-9:
                cands.append(x)
        except np.linalg.LinAlgError:
            pass
        if on_plane[a]:
            cands = [to_plane(x) for x in cands]
        costs = [cost_of(q, x) for x in cands]
        i = int(np.argmin(costs))
        return costs[i], cands[i]

    def neighbours(v: int) -> set:
        return {int(u) for fi in vfaces[v] for u in F[fi]} - {v}

    def collapse(a: int, b: int) -> bool:
        """Col·lapsa l'aresta (a, b) a a, si és vàlid. Retorna si s'ha fet."""
        if not vfaces[a] or not vfaces[b] or (fixed[a] and fixed[b]):
            return False
        if fixed[b]:  # es queda el fix
            a, b = b, a
        shared = vfaces[a] & vfaces[b]
        if not shared:
            return False
        # Condició d'enllaç: els veïns comuns han de ser exactament els de les cares comunes.
        if len(neighbours(a) & neighbours(b)) != len(shared):
            return False
        if bound_v[a] and bound_v[b] and len(shared) != 1:
            return False  # aresta interior entre dues vores: pinçaria la superfície
        _, x = best(a, b)
        for fi in (vfaces[a] | vfaces[b]) - shared:
            f = F[fi]
            old = V[f]
            new = np.array([x if v in (a, b) else V[v] for v in f])
            n0 = np.cross(old[1] - old[0], old[2] - old[0])
            n1 = np.cross(new[1] - new[0], new[2] - new[0])
            l0, l1 = np.linalg.norm(n0), np.linalg.norm(n1)
            if l1 < 1e-12 * max(l0, 1e-12) or (l0 > 0 and n0 @ n1 < 0.2 * l0 * l1):
                return False  # el triangle es giraria o quedaria pla
        V[a] = x
        Q[a] = Q[a] + Q[b]
        bound_v[a] |= bound_v[b]
        on_plane[a] |= on_plane[b]
        for fi in shared:
            alive[fi] = False
            for v in F[fi]:
                vfaces[v].discard(fi)
        for fi in list(vfaces[b]):
            F[fi][F[fi] == b] = a
            vfaces[a].add(fi)
        vfaces[b].clear()
        return True

    # Per rondes: a cada ronda es calculen tots els costos i es fan alhora els col·lapses més
    # barats que no es toquen entre ells (cap vèrtex compartit ni veí). Així dues zones
    # equivalents (un ull i l'altre) es simplifiquen a la mateixa ronda i igual: no és l'ordre
    # d'una cua el que decideix quina perd abans.
    faces_left = int(alive.sum())
    while faces_left > target:
        act = F[alive]
        E = np.unique(np.sort(np.concatenate([act[:, [0, 1]], act[:, [1, 2]], act[:, [2, 0]]]),
                              axis=1), axis=0)
        if not len(E):
            break
        costs = np.array([best(int(a), int(b))[0] for a, b in E])
        order = np.argsort(costs, kind="stable")
        need = max(1, (faces_left - target + 1) // 2)
        limit = max(1, min(need, len(order) // ROUND_SHARE))
        cut = costs[order[min(len(order) - 1, 2 * limit)]]  # només els barats d'aquesta ronda
        locked = np.zeros(nv, bool)
        done = 0
        for i in order:
            if done >= limit or (done and costs[i] > cut * (1 + 1e-9) + 1e-15):
                break
            a, b = int(E[i][0]), int(E[i][1])
            if locked[a] or locked[b]:
                continue
            if not math.isfinite(costs[i]):
                break
            if collapse(a, b):
                done += 1
                for v in (a, b):  # el que queda pot ser qualsevol dels dos
                    if vfaces[v]:
                        locked[v] = True
                        locked[list(neighbours(v))] = True
        if not done:
            break
        faces_left = int(alive.sum())

    keep = np.nonzero(alive)[0]
    out = trimesh.Trimesh(V, F[keep], process=False)
    out.remove_unreferenced_vertices()
    return out


# ---------------------------------------------------------------- tot junt

def reduce(mesh: trimesh.Trimesh, target: int, symmetry: str = "no", detail: float = 30.0,
           texture=None, texture_mesh: trimesh.Trimesh | None = None):
    """Simplifica `mesh` a unes `target` cares respectant la forma.

    `symmetry`: "no" (per defecte: no s'imposa cap simetria), "auto" (si el model ja és
    simètric, el resultat ho és exactament), o "x", "y", "z" (força aquell pla pel centre).
    `detail`: quant pesen els detalls (0 = QEM normal). Retorna (malla, informació).
    """
    import papercraft as pc
    info = {"simetria": None}
    if len(mesh.faces) <= target:
        return pc.clean(mesh), info
    pre = pc.simplify(mesh, max(PRE_MIN, PRE_FACTOR * target)) \
        if len(mesh.faces) > max(PRE_MIN, PRE_FACTOR * target) else pc.clean(mesh)
    if len(pre.faces) <= target:
        return pre, info
    sym = None if symmetry == "no" else find_symmetry(pre, symmetry)
    weight = 1.0 + detail * importance(pre, texture, texture_mesh, target)
    if sym is not None:
        c, n, err = sym
        info["simetria"] = dict(normal=n.round(3).tolist(), error=round(err, 4),
                                point=c.tolist(), n=n.tolist())
        HV, HF = split_half(pre, c, n)
        half = trimesh.Trimesh(HV, HF, process=False)
        # Pes dels vèrtexs nous del tall: el del vèrtex original més proper.
        w = np.ones(len(HV))
        w[:len(pre.vertices)] = weight
        if len(HV) > len(pre.vertices):
            near = _nearest_index(HV[len(pre.vertices):], pre.vertices)
            w[len(pre.vertices):] = weight[near]
        used = np.unique(HF)
        remap = -np.ones(len(HV), dtype=np.int64)
        remap[used] = np.arange(len(used))
        half = trimesh.Trimesh(HV[used], remap[HF], process=False)
        red = qem(half.vertices, half.faces, max(4, target // 2), w[used], plane=(c, n))
        mir = red.vertices - 2 * ((red.vertices - c) @ n)[:, None] * n
        both = trimesh.Trimesh(np.vstack([red.vertices, mir]),
                               np.vstack([red.faces, red.faces[:, ::-1] + len(red.vertices)]),
                               process=False)
        both.merge_vertices()
        out = pc.clean(both)
        # Amb poques cares la simetria exacta pot no caber (el tall pel pla parteix cares: una
        # caixa simètrica en necessita 20): si s'allunya massa de la forma, es fa sense.
        diag = float(np.linalg.norm(pre.extents))
        if deviation(pre, out) > SHAPE_TOL * diag:
            plain = pc.clean(qem(pre.vertices, pre.faces, target, weight))
            if deviation(pre, plain) < deviation(pre, out):
                info["simetria"] = None
                info["simetria_descartada"] = True
                out = plain
    else:
        out = pc.clean(qem(pre.vertices, pre.faces, target, weight))
    return out, info


def deviation(ref: trimesh.Trimesh, m: trimesh.Trimesh, samples: int = 3000) -> float:
    """Quant s'allunya `m` de `ref` (percentil 95, en unitats del model), en les dues direccions."""
    a, _ = trimesh.sample.sample_surface(ref, samples, seed=4)
    b, _ = trimesh.sample.sample_surface(m, samples * 6, seed=5)
    c, _ = trimesh.sample.sample_surface(m, samples, seed=6)
    d, _ = trimesh.sample.sample_surface(ref, samples * 6, seed=7)
    return float(max(np.percentile(_nearest(a, b), 95), np.percentile(_nearest(c, d), 95)))


def _nearest_index(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if cKDTree is not None:
        return cKDTree(b).query(a)[1]
    b2 = (b ** 2).sum(1)
    out = np.empty(len(a), dtype=int)
    for i in range(0, len(a), 2048):
        x = a[i:i + 2048]
        out[i:i + 2048] = ((x ** 2).sum(1)[:, None] + b2[None] - 2 * x @ b.T).argmin(1)
    return out
