"""Pont entre una sessió SfM (COLMAP) i el visor orbital: poses de càmera al voltant d'un edifici.

La sessió ve de `048-escena-video` (vídeo al voltant de l'edifici → `dades/sessions/<nom>/A/sparse/millor`).
Aquí no es recalcula res d'SfM: es llegeix el model, es deriva la vertical de les pròpies càmeres, es
posa el centre de l'edifici a l'origen i cada càmera es descriu com el visor la vol: azimut, elevació,
distància, roll, FOV i alçada de mirada. Per rodar amb pycolmap cal el python de 048-escena-video:

    048-escena-video/venv/bin/python sfm_poses.py <carpeta sparse/millor> <carpeta frames> sortida.json

Convenció de l'escena (la mateixa del visor): Y amunt, azimut 0 = -Z, creix cap a +X; la càmera mira
el punt (0, mirY, 0). L'azimut absolut no es coneix (l'SfM no té nord): la primera càmera és a 180° i
`--gir` ho rota; amb la planta es fixarà més endavant.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import math
from pathlib import Path

import numpy as np

VERSIO = 1


def _unit(v):
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError("Vector nul.")
    return v / n


def _gira_a_y(up: np.ndarray) -> np.ndarray:
    """Rotació (3×3) que porta el vector unitari `up` a (0, 1, 0)."""
    y = np.array([0.0, 1.0, 0.0])
    v, c = np.cross(up, y), float(up @ y)
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


def poses_visor(centres, r_cam_des_de_mon, mides, focals, gir=0.0, radi=60.0, percentil_terra=2.0, punts=None):
    """Poses de visor per a càmeres d'una sessió SfM.

    centres: (N,3) centres de càmera al món; r_cam_des_de_mon: (N,3,3) rotació món→càmera (convenció
    COLMAP/OpenCV: x dreta, y avall, z endavant); mides: (N,2) amplada, alçada; focals: (N,) en px.
    `punts` (M,3, opcional) serveix per posar el terra. Retorna (poses, transformació) on cada pose és un
    dict i la transformació porta punts del món a l'escena: p' = escala · M · (p − origen)."""
    C = np.asarray(centres, float)
    R = np.asarray(r_cam_des_de_mon, float)
    if len(C) < 3:
        raise ValueError("Calen almenys 3 càmeres.")
    avall = R[:, 1, :]                                   # eix y de la càmera (avall) en coordenades del món
    # La vertical és la mitjana de l'«amunt» de les càmeres: en una volta completa el capcineig (apuntar
    # amunt o avall) s'anul·la per simetria. Descartar les càmeres més inclinades el biaixaria.
    up = _unit(-avall.mean(axis=0))
    M = _gira_a_y(up)
    P = (C - C.mean(axis=0)) @ M.T                       # centrat provisional
    centre_h = np.array([P[:, 0].mean(), 0.0, P[:, 2].mean()])
    base = C.mean(axis=0)
    if punts is not None and len(punts):
        y = ((np.asarray(punts, float) - base) @ M.T)[:, 1]
        terra = float(np.percentile(y, percentil_terra))
    else:
        terra = float(P[:, 1].min()) - 1.0
    origen_scene = np.array([centre_h[0], terra, centre_h[2]])
    S = P - origen_scene
    dh = np.hypot(S[:, 0], S[:, 2])
    escala = radi / float(np.median(dh))
    S = S * escala
    az = np.degrees(np.arctan2(S[:, 0], -S[:, 2]))
    desplaca = 180.0 - az[0] + gir
    az = (az + desplaca) % 360.0
    c, s = math.cos(math.radians(desplaca)), math.sin(math.radians(desplaca))
    # gir de l'escena sobre Y perquè l'azimut calculat coincideixi amb la posició
    Ry = np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]])      # x' = c·x − s·z, z' = s·x + c·z: suma `desplaca` a l'azimut
    S = S @ Ry.T
    dist = np.linalg.norm(S, axis=1)
    el = np.degrees(np.arctan2(S[:, 1], np.hypot(S[:, 0], S[:, 2])))
    poses = []
    for i in range(len(C)):
        f = _unit(R[i, 2, :] @ M.T @ Ry.T)               # endavant en l'escena
        u_cam = _unit(-R[i, 1, :] @ M.T @ Ry.T)           # amunt de la càmera en l'escena
        # alçada on l'eix òptic passa més a prop de l'eix vertical (0, y, 0)
        p0, d = S[i], f
        horitzontal = np.array([d[0], 0.0, d[2]])
        den = float(horitzontal @ horitzontal)
        mir_y = 0.0
        if den > 1e-9:
            t = -float(np.array([p0[0], 0.0, p0[2]]) @ horitzontal) / den
            mir_y = float(p0[1] + t * d[1])
        mir_y = float(np.clip(mir_y, 0.0, 60.0))
        T = np.array([0.0, mir_y, 0.0])
        dir_visor = _unit(T - S[i])
        desv = math.degrees(math.acos(float(np.clip(dir_visor @ f, -1, 1))))
        u0 = _unit(np.array([0.0, 1.0, 0.0]) - f[1] * f)   # amunt «de nivell» per a l'endavant real
        roll = math.degrees(math.atan2(float(f @ np.cross(u0, u_cam)), float(u0 @ u_cam)))
        w, h = mides[i]
        fov_l = 2 * math.degrees(math.atan(max(w, h) / (2.0 * focals[i])))
        poses.append(dict(az=float(az[i]), el=float(el[i]), dist=float(dist[i]), roll=float(roll),
                          mirY=mir_y, fov_costat_llarg=float(fov_l),
                          fov_horitzontal=2 * math.degrees(math.atan(w / (2.0 * focals[i]))),
                          amplada=int(w), alcada=int(h), desviacio_graus=float(desv)))
    transf = dict(M=M.tolist(), base=base.tolist(), origen=origen_scene.tolist(), escala=float(escala), Ry=Ry.tolist())
    return poses, transf


def aplica(transf, punts):
    """Porta punts del món (K,3) a l'escena del visor."""
    t = transf
    P = (np.asarray(punts, float) - np.array(t["base"])) @ np.array(t["M"]).T
    return ((P - np.array(t["origen"])) * t["escala"]) @ np.array(t["Ry"]).T


