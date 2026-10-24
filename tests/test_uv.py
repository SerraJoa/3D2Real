"""UV: passar-la a una malla tallada i alinear un model importat amb la peça."""
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import decor as dc  # noqa: E402
from ui import encaix, uv  # noqa: E402


def _esfera_uv():
    m = trimesh.creation.icosphere(2, 10)
    u = np.column_stack([np.arctan2(m.vertices[:, 1], m.vertices[:, 0]) / (2 * np.pi) + .5,
                         m.vertices[:, 2] / 20 + .5])
    return m, u[m.faces]


def test_transfer_com_el_original():
    m, face_uv = _esfera_uv()
    cut = encaix.talla(m, "sota1", (0, 0, -4, 0, 0, 0))
    a, b = uv.transfer(m, face_uv, cut), dc.transfer_uv(m, face_uv, cut)
    assert a.shape == (len(cut.faces), 3, 2)
    assert np.abs(a - b).mean() < 1e-3   # només difereix en empats de costura


def test_transfer_identitat():
    m, face_uv = _esfera_uv()
    assert np.allclose(uv.transfer(m, face_uv, m), face_uv, atol=1e-6)


def test_aliniar_posa_el_model_importat_com_la_peca():
    ref = trimesh.creation.box((2, 4, 6))
    imp = trimesh.creation.box((20, 40, 60))
    imp.apply_translation([100, 0, 0])
    out = uv.aliniar(imp, ref, np.eye(4), np.eye(4))
    assert np.allclose(out.extents, ref.extents) and np.allclose(out.bounds.mean(0), ref.bounds.mean(0))


def test_disseny_dades_i_rangs():
    """Les dades del selector de cares i la llista de rangs del pas Disseny."""
    import decor as dc
    from ui import disseny
    m = trimesh.creation.box((40, 30, 20))
    fr = dc.face_frames(m)
    d = disseny._dades(m, fr, [dict(cares=[0])], False)
    assert len(d["fr"]) == len(m.faces) and sorted(set(d["fr"])) == list(range(len(fr)))
    assert d["dec"][0] == 1 and sum(d["dec"]) == 1
    assert disseny._ranges([0, 1, 2, 5]) == "C1–C3, C6"


def test_pintura_capes_en_ordre():
    """Pell, grup i cara es componen en aquest ordre; el làser grava en gris i talla el negre."""
    import io
    from PIL import Image
    import decor as dc
    from ui import pintura
    m = trimesh.creation.box((40, 30, 20))
    fr = dc.face_frames(m)
    ops = [dict(nivell="cara", tipus="color", color="#00ff00", cares=[0]),
           dict(nivell="grup", tipus="color", color="#ff0000", cares=[0, 1])]   # desordenades
    png = pintura.cara(fr[0], m, None, [o for o in ops if 0 in o["cares"]], 0.0)
    im = Image.open(io.BytesIO(png)).convert("RGB")
    assert im.getpixel((im.width // 2, im.height // 2)) == (0, 255, 0)   # la cara va damunt del grup
    d = pintura.decoracio(fr, m, None, ops, 0.0, True, 20)
    assert set(d) == {0, 1} and all(s.laser == "gravar i tallar" and s.frame >= dc.CUT_MIN_FRAME
                                    for s in d.values())
    assert pintura.decoracio(fr, m, None, ops, 0.0, False, 20)[0].laser != "gravar i tallar"


def test_pintura_pell_uv():
    import io
    from PIL import Image
    import decor as dc
    from ui import pintura
    m = trimesh.creation.box((40, 30, 20))
    uvs = np.tile(np.array([[0.5, 0.5], [0.6, 0.5], [0.5, 0.6]]), (len(m.faces), 1, 1))
    tex = dc.Texture(Image.new("RGB", (16, 16), (200, 10, 10)), uvs)
    fr = dc.face_frames(m)
    png = pintura.cara(fr[0], m, tex, [dict(nivell="uv", tipus="uv", cares=[0])], 0.0)
    im = Image.open(io.BytesIO(png)).convert("RGB")
    assert im.getpixel((im.width // 2, im.height // 2)) == (200, 10, 10)


def test_disseny_arriba_al_desplegable():
    """Una imatge assignada a una cara surt a les pàgines del desplegable."""
    import io
    from PIL import Image
    import papercraft as pc
    b = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(b, "PNG")
    m = pc.scale_to(trimesh.creation.box((40, 30, 20)), 80)
    r = pc.make_papercraft(m, 12, 80, 5, "A4", False, False, 0, True,
                           decor={0: dc.DecorSpec(kind="imatge", image=b.getvalue())})
    assert sum(p.count("<image") for p in r.pages) == 1


def test_textura_uv_arriba_al_desplegable():
    """Les cares decorades amb «textura» porten la imatge de la UV a les pàgines."""
    import papercraft as pc
    from PIL import Image
    m = trimesh.creation.icosphere(2, 40)
    u = np.column_stack([(np.arctan2(m.vertices[:, 1], m.vertices[:, 0]) / np.pi + 1) / 2,
                         (m.vertices[:, 2] / 40 + 1) / 2])
    tex = dc.Texture(Image.new("RGB", (64, 64), "red"), u[m.faces])
    r = pc.make_papercraft(m, 100, 80, 5, "A4", False, False, 0, True,
                           decor={k: dc.DecorSpec(kind="textura") for k in range(5)}, texture=tex)
    assert sum(p.count("<image") for p in r.pages) >= 1


def test_colors_del_render_texturitzat():
    """Cada triangle porta el color de la capa que té damunt (la de la cara, sobre la del grup)."""
    import decor as dc
    from ui import pintura
    m = trimesh.creation.box((40, 30, 20))
    fr = dc.face_frames(m)
    ops = [dict(nivell="grup", tipus="color", color="#ff0000", cares=[0, 1]),
           dict(nivell="cara", tipus="color", color="#00ff00", cares=[0])]
    c = pintura.colors(fr, m, None, ops)
    assert c.shape == (len(m.faces), 3)
    assert (c[fr[0].faces] == (0, 255, 0)).all() and (c[fr[1].faces] == (255, 0, 0)).all()
    assert (c[fr[2].faces] == (220, 194, 154)).all()   # sense capes: color base
