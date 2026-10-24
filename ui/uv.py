"""Pas UV: fer servir la UV que porta el model, importar-ne una d'un altre fitxer, o cap.

Només hi ha UV si hi ha una imatge de textura. Una UV importada ve d'un model amb textura (OBJ amb
MTL i imatge, o GLB) que ha de ser el mateix objecte i estar en la mateixa posició que el fitxer
carregat: s'hi aplica la mateixa orientació i el mateix moviment d'encaix, i la UV es passa a la
malla tallada pel triangle original més proper.
"""
import base64
import io

import numpy as np
import streamlit as st
import trimesh
from PIL import Image
from scipy.spatial import cKDTree

import decor as dc
import papercraft as pc
from ui import carpeta, portada

FRASE = ("UV del model: fa servir la que ja porta el fitxer. Importar UV: carregues el mateix model "
         "amb textura (OBJ amb MTL i imatge, o GLB) i se n'agafa la UV. Sense UV: sense textura.")
OPCIONS = [("uvmodel", "UV del model", "uv_model.png"),
           ("uvimporta", "Importar UV", "uv_importa.png"),
           ("uvcap", "Sense UV", "uv_cap.png")]


def transfer(src: trimesh.Trimesh, src_uv: np.ndarray, dst: trimesh.Trimesh, k: int = 24) -> np.ndarray:
    """UV (F, 3, 2) per als triangles de `dst` a partir de `src`: com `decor.transfer_uv`, però
    vectoritzat i amb cerca per arbre (uns segons en lloc de més de 20 s amb 30.000 cares)."""
    tri, c = src.triangles, dst.triangles_center
    k = min(k, len(tri))
    near = cKDTree(src.triangles_center).query(c, k=k)[1].reshape(len(c), -1)
    n, kk = near.shape
    P = np.repeat(c, kk, 0)
    cp = trimesh.triangles.closest_point(tri[near.ravel()], P)
    j = near[np.arange(n), np.linalg.norm(cp - P, axis=1).reshape(n, kk).argmin(1)]
    a = tri[j, 0]
    e1, e2 = tri[j, 1] - a, tri[j, 2] - a
    g11, g12, g22 = (e1 * e1).sum(1), (e1 * e2).sum(1), (e2 * e2).sum(1)
    det = g11 * g22 - g12 ** 2
    det = np.where(np.abs(det) < 1e-18, 1.0, det)
    p = dst.vertices[dst.faces] - a[:, None, :]
    r1, r2 = np.einsum("nci,ni->nc", p, e1), np.einsum("nci,ni->nc", p, e2)
    s, t = (g22[:, None] * r1 - g12[:, None] * r2) / det[:, None], \
        (g11[:, None] * r2 - g12[:, None] * r1) / det[:, None]
    uv = src_uv[j]
    return uv[:, 0, None, :] + s[..., None] * (uv[:, 1] - uv[:, 0])[:, None, :] \
        + t[..., None] * (uv[:, 2] - uv[:, 0])[:, None, :]


def aliniar(imp: trimesh.Trimesh, ref: trimesh.Trimesh, orient: np.ndarray, moviment: np.ndarray):
    """Posa el model importat com la peça: mateixa orientació, mateixa mida i centre, i el mateix
    moviment de l'encaix. `ref` és la peça orientada i sense tallar."""
    out = imp.copy()
    out.apply_transform(orient)
    out.apply_scale(float(max(ref.extents)) / float(max(out.extents)))
    out.apply_translation(ref.bounds.mean(0) - out.bounds.mean(0))
    out.apply_transform(moviment)
    return out


def miniatura(img: Image.Image, mida: int = 200) -> str:
    im = img.convert("RGB").copy()
    im.thumbnail((mida, mida))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def seleccio(te_model: bool) -> str:
    """UV del disseny: un botó per carregar una textura nova (OBJ amb MTL i imatge, o GLB) i un
    interruptor per activar-la. Si el model en porta, es carrega per defecte (activa); si no, l'UV
    comença apagada. Una de nova substitueix la del model. Guarda a `session_state` `uv`
    (uvcap | uvmodel | uvimporta) i, si s'ha pujat, `uv_import` = (malla, Texture)."""
    ss = st.session_state
    pujats = st.file_uploader("Carrega una textura (OBJ amb MTL i imatge, o GLB)",
                              type=["obj", "mtl", "glb", "gltf", "png", "jpg", "jpeg"],
                              accept_multiple_files=True, key="uv_pujada")
    if not pujats:
        triats = carpeta.tria((".obj", ".glb", ".gltf"), "uv_carpeta")
        if triats:
            pujats = triats + carpeta.germans(triats[0], (".mtl", ".png", ".jpg", ".jpeg"))
    if any(u.name.lower().endswith((".obj", ".glb", ".gltf")) for u in pujats):
        try:
            mesh, tex = dc.load_textured({u.name: u.getvalue() for u in pujats})
        except Exception as e:
            st.error(f"No s'ha pogut llegir: {e}")
        else:
            if tex is None:
                st.error("El fitxer no porta UV amb una imatge de textura.")
            else:
                ss["uv_import"] = (mesh, tex)
    else:
        ss.pop("uv_import", None)
    hi_ha = te_model or "uv_import" in ss
    # la clau canvia quan apareix una textura, i així l'interruptor torna a començar encès
    activa = st.toggle("UV activa", value=hi_ha, disabled=not hi_ha,
                       key=f"uv_on_{'imp' if 'uv_import' in ss else 'mod' if te_model else 'cap'}")
    ss["uv"] = ("uvimporta" if "uv_import" in ss else "uvmodel") if hi_ha and activa else "uvcap"
    if ss["uv"] == "uvimporta":
        st.image(miniatura(ss["uv_import"][1].image), caption="Textura carregada")
    return ss["uv"]
