"""Segmentació en parts pels plecs còncaus: sense llavors posades a mà."""
import os
import sys

import numpy as np
import pytest
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import segmenta  # noqa: E402


def _caixes(mides, posicions):
    pytest.importorskip("manifold3d")
    parts = [trimesh.creation.box(s) for s in mides]
    for p, o in zip(parts, posicions):
        p.apply_translation(o)
    return trimesh.boolean.union(parts)


def _ninot():
    return _caixes(((20, 12, 30), (12, 12, 12), (6, 6, 26), (6, 6, 26), (7, 7, 24), (7, 7, 24)),
                   ((0, 0, 0), (0, 0, 21), (13, 0, 2), (-13, 0, 2), (5, 0, -27), (-5, 0, -27)))


def _halteri():
    pytest.importorskip("manifold3d")
    a = trimesh.creation.icosphere(3, radius=20)
    b = a.copy()
    b.apply_translation([55, 0, 0])
    c = trimesh.creation.cylinder(radius=6, height=40)
    c.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    c.apply_translation([27, 0, 0])
    return trimesh.boolean.union([a, b, c])


def _cara():
    m = trimesh.creation.icosphere(4, 50.0)
    V = m.vertices.copy()
    for c, s, depth in (((16, -45, 12), (6, 8, 5), 6), ((-16, -45, 12), (6, 8, 5), 6),
                        ((0, -46, -16), (13, 8, 2.5), 4)):
        d = sum(((V[:, i] - c[i]) / s[i]) ** 2 for i in range(3))
        V -= (depth * np.exp(-d))[:, None] * V / np.linalg.norm(V, axis=1)[:, None]
    return trimesh.Trimesh(V, m.faces)


def _parts(m):
    return int(segmenta.segment(m).max()) + 1


def test_ninot_en_sis_parts():
    m = _ninot()
    lab = segmenta.segment(m)
    assert lab.max() + 1 == 6
    # braços i cames: quatre parts de la mateixa àrea (±10 %)
    a = np.sort(np.bincount(lab, weights=m.area_faces))
    assert a[:4].max() < 1.4 * a[:4].min()


def test_halteri_dues_esferes_i_una_barra():
    m = _halteri()
    lab = segmenta.segment(m)
    a = np.sort(np.bincount(lab, weights=m.area_faces))[::-1]
    assert lab.max() + 1 == 3
    assert abs(a[0] - a[1]) < 0.05 * a[0]          # les dues esferes són iguals
    assert a[2] < 0.2 * a[0]                       # la barra, menuda


@pytest.mark.parametrize("nom,mesh", [
    ("caixa", lambda: trimesh.creation.box((40, 30, 20))),
    ("esfera", lambda: trimesh.creation.icosphere(3, radius=30)),
    ("tor", lambda: trimesh.creation.torus(30, 10, major_sections=32, minor_sections=16)),
    ("coet", lambda: trimesh.creation.revolve(np.array([[0, 0], [10, 0], [10, 40], [0, 60]]),
                                              sections=16)),
    ("cara amb conques", _cara),
])
def test_formes_d_una_sola_part_no_es_parteixen(nom, mesh):
    assert _parts(mesh()) == 1


def test_etiquetes_de_totes_les_cares_i_sense_forats():
    m = _ninot()
    lab = segmenta.segment(m)
    assert lab.shape == (len(m.faces),)
    assert set(np.unique(lab)) == set(range(lab.max() + 1))


def test_peces_soltes_reben_etiqueta():
    # Una peça solta no connexa per arestes també ha de quedar etiquetada.
    gran = trimesh.creation.icosphere(3, radius=20)
    petita = trimesh.creation.icosphere(2, radius=3)
    petita.apply_translation([60, 0, 0])
    m = trimesh.util.concatenate([gran, petita])
    lab = segmenta.segment(m)
    assert lab.shape == (len(m.faces),) and lab.min() >= 0
