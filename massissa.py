"""Parts massisses: zones de la figura ajustada original que es fan com a peça tancada (3D)."""
from __future__ import annotations

import numpy as np
import trimesh
from scipy.spatial import cKDTree

import papercraft as pc


def solid_part(mesh: trimesh.Trimesh, size_mm: float, prepared: trimesh.Trimesh, frames: list,
               chosen: list[int]) -> tuple[trimesh.Trimesh, bool]:
    """Peça tancada amb la part de `mesh` (la figura ajustada, sense simplificar) que cau a les
    cares `chosen` del model simplificat `prepared`. Torna la malla i si ha quedat estanca.

    Cada triangle de l'original va a la cara simplificada més propera; la zona es tanca amb
    el forat omplert per la vora.
    """
    full = pc.scale_to(pc.clean(mesh), size_mm)
    owner = np.full(len(prepared.faces), -1)
    for k, fr in enumerate(frames):
        owner[list(fr.faces)] = k
    # Cada triangle simplificat es mostreja (vèrtexs, mitjos i centre) i es busca el més proper.
    T = prepared.triangles
    a, b, c = T[:, 0], T[:, 1], T[:, 2]
    samples = np.concatenate([T.mean(1), a, b, c, (a + b) / 2, (b + c) / 2, (c + a) / 2,
                              (a + b + 2 * c) / 4, (a + 2 * b + c) / 4, (2 * a + b + c) / 4])
    tri = np.tile(np.arange(len(T)), 10)[cKDTree(samples).query(full.triangles_center)[1]]
    keep = np.isin(owner[tri], chosen)
    if not keep.any():
        raise ValueError("Cap triangle de la figura cau a les cares triades.")
    part = full.submesh([np.flatnonzero(keep)], append=True)
    # Triangles solts que han anat a parar a la cara (soroll de vora) es descarten.
    comps = part.split(only_watertight=False)
    big = max(len(c.faces) for c in comps)
    comps = [_cap(c) for c in comps if len(c.faces) >= max(4, 0.15 * big)]
    part = trimesh.util.concatenate(comps)
    return part, bool(part.is_watertight)


def _cap(m: trimesh.Trimesh) -> trimesh.Trimesh:
    """Tanca cada anell de vora amb un ventall des del seu centre."""
    m = m.copy()
    m.merge_vertices()
    edges = m.edges_sorted
    uniq, counts = np.unique(edges, axis=0, return_counts=True)
    border = {}
    for u, v in uniq[counts == 1]:
        border.setdefault(int(u), []).append(int(v))
        border.setdefault(int(v), []).append(int(u))
    # Les arestes de vora es recorren com a anells; el sentit s'agafa de les cares.
    directed = {}
    for f in m.faces:
        for i in range(3):
            a, b = int(f[i]), int(f[(i + 1) % 3])
            if tuple(sorted((a, b))) in {tuple(e) for e in uniq[counts == 1]}:
                directed[b] = a   # l'aresta oposada (b→a) és la que cal per tancar
    verts, faces, seen = list(m.vertices), list(m.faces), set()
    for start in list(directed):
        if start in seen:
            continue
        loop, cur = [], start
        while cur not in seen and cur in directed:
            seen.add(cur)
            loop.append(cur)
            cur = directed[cur]
        if len(loop) < 3:
            continue
        c = len(verts)
        verts.append(np.mean([m.vertices[i] for i in loop], axis=0))
        for i in range(len(loop)):
            faces.append([loop[i], loop[(i + 1) % len(loop)], c])
    out = trimesh.Trimesh(np.array(verts), np.array(faces), process=False)
    out.merge_vertices()
    trimesh.repair.fix_normals(out)
    return out
