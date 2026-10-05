import itertools
import math

import numpy as np
import pytest
import trimesh
from shapely.geometry import Point, Polygon

import cares
import laminacio as lm
import laser


def _seam(normal_q, b):
    """Aresta sobre l'eix z; la placa p és el pla y=0 (normal −y) i s'estén cap a +x."""
    return cares.Seam(1, 0, 1, np.zeros(3), np.array([0, 0, 1.0]), np.array([1.0, 0, 0]),
                      np.array(b, float), np.array([0, -1.0, 0]), np.array(normal_q, float))


CONVEX_90 = dict(normal_q=[-1, 0, 0], b=[0, 1, 0])   # cantonada de caixa
CONCAVE_90 = dict(normal_q=[1, 0, 0], b=[0, -1, 0])  # racó d'una L


@pytest.mark.parametrize("kind", [CONVEX_90, CONCAVE_90])
def test_les_plaques_retirades_no_xoquen_i_al_minim(kind):
    seam = _seam(**kind)
    t = 3.0
    s = cares.min_inset(seam, t)
    A, B = cares._slabs(seam, t, s)
    assert A.intersection(B).area < 1e-6
    A, B = cares._slabs(seam, t, max(0.0, s - 0.05))
    assert s == 0 or A.intersection(B).area > 0


def test_cantonada_de_caixa_es_retira_un_gruix():
    assert cares.min_inset(_seam(**CONVEX_90), 3.0) == pytest.approx(3.0, abs=1e-3)


@pytest.mark.parametrize("kind", [CONVEX_90, CONCAVE_90])
def test_suport_en_arc_queda_per_dins_i_els_tenons_dins_les_plaques(kind):
    seam = _seam(**kind)
    t = 3.0
    s = cares.min_inset(seam, t)
    spans = cares.tenon_spans(s, 25, t)
    poly = cares.arch_bracket(seam, t, s, 25, spans, spans)
    assert poly is not None and poly.is_valid
    A, B = cares._slabs(seam, t, s)
    # El que entra a les plaques són exactament els tenons (amplada × gruix).
    tenons = sum((u1 - u0) * t for u0, u1 in spans) * 2
    assert poly.intersection(A).area + poly.intersection(B).area == pytest.approx(tenons, rel=1e-3)


@pytest.fixture(scope="module")
def caixa():
    return cares.make_faces(trimesh.creation.box((40, 30, 20)), 400, 120, 3.0, 0.0)


def test_caixa_en_sis_plaques_unides(caixa):
    s = caixa.stats
    assert s["plaques"] == 6
    assert s["grups_de_plaques"] == 1
    assert s["arestes_sense_suport"] == 0
    assert s["ranures"] > 0
    assert s["massa_grans"] == 0


def test_plaques_de_la_caixa_retirades_pel_gruix(caixa):
    plaques = sorted((p for p in caixa.parts if p.name.startswith("C")),
                     key=lambda p: -p.shape.area)
    # Cara de 120×90 retirada 3 mm a cada costat → 114×84, menys les ranures.
    gran = plaques[0].shape
    assert Polygon(gran.exterior).area == pytest.approx(114 * 84, rel=1e-3)
    assert len(gran.interiors) > 0


def test_espai_entre_cares_retira_mes(caixa):
    amb = cares.make_faces(trimesh.creation.box((40, 30, 20)), 400, 120, 3.0, 4.0)
    area = lambda r: sum(Polygon(p.shape.exterior).area for p in r.parts if p.name.startswith("C"))
    assert area(amb) < area(caixa)


def test_suports_enganxats_sense_ranures():
    r = cares.make_faces(trimesh.creation.box((40, 30, 20)), 400, 120, 3.0, 0.0, joint="cola")
    assert r.stats["ranures"] == 0
    assert r.stats["suports"] > 0


def test_suports_d_una_placa_no_es_toquen(caixa):
    for p in caixa.parts:
        if not p.name.startswith("C"):
            continue
        rects = [Polygon(e) for e in p.engraves if len(e) >= 4]
        for a, b in itertools.combinations(rects, 2):
            assert not a.intersects(b)


def test_peces_de_planxa_no_es_toquen(caixa):
    for grup in caixa.groups:
        for a, b in itertools.combinations([p.shape for p in grup], 2):
            assert a.distance(b) >= laser.PART_GAP - 0.2


# ---------------------------------------------------------------- laminació

def test_seccio_d_una_caixa():
    m = trimesh.creation.box((40, 30, 20))
    assert lm.slice_at(m, 0.0).area == pytest.approx(1200, rel=1e-6)


def test_seccio_amb_forat():
    m = trimesh.creation.torus(30, 10, major_sections=32, minor_sections=16)
    g = lm.slice_at(m, 0.0)
    assert len(g.interiors) == 1 if g.geom_type == "Polygon" else False


@pytest.fixture(scope="module")
def capes():
    return lm.make_layers(trimesh.creation.box((40, 30, 20)), 400, 60, 3.0, 5.0)


def test_capes_del_gruix_del_material(capes):
    assert capes.stats["capes"] == 10      # 30 mm d'alçada / 3 mm
    assert capes.stats["peces"] == 10


def test_columnes_alineades_a_totes_les_capes(capes):
    assert capes.stats["peces_amb_una_columna"] == 0
    assert capes.stats["peces_sense_columna"] == 0
    for p in capes.parts:
        assert len(p.shape.interiors) >= lm.COLUMNS_PER_PIECE
        for hole in p.shape.interiors:
            assert Polygon(hole).area == pytest.approx(math.pi * 2.6 ** 2, rel=0.02)


def test_columnes_lluny_de_les_vores_i_entre_elles():
    m = trimesh.creation.box((40, 30, 20))
    layers = [[lm.slice_at(m, z)] for z in (-5, 0, 5)]
    cols = lm.place_columns(layers, 5.0)
    assert len(cols) >= 2
    for x, y, a, b in cols:
        assert layers[0][0].buffer(-(2.6 + lm.COLUMN_WALL - 1e-6)).contains(Point(x, y))
    for (x1, y1, *_), (x2, y2, *_) in itertools.combinations(cols, 2):
        assert math.hypot(x1 - x2, y1 - y2) >= lm.COLUMN_SEP * 5.0 - 1e-6


def test_marques_de_cada_capa(capes):
    for p in capes.parts:
        assert any(t.startswith("L") for _, t, _ in p.labels)
        assert len(p.engraves) >= 2  # com a mínim, la fletxa d'orientació


def test_esfera_marca_el_solapament_a_les_dues_meitats():
    r = lm.make_layers(trimesh.creation.icosphere(2, radius=30), 400, 60, 3.0, 4.0)
    for p in r.parts:
        # A cada capa hi ha el contorn de la de sobre o el de la de sota (o tots dos).
        assert len(p.engraves) > 2 or p.name in ("L1", f"L{r.stats['capes']}")


def test_llista_de_tiges(capes):
    assert any("columna 1" in n for n in capes.notes)
    assert any("llargada 30 mm" in n for n in capes.notes)
