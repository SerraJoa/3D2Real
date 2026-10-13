"""Reducció que respecta la forma: simetria exacta, detalls conservats i orientació."""
import os
import sys

import numpy as np
import pytest
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import papercraft as pc  # noqa: E402
import reduccio as rd  # noqa: E402


def cara():
    """Esfera amb dues conques d'ulls i una boca, simètrica respecte del pla x = 0."""
    m = trimesh.creation.icosphere(4, 50.0)
    V = m.vertices.copy()
    for c, s, depth in (((16, -45, 12), (6, 8, 5), 6), ((-16, -45, 12), (6, 8, 5), 6),
                        ((0, -46, -16), (13, 8, 2.5), 4)):
        d = sum(((V[:, i] - c[i]) / s[i]) ** 2 for i in range(3))
        V -= (depth * np.exp(-d))[:, None] * V / np.linalg.norm(V, axis=1)[:, None]
    return trimesh.Trimesh(V, m.faces)


def surface_dist(m, pts):
    s, _ = trimesh.sample.sample_surface(m, 60000, seed=3)
    return rd._nearest(pts, s)


@pytest.fixture(scope="module")
def models():
    m = cara()
    return m, pc.simplify(m, 300), rd.reduce(m, 300, symmetry="auto")


def test_troba_el_pla_de_simetria(models):
    m, _, _ = models
    c, n, err = rd.find_symmetry(m)
    assert abs(abs(n[0]) - 1) < 1e-6 and abs(c[0]) < 0.5 and err < rd.SYM_TOL
    # Un model sense simetria no en té.
    # Un sol bony té un pla de simetria (el que passa pel centre i pel bony); amb els ulls i
    # la boca ja no n'hi ha cap.
    V = m.vertices.copy()
    d = ((V - [30, 20, 25]) ** 2).sum(1) / 15 ** 2
    V += (12 * np.exp(-d))[:, None] * V / np.linalg.norm(V, axis=1)[:, None]
    assert rd.find_symmetry(trimesh.Trimesh(V, m.faces)) is None


def test_reduccio_simetrica_i_tancada(models):
    m, rapida, (red, info) = models
    assert info["simetria"] is not None
    assert abs(len(red.faces) - 300) <= 10
    assert red.is_watertight
    c, n = np.array(info["simetria"]["point"]), np.array(info["simetria"]["n"])
    mir = red.vertices - 2 * ((red.vertices - c) @ n)[:, None] * n
    assert rd._nearest(mir, red.vertices).max() < 1e-6        # exactament simètrica
    assert rd._nearest(rapida.vertices * np.array([-1.0, 1, 1]), rapida.vertices).max() > 1.0


def test_detalls_amb_mes_vertexs_i_iguals(models):
    """Sense simetria: els ulls i la boca reben més vèrtexs que amb la reducció ràpida, i els
    dos ulls (equivalents) en reben els mateixos."""
    m, rapida, _ = models
    red, info = rd.reduce(m, 300)
    assert info["simetria"] is None  # per defecte no s'imposa cap simetria

    def count(r, cx, cz, rx, rz):
        W = r.vertices
        return int(((np.abs(W[:, 0] - cx) < rx) & (np.abs(W[:, 2] - cz) < rz) & (W[:, 1] < -30)).sum())
    ull_d, ull_e = count(red, 16, 12, 7, 7), count(red, -16, 12, 7, 7)
    assert abs(ull_d - ull_e) <= 1
    assert ull_d + ull_e > count(rapida, 16, 12, 7, 7) + count(rapida, -16, 12, 7, 7)
    assert count(red, 0, -16, 13, 4) > count(rapida, 0, -16, 13, 4)


def test_les_cares_planes_es_treuen_primer():
    """Una caixa molt triangulada es queda amb els 12 triangles de les seves 6 cares."""
    m = trimesh.creation.box((40, 30, 20))
    m = m.subdivide().subdivide().subdivide()
    red, info = rd.reduce(m, 12)
    # Amb 12 cares la caixa no cap simètrica (en caldrien 20): es fa sense simetria.
    assert info["simetria"] is None
    assert len(red.faces) == 12 and red.is_watertight
    assert np.allclose(np.sort(np.abs(red.vertices), axis=0)[-1], [20, 15, 10], atol=1e-6)


def test_branques_fan_servir_la_reduccio():
    m = cara()
    red, _ = rd.reduce(m, 200)
    m.metadata["reduccio"] = (200, red)
    out = pc.simplify(pc.clean(m), 200)
    assert len(out.faces) == len(red.faces) and np.allclose(out.vertices, red.vertices)


def test_orientacio():
    for up, v in pc.UPS.items():
        assert np.allclose(pc.orientation_matrix(up)[:3, :3] @ v, [0, 0, 1])
    assert np.allclose(pc.orientation_matrix("+Z", 90)[:3, :3] @ [1, 0, 0], [0, 1, 0])


def test_harmonitzacio_fa_triangles_mes_regulars():
    """Menys triangles prims i la mateixa forma (la desviació gairebé no canvia)."""
    m = cara()
    crua, _ = rd.reduce(m, 300, harmonize_=False)
    harm, info = rd.reduce(m, 300)
    assert info.get("harmonitzada") and harm.is_watertight
    assert len(harm.faces) == len(crua.faces)
    assert np.median(rd.min_angles(harm)) > np.median(rd.min_angles(crua)) + 2
    diag = np.linalg.norm(m.extents)
    assert rd.deviation(m, harm) < rd.deviation(m, crua) + 0.003 * diag
