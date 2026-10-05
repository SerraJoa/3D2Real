"""Vista 3D senzilla (projecció axonomètrica, cares ordenades per profunditat) en SVG."""
from __future__ import annotations

import math

import numpy as np
import trimesh

PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#76b7b2", "#edc948", "#9c755f",
           "#ff9da7", "#bab0ac", "#e15759"]


def view_svg(mesh: trimesh.Trimesh, colors: list[str], width: float = 400,
             yaw: float = 35, pitch: float = 25, title: str = "",
             outline: list[bool] | None = None) -> str:
    """Dibuixa la malla vista des de (yaw, pitch) graus; `colors` és un color per cara."""
    a, b = math.radians(yaw), math.radians(pitch)
    Rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    # Mirem des de -y: x a la dreta, z amunt; la profunditat és y.
    V = (mesh.vertices - mesh.centroid) @ (Rx @ Rz).T
    N = mesh.face_normals @ (Rx @ Rz).T
    P = np.column_stack([V[:, 0], -V[:, 2]])
    lo, hi = P.min(0), P.max(0)
    scale = width / max(hi - lo)
    P = (P - lo) * scale + 10
    depth = V[mesh.faces][:, :, 1].mean(1)
    light = np.array([-0.4, -0.8, 0.45])
    light /= np.linalg.norm(light)
    W, H = P.max(0) + 10
    W = max(W, 7.5 * len(title) + 20)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H + 20:.0f}" '
           f'viewBox="0 0 {W:.0f} {H + 20:.0f}"><rect width="100%" height="100%" fill="white"/>']
    for f in np.argsort(-depth):  # del fons cap endavant
        if N[f, 1] > 0:           # d'esquena
            continue
        shade = 0.7 + 0.3 * max(0.0, float(-N[f] @ light))
        c = colors[f].lstrip("#")
        rgb = [int(int(c[i:i + 2], 16) * shade) for i in (0, 2, 4)]
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in P[mesh.faces[f]])
        stroke = "#000" if outline is not None and outline[f] else "#333"
        sw = 2.0 if outline is not None and outline[f] else 0.3
        out.append(f'<polygon points="{pts}" fill="rgb({rgb[0]},{rgb[1]},{rgb[2]})" '
                   f'stroke="{stroke}" stroke-width="{sw}"/>')
    if title:
        out.append(f'<text x="10" y="{H + 14:.0f}" font-family="sans-serif" font-size="13">'
                   f'{title}</text>')
    out.append("</svg>")
    return "\n".join(out)


def plates_view(result, **kw) -> str:
    """Plaques de la branca de cares, acolorides pel grup de plaques unides per suports."""
    ex = result.extra
    m, plate_of, group = ex["mesh"], ex["plate_of"], ex["group"]
    order = {g: i for i, g in enumerate(dict.fromkeys(group[k] for k in sorted(group)))}
    colors = [PALETTE[order[group[int(k)]] % len(PALETTE)] for k in plate_of]
    lonely = [ex["supports"][int(k)] == 0 for k in plate_of]
    return view_svg(m, colors, outline=lonely, **kw)


def faces_view(mesh: trimesh.Trimesh, frames, decorated=(), width: float = 380,
               yaw: float = 35, pitch: float = 25) -> str:
    """Vista 3D amb el número de cada cara (C1, C2…); les cares decorades, en color."""
    cara = np.zeros(len(mesh.faces), dtype=int)
    for fr in frames:
        cara[fr.faces] = fr.index
    colors = ["#f28e2b" if cara[f] in decorated else "#d9e2ec" for f in range(len(mesh.faces))]
    svg = view_svg(mesh, colors, width=width, yaw=yaw, pitch=pitch)
    # Etiquetes al centre de cada cara visible.
    a, b = math.radians(yaw), math.radians(pitch)
    Rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    R = Rx @ Rz
    V = (mesh.vertices - mesh.centroid) @ R.T
    P = np.column_stack([V[:, 0], -V[:, 2]])
    lo, hi = P.min(0), P.max(0)
    scale = width / max(hi - lo)
    labels = []
    visible = [fr for fr in frames if (fr.normal @ R.T)[1] <= -0.15]  # ni d'esquena ni de cantell
    # Amb moltes cares, només les més grans (les altres no es podrien llegir).
    visible = sorted(visible, key=lambda fr: -mesh.area_faces[fr.faces].sum())[:40]
    for fr in visible:
        fs = fr.faces
        c = (mesh.triangles_center[fs] * mesh.area_faces[fs, None]).sum(0) / mesh.area_faces[fs].sum()
        q = (c - mesh.centroid) @ R.T
        x, y = (np.array([q[0], -q[2]]) - lo) * scale + 10
        size = math.sqrt(mesh.area_faces[fs].sum()) * scale / 4
        if size < 6:
            continue
        size = float(min(size, 14))
        common = (f'x="{x:.1f}" y="{y:.1f}" font-family="sans-serif" font-size="{size:.1f}" '
                  f'text-anchor="middle" dominant-baseline="central"')
        labels.append(f'<text {common} fill="white" stroke="white" stroke-width="3">C{fr.index + 1}</text>'
                      f'<text {common} fill="#102a43">C{fr.index + 1}</text>')
    return svg.replace("</svg>", "".join(labels) + "</svg>")
