import io

import numpy as np
import pytest
import trimesh
from PIL import Image, ImageDraw
from shapely.geometry import Polygon

import cares
import decor as dc
import papercraft as pc


def _png(size=(120, 80)):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    d.ellipse((20, 10, 100, 70), fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _box():
    return pc.scale_to(pc.clean(trimesh.creation.box((40, 30, 20))), 60)


def test_cares_numerades_com_les_plaques_i_amb_l_amunt_del_model():
    m = _box()
    frames = dc.face_frames(m)
    assert len(frames) == 6
    assert sum(f.shape.area for f in frames) == pytest.approx(m.area, rel=1e-6)
    for f in frames:
        assert np.cross(f.u, f.v) @ f.normal == pytest.approx(1.0)
        if abs(f.normal[2]) < 0.5:          # cares verticals: amunt = amunt del model
            assert f.v[2] == pytest.approx(1.0)


@pytest.mark.parametrize("pattern", dc.PATTERNS)
def test_patrons_dins_del_marc(pattern):
    fr = dc.face_frames(_box())[0]
    spec = dc.DecorSpec(kind="patró", pattern=pattern, frame=4.0, text="Hola")
    src = dc.build_source(fr, spec)
    assert src.clip.area == pytest.approx(fr.shape.buffer(-4.0).area)
    if pattern != "text":
        assert src.svg
    if src.holes is not None and not src.holes.is_empty:
        assert src.holes.difference(src.clip.buffer(1e-6)).area < 1e-6


def test_imatge_fosca_es_converteix_en_forat():
    fr = dc.face_frames(_box())[0]
    src = dc.build_source(fr, dc.DecorSpec(kind="imatge", image=_png(), fit="encabir",
                                           threshold=128))
    assert src.images
    assert src.holes.area > 0.2 * src.clip.area   # l'el·lipse negra


def test_desplegable_amb_imatge_i_marc():
    decor = {0: dc.DecorSpec(kind="imatge", image=_png(), frame=3.0)}
    r = pc.make_papercraft(trimesh.creation.box((40, 30, 20)), 400, 60, decor=decor)
    svg = "".join(r.pages)
    assert "<image" in svg and "clipPath" in svg
    ops = [op for p in r.pieces for op in p.decor]
    frame = dc.face_frames(r.mesh)[0]
    assert len(ops) == len(frame.faces)
    # Amb marc, el que es pinta és més petit que la cara.
    assert sum(op.clip.area for op in ops) < frame.shape.area


def _textured_files(tmp_path):
    m = trimesh.creation.box((40, 30, 20))
    m = trimesh.Trimesh(m.vertices[m.faces].reshape(-1, 3), np.arange(36).reshape(-1, 3),
                        process=False)
    uv = np.tile([[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]], (12, 1))
    img = Image.new("RGB", (64, 64), (200, 30, 30))
    m.visual = trimesh.visual.TextureVisuals(uv=uv, image=img)
    obj, extra = trimesh.exchange.obj.export_obj(m, include_texture=True, return_texture=True)
    files = {"model.obj": obj.encode()}
    files.update(extra)
    return files


def test_textura_importada_es_porta_als_triangles(tmp_path):
    mesh, tex = dc.load_textured(_textured_files(tmp_path))
    assert tex is not None and tex.face_uv.shape == (12, 3, 2)
    m, t2 = dc.prepare(mesh, 400, 60, tex)
    assert t2.face_uv.shape == (len(m.faces), 3, 2)
    # Sense simplificar, cada triangle recupera les UV del seu triangle original.
    assert np.allclose(np.sort(t2.face_uv.reshape(-1, 2), axis=0)[[0, -1]],
                       [[0.1, 0.1], [0.9, 0.9]], atol=1e-6)
    n = len(dc.face_frames(m))
    r = pc.make_papercraft(mesh, 400, 60, decor={k: dc.DecorSpec(kind="textura") for k in range(n)},
                           texture=tex)
    assert 'href="#tex"' in "".join(r.pages)


def test_laser_gravar_posa_la_placa_cara_amunt():
    decor = {2: dc.DecorSpec(kind="patró", pattern="text", text="Hola", laser="gravar")}
    r = cares.make_faces(trimesh.creation.box((40, 30, 20)), 400, 120, 3.0, decor=decor)
    plate = next(p for p in r.parts if p.name == "C3")
    assert plate.decor and plate.guides and not plate.engraves
    assert "C3" in "".join(r.notes)


def test_laser_tallar_deixa_marc_i_respecta_ranures():
    decor = {1: dc.DecorSpec(kind="patró", pattern="hexàgons", laser="tallar", spacing=10,
                             width=2, frame=0.0)}
    sense = cares.make_faces(trimesh.creation.box((40, 30, 20)), 400, 120, 3.0)
    amb = cares.make_faces(trimesh.creation.box((40, 30, 20)), 400, 120, 3.0, decor=decor)
    assert amb.stats["forats_decoratius"] > 0
    a = next(p for p in sense.parts if p.name == "C2").shape
    b = next(p for p in amb.parts if p.name == "C2").shape
    assert b.area < a.area
    slots = [Polygon(h) for h in a.interiors]
    new = [Polygon(h) for h in b.interiors if not any(Polygon(h).equals_exact(s, 1e-3) for s in slots)]
    assert new
    outer = Polygon(b.exterior)
    for h in new:
        assert h.distance(outer.exterior) >= dc.CUT_MIN_FRAME - 0.01   # el marc mínim
        assert all(h.distance(s) >= 2.0 - 0.01 for s in slots)        # lluny de les ranures
