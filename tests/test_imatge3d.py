import io
import json

import numpy as np
import trimesh
from PIL import Image

import imatge3d


def test_prepara_imatge_quadrada_sobre_blanc():
    im = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    im.paste((255, 0, 0, 255), (10, 5, 30, 15))
    b = io.BytesIO()
    im.save(b, "PNG")
    out = Image.open(io.BytesIO(imatge3d.prepara_imatge(b.getvalue(), 64)))
    assert out.size == (64, 64) and out.mode == "RGB"
    assert out.getpixel((0, 0)) == (255, 255, 255)
    assert out.getpixel((32, 32)) == (255, 0, 0)


def test_orienta_passa_z_amunt_a_y_amunt():
    m = trimesh.creation.box((1, 1, 4))  # llarg en Z
    r = trimesh.load(io.BytesIO(imatge3d.orienta(m.export(file_type="glb"))), file_type="glb",
                     force="mesh")
    assert np.ptp(r.vertices[:, 1]) > 3.9 and np.ptp(r.vertices[:, 2]) < 1.1


def test_workflow_te_el_placeholder_i_els_nodes_que_toquem():
    wf = json.loads(imatge3d.WORKFLOW.read_text())
    assert wf["2"]["inputs"]["image"] == "__IMAGE__"
    assert "steps" in wf["19:7"]["inputs"] and wf["10"]["class_type"] == "SaveGLB"


def test_neteja_torna_malla_estanca_i_manifold():
    a = trimesh.creation.box((1, 1, 1))
    b = trimesh.creation.box((1, 1, 1))
    b.apply_translation((0.5, 0.5, 0.5))  # dues caixes que es tallen: no manifold
    m = trimesh.util.concatenate([a, b])
    r = trimesh.load(io.BytesIO(imatge3d.neteja(m.export(file_type="glb"), 40)), file_type="glb",
                     force="mesh")
    assert r.is_watertight and (np.bincount(r.edges_unique_inverse) <= 2).all()
    assert abs(r.extents.max() - 1.5) < 0.1


def test_workflow_imatge_porta_prompt_i_estil():
    for estil, clau in (("normal", "studio"), ("low poly", "low poly")):
        wf = imatge3d._workflow_imatge("una guineu", estil, 7, 512, 8)
        text = wf["5"]["inputs"]["text"]
        assert text.startswith("una guineu") and clau in text
        assert wf["8"]["inputs"]["seed"] == 7 and wf["7"]["inputs"]["width"] == 512
        for n in wf.values():  # cap referència a un node inexistent
            for v in n["inputs"].values():
                assert not isinstance(v, list) or v[0] in wf


def test_neteja_torna_la_malla_amb_les_normals_cap_a_fora():
    import papercraft as pc
    glb = trimesh.creation.icosphere(2).export(file_type="glb")
    m = trimesh.load(io.BytesIO(imatge3d.neteja(glb)), file_type="glb", force="mesh")
    assert m.volume > 0
    rev = trimesh.creation.box((2, 2, 2))
    rev.invert()
    assert pc.clean(rev).volume > 0


def test_malla_camp_estanca_sense_placa_ni_illes_i_amb_arestes_vives():
    c = np.zeros((64, 64, 64), np.float32)
    c[16:48, 20:44, 24:40] = 1.0          # caixa (la Z del camp és l'eix 0)
    c[28:34, 28:34, 30:34] = 0.0          # buit intern: s'omple
    c[2:6, 2:6, 2:6] = 1.0                # illa: fora
    c[40, 2:-2, 2:-2] = 0.8               # placa espúria del decodificador (la vora queda buida)
    m = imatge3d.malla_camp(c)
    assert m.is_watertight and (np.bincount(m.edges_unique_inverse) <= 2).all() and m.volume > 0
    assert len(m.split(only_watertight=False)) == 1
    vox = m.extents * 64 / 2              # el costat llarg de la graella va de -1 a 1
    assert np.allclose(vox, (16, 24, 32), atol=1.5)   # (x, y, z) = (W, H, D): sense la placa
    # cares planes: gairebé tots els parells veïns són coplanaris (no s'ha difuminat)
    assert (np.degrees(m.face_adjacency_angles) < 2).mean() > 0.8


def _imatge_quadrat():
    im = Image.new("RGB", (200, 200), "white")
    im.paste((230, 120, 40), (50, 50, 150, 150))   # l'objecte: un quadrat taronja
    im.paste((30, 20, 20), (90, 80, 110, 100))     # un «ull»
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def test_pell_projectada_davant_imatge_i_darrere_neutre():
    import decor as dc
    m = trimesh.creation.box((1, 1, 0.3))          # placa: la cara gran mira cap a +Z o -Z
    glb = imatge3d.pell_projectada(m, _imatge_quadrat()).export(file_type="glb")
    mesh, tex = dc.load_textured({"m.glb": glb})
    assert tex is not None and len(mesh.faces) == len(m.faces)
    H = tex.image.height
    gran = np.abs(mesh.face_normals[:, 2]) > 0.9
    neutre = np.all(np.isclose(tex.face_uv, (0.5, 8 / H)), axis=(1, 2))
    # una cara gran veu la imatge (UV sobre el quadrat, de 50 a 150 px de 200); l'altra, neutra
    for z in (1, -1):
        costat = gran & (np.sign(mesh.face_normals[:, 2]) == z)
        if not neutre[costat].any():
            u = tex.face_uv[costat][..., 0]
            assert abs(u.min() - 0.25) < 0.03 and abs(u.max() - 0.75) < 0.03
            assert neutre[gran & ~costat].all()
            break
    else:
        raise AssertionError("cap cara gran no veu la imatge")


def test_mascara_detalls_només_la_taca_dins_la_capsa():
    im = Image.open(io.BytesIO(_imatge_quadrat())).convert("RGB")
    m = imatge3d.mascara_detalls(im, [(92 / 200, 82 / 200, 108 / 200, 98 / 200)])   # capsa justa
    assert m[90, 100] and m[85, 95]
    assert not m[60, 60] and not m[10, 10] and m.sum() <= 20 * 20 + 10