def tria_per_azimut(poses, pes, n):
    """Índexs de `n` càmeres repartides per azimut, la millor (més pes) de cada sector."""
    az = np.array([p["az"] for p in poses])
    triats = []
    for k in range(n):
        lo, hi = 360.0 * k / n, 360.0 * (k + 1) / n
        idx = [i for i in range(len(poses)) if lo <= az[i] < hi]
        if idx:
            triats.append(max(idx, key=lambda i: pes[i]))
    return triats


def exporta(sparse: Path, frames: Path, sortida: Path, n=10, gir=0.0, radi=60.0, mida_min=640, max_punts=6000):
    import pycolmap
    from PIL import Image
    rec = pycolmap.Reconstruction(str(sparse))
    ids = sorted(rec.images, key=lambda k: rec.images[k].name)
    C, R, mides, focals, noms, pes = [], [], [], [], [], []
    for k in ids:
        im = rec.images[k]; cam = rec.cameras[im.camera_id]
        C.append(np.array(im.projection_center())); R.append(im.cam_from_world().rotation.matrix())
        mides.append((cam.width, cam.height)); focals.append(cam.focal_length); noms.append(im.name); pes.append(im.num_points3D)
    xyz = np.array([p.xyz for p in rec.points3D.values()])
    col = np.array([p.color for p in rec.points3D.values()])
    poses, tr = poses_visor(C, R, mides, focals, gir=gir, radi=radi, punts=xyz)
    sc = aplica(tr, xyz)
    ok = np.linalg.norm(sc, axis=1) < 2.5 * max(p["dist"] for p in poses)       # descarta els punts molt llunyans (soroll)
    sc, col = sc[ok], col[ok]
    if len(sc) > max_punts:
        sel = np.random.default_rng(0).choice(len(sc), max_punts, replace=False); sc, col = sc[sel], col[sel]
    fotos = []
    for i in tria_per_azimut(poses, pes, n):
        im = Image.open(frames / noms[i]).convert("RGB"); im.thumbnail((mida_min, mida_min))
        b = io.BytesIO(); im.save(b, "JPEG", quality=72)
        fotos.append(dict(nom=noms[i], src="data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode(), **poses[i]))
    out = dict(versio=VERSIO, origen="sfm", sessio=str(sparse), radi=radi, fotos=fotos,
               totes_les_poses=[dict(nom=noms[i], **{k: round(v, 3) if isinstance(v, float) else v for k, v in poses[i].items()}) for i in range(len(poses))],
               nuvol=dict(punts=np.round(sc, 2).tolist(), colors=col.astype(int).tolist()))
    sortida.write_text(json.dumps(out, separators=(",", ":")))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sparse", type=Path); ap.add_argument("frames", type=Path); ap.add_argument("sortida", type=Path)
    ap.add_argument("--fotos", type=int, default=10); ap.add_argument("--gir", type=float, default=0.0)
    ap.add_argument("--radi", type=float, default=60.0)
    a = ap.parse_args()
    o = exporta(a.sparse, a.frames, a.sortida, n=a.fotos, gir=a.gir, radi=a.radi)
    d = np.array([p["desviacio_graus"] for p in o["totes_les_poses"]])
    print(f"{len(o['totes_les_poses'])} càmeres, {len(o['fotos'])} fotos triades, {len(o['nuvol']['punts'])} punts")
    print(f"desviació entre l'eix real i el del visor: mediana {np.median(d):.1f}°, p90 {np.percentile(d, 90):.1f}°")
