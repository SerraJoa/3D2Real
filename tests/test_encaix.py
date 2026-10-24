"""Encaix: terra, paret, sostre i cantonada tallen la peça pels plans, amb o sense cara."""
import os
import sys

import numpy as np
import pytest
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ui import encaix  # noqa: E402

pytest.importorskip("manifold3d")


def test_cada_encaix_talla_pels_seus_plans():
    m = trimesh.creation.icosphere(2, 10)
    assert len(encaix.TIPUS) == 9
    for clau, _t, _i in encaix.TIPUS:
        out = encaix.talla(m, clau, encaix.desp_icona(m, clau, 20.0))
        assert out.is_watertight and out.volume < m.volume
        assert encaix.talla(m, clau, encaix.ZERO) is m   # sense moure, no es toca
    sota = encaix.talla(m, "sota1", (0, 0, -0.2 * m.extents[2], 0, 0, 0))
    assert sota.bounds[0][2] == pytest.approx(m.bounds[0][2], abs=1e-6)
    assert sota.bounds[1][2] == pytest.approx(m.bounds[1][2] - 0.2 * m.extents[2], abs=1e-6)
    c = encaix.talla(m, "lateral2", encaix.desp_icona(m, "lateral2", 20.0))
    assert c.bounds[1][0] == pytest.approx(m.bounds[1][0]) and c.bounds[1][1] == pytest.approx(m.bounds[1][1])
    # Girar la peça la fa sortir dels plans: es talla encara que no s'hagi desplaçat
    cub = trimesh.creation.box((2, 2, 2))
    assert encaix.talla(cub, "sota1", (0, 0, 0, 0, 0, 45)) is not cub


def test_deixar_buit_no_tapa():
    m = trimesh.creation.icosphere(2, 10)
    d = (0, 0, -0.2, 0, 0, 0)
    assert encaix.talla(m, "sota1", d).is_watertight
    assert not encaix.talla(m, "sota1", d, cap=False).is_watertight


def test_icona_amb_la_peca_encastada():
    m = trimesh.creation.icosphere(2, 10)
    svg = encaix.escena_svg(m, "sota3", encaix.desp_icona(m, "sota3"), width=200)
    assert svg.startswith("<svg") and svg.count("<polygon") > 50


def test_tapa_de_terra_sobreviu_a_la_reduccio_i_es_una_sola():
    import decor as dc
    import papercraft as pc
    m = trimesh.creation.icosphere(4, 10)
    desp = (0, 0, -0.3 * m.extents[2], 0, 0, 0)
    talls = encaix.plans_tallats(m, "sota1", desp)
    assert talls == [(2, 1)] and encaix.plans_tallats(m, "sota1") == []
    cut = encaix.talla(m, "sota1", desp)
    red = encaix.refa_tapa(pc.simplify(cut, 80), talls)
    assert red.is_watertight and len(red.faces) < len(cut.faces)
    zmin = red.bounds[0][2]
    plana = [i for i, f in enumerate(red.faces) if np.all(red.vertices[f][:, 2] < zmin + 1e-6)]
    assert len(plana) >= 3   # la base és plana a l'alçada del tall
    fr = dc.face_frames(red)
    base = [f for f in fr if set(f.faces) >= set(plana)]
    assert len(base) == 1   # una sola cara


def test_tapa_amb_dues_illes_no_peta():
    """Un arc tallat pel terra deixa dues illes: la tapa es fa per illa (abans, MultiPolygon)."""
    import papercraft as pc
    pota = lambda x: trimesh.creation.box((10, 10, 30), transform=trimesh.transformations.translation_matrix((x, 0, 15)))
    sostre = trimesh.creation.box((50, 10, 10), transform=trimesh.transformations.translation_matrix((0, 0, 35)))
    arc = trimesh.boolean.union([pota(-20), pota(20), sostre], engine="manifold")
    desp = (0, 0, -4, 0, 0, 0)
    talls = encaix.plans_tallats(arc, "sota1", desp)
    cut = encaix.talla(arc, "sota1", desp)
    red = encaix.refa_tapa(pc.simplify(cut, 20), talls)
    assert red.is_watertight
