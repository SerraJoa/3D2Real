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
