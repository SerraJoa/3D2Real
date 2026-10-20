"""Segmentació d'una malla en parts pels plecs còncaus (coll, aixelles, base d'orelles...).

Cada part és un volum que es pot descriure amb una primitiva (caixa, caixa que s'estreny,
extrusió plana). Cap llavor posada a mà: les llavors surten de la mateixa malla.

1. **Llavors a les extremitats**: la cara més central i després, successivament, la més
   allunyada de les llavors segons la distància sobre la superfície (puntes d'orelles, cua,
   peus, morro...), mentre quedi més lluny de `ext_min` de la diagonal.
2. **Regions**: cada cara va a la llavor que hi arriba amb menys cost. El cost d'una aresta és
   l'angle només si és còncava (la superfície s'enfonsa) més un petit terme de longitud: les
   regions creixen lliures per superfícies convexes i es freguen als plecs.
3. **Fusió**: de cada parell de regions veïnes es mesura la *concavitat mitjana* de la vora
   que comparteixen (angle amb signe: còncau positiu, convex negatiu). Si és plana o convexa
   (menys de `fusio` radians), les dues llavors eren de la mateixa part i s'ajunten; es
   repeteix amb la parella menys còncava fins que totes les vores restants són plecs.
4. Les parts petites (menys de `min_area` de l'àrea total) s'ajunten a la veïna amb més vora.
"""
from __future__ import annotations

import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree


def _csr(n, a, b, w):
    return coo_matrix((np.r_[w, w], (np.r_[a, b], np.r_[b, a])), shape=(n, n)).tocsr()


def segment(mesh: trimesh.Trimesh, ext_min: float = 0.10, fusio: float = 0.30,
            min_area: float = 0.03, max_seeds: int = 40, seeds: list[int] | None = None,
            seed_groups: list[int] | None = None,
            conc_max: float = 1.01, conc_deg_rad: float = 0.26) -> np.ndarray:
    """Retorna l'etiqueta (0..k-1) de cada cara. `seeds`: cares llavor ja decidides (p. ex. pel
    VL); si no, es busquen a les extremitats."""
    n = len(mesh.faces)
    adj = mesh.face_adjacency
    ang = mesh.face_adjacency_angles
    convex = mesh.face_adjacency_convex
    signed = np.where(convex, -ang, ang)                       # còncau > 0
    C = mesh.triangles_center
    diag = float(np.linalg.norm(mesh.extents))
    d = np.linalg.norm(C[adj[:, 0]] - C[adj[:, 1]], axis=1)
    Geo = _csr(n, adj[:, 0], adj[:, 1], d)
    Cost = _csr(n, adj[:, 0], adj[:, 1], np.where(convex, 0.0, ang) + 0.02 * d / diag)
    # només la component connexa (per arestes) més gran; la resta s'assigna al final per proximitat
    _, comp = connected_components(Geo, directed=False)
    big = np.bincount(comp).argmax()
    inside = np.where(comp == big)[0]
    # 1. llavors per extremitats (o les que es donen)
    given = seeds is not None
    group_of: dict[int, set] = {}
    if given:
        for k, s in enumerate(seeds):
            group_of.setdefault(int(s), set()).add(seed_groups[k] if seed_groups is not None else None)
        seeds = sorted(group_of)
    else:
        seeds = [int(inside[np.argmin(np.linalg.norm(C[inside] - C[inside].mean(0), axis=1))])]
    while not given and len(seeds) < max_seeds:
        dist = dijkstra(Geo, indices=seeds, min_only=True)
        dist[~np.isfinite(dist)] = 0
        far = int(np.argmax(dist))
        if dist[far] < ext_min * diag:
            break
        seeds.append(far)
    # 2. regions
    _, _, src = dijkstra(Cost, indices=seeds, min_only=True, return_predecessors=True)
    lab = np.array([seeds.index(s) if s in seeds else 0 for s in src])
    outside = np.where(comp != big)[0]
    if len(outside):
        lab[outside] = lab[inside[cKDTree(C[inside]).query(C[outside])[1]]]
    area = mesh.area_faces

    concave = signed > conc_deg_rad

    def pair_stats(lab):
        """Per parella de regions: (concavitat mitjana de la vora, fracció de la vora còncava, llargada)."""
        a, b = lab[adj[:, 0]], lab[adj[:, 1]]
        sel = a != b
        lo, hi = np.minimum(a[sel], b[sel]), np.maximum(a[sel], b[sel])
        out: dict[tuple[int, int], list] = {}
        for i, j, s, ln, cv in zip(lo, hi, signed[sel], d[sel], concave[sel]):
            e = out.setdefault((int(i), int(j)), [0.0, 0.0, 0.0])
            e[0] += s * ln
            e[1] += ln * cv
            e[2] += ln
        return {k: (v[0] / v[2], v[1] / v[2], v[2]) for k, v in out.items()}

    # 3. fusió de regions de la mateixa part: vora plana o convexa (mitjana < fusio) i amb
    #    poca vora còncava (fracció < conc_max). `conc_max` > 1 (per defecte) la desactiva: provada
    #    amb 0,25 no millora el ninot i trenca la cara amb conques.
    rv = {k: set(group_of[s]) - {None} for k, s in enumerate(seeds)} if given else {}
    while True:
        st = {k: v for k, v in pair_stats(lab).items() if v[0] < fusio and v[1] < conc_max
              and rv.get(k[0], set()).isdisjoint(rv.get(k[1], set()))}   # mateixa vista = parts diferents
        if not st:
            break
        (i, j) = min(st, key=lambda k: st[k][0])
        lab[lab == j] = i
        rv[i] = rv.get(i, set()) | rv.pop(j, set())
    # 4. parts petites
    while True:
        _, lab = np.unique(lab, return_inverse=True)
        k = lab.max() + 1
        tot = np.bincount(lab, weights=area, minlength=k)
        small = [i for i in range(k) if tot[i] < min_area * tot.sum()]
        if not small or k == 1:
            break
        i = min(small, key=lambda q: tot[q])
        st = {p: v for p, v in pair_stats(lab).items() if i in p}
        if not st:
            break
        p = max(st, key=lambda q: st[q][2])
        lab[lab == i] = p[0] if p[1] == i else p[1]
    return lab


def clean_labels(mesh: trimesh.Trimesh, lab: np.ndarray, rounds: int = 3) -> np.ndarray:
    """Parts netes: cap part amb trossos del veí ni illes soltes.

    1. Votació amb els veïns: una cara voltada de dues altres parts s'hi passa (treu les
       dents de la vora entre parts).
    2. Cada part es queda només amb el seu tros connex més gran; els altres trossos passen
       a la part amb qui comparteixen més vora.
    """
    lab = lab.copy()
    adj = mesh.face_adjacency
    n = len(lab)
    for _ in range(rounds):
        votes = [dict() for _ in range(n)]
        for a, b in adj:
            votes[a][lab[b]] = votes[a].get(lab[b], 0) + 1
            votes[b][lab[a]] = votes[b].get(lab[a], 0) + 1
        new = lab.copy()
        for i, v in enumerate(votes):
            top = max(v, key=v.get) if v else lab[i]
            if top != lab[i] and v[top] >= 2:
                new[i] = top
        if (new == lab).all():
            break
        lab = new
    for _ in range(400):                                  # illes: només el tros més gran
        same = lab[adj[:, 0]] == lab[adj[:, 1]]
        g = coo_matrix((np.ones(same.sum()), (adj[same, 0], adj[same, 1])), shape=(n, n))
        k, comp = connected_components(g, directed=False)
        size = np.bincount(comp, weights=mesh.area_faces, minlength=k)
        comp_lab = np.zeros(k, int)
        comp_lab[comp] = lab
        main = {int(l): int(np.argmax(np.where(comp_lab == l, size, -1))) for l in np.unique(lab)}
        stray = [c for c in range(k) if main[int(comp_lab[c])] != c]
        if not stray:
            return lab
        c = min(stray, key=lambda q: size[q])
        faces = comp == c
        cross = faces[adj[:, 0]] ^ faces[adj[:, 1]]
        other = np.where(faces[adj[cross, 0]], lab[adj[cross, 1]], lab[adj[cross, 0]])
        if len(other):
            lab[faces] = np.bincount(other).argmax()
        else:                                             # illa sense veïns per aresta: la més propera
            C = mesh.triangles_center
            rest = np.where(~faces)[0]
            lab[faces] = lab[rest[cKDTree(C[rest]).query(C[faces].mean(0))[1]]]
    return lab

