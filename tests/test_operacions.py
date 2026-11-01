import pytest
from shapely.geometry import Polygon, box

import operacions as op


def test_solapa_surt_cap_a_fora_i_amb_l_alcada_demanada():
    r = op.rectangle("c", 40, 20)
    s = op.solapa(r.contorn, (0, 0), (40, 0), 8)
    assert s.bounds == pytest.approx((0, -8, 40, 0))
    assert s.intersection(r.contorn).area == pytest.approx(0)
    assert s.area < 40 * 8   # trapezi, no rectangle


def test_solapa_cap_a_fora_per_qualsevol_costat():
    r = op.rectangle("c", 40, 20)
    assert op.solapa(r.contorn, (40, 0), (40, 20), 5).bounds[2] == pytest.approx(45)
    assert op.solapa(r.contorn, (40, 20), (0, 20), 5).bounds[3] == pytest.approx(25)
    assert op.solapa(r.contorn, (0, 20), (0, 0), 5).bounds[0] == pytest.approx(-5)


def test_solapa_en_aresta_curta_no_es_degenera():
    r = op.rectangle("c", 4, 20)
    s = op.solapa(r.contorn, (0, 0), (4, 0), 8)
    assert s.is_valid and s.area > 0


def test_solapa_valida():
    r = op.rectangle("c", 40, 20)
    with pytest.raises(ValueError, match="alçada"):
        op.solapa(r.contorn, (0, 0), (40, 0), 0)
    with pytest.raises(ValueError, match="vora"):
        op.solapa(r.contorn, (5, 5), (30, 5), 4)


def test_afegeix_solapes_dona_una_peca():
    r = op.rectangle("c", 40, 20)
    p = op.afegeix_solapes(r, [((0, 0), (40, 0)), ((40, 0), (40, 20))], 6)
    assert isinstance(p.contorn, Polygon) and p.contorn.area > r.contorn.area
    assert r.contorn.area == 800                      # l'original no es toca
    assert p.notes[-1].startswith("2 solapes")


def test_retalla_forat_i_osca():
    r = op.rectangle("c", 40, 20)
    forat = op.retalla(r, box(10, 5, 20, 15))
    assert len(forat.contorn.interiors) == 1 and forat.contorn.area == pytest.approx(700)
    osca = op.retalla(r, box(-1, 5, 10, 15))
    assert len(osca.contorn.interiors) == 0 and osca.contorn.area == pytest.approx(800 - 100)


def test_retalla_que_parteix_la_peca_es_error():
    with pytest.raises(ValueError, match="parteix"):
        op.retalla(op.rectangle("c", 40, 20), box(15, -1, 25, 21))


def test_plega():
    r = op.rectangle("c", 40, 20)
    p = op.plega(r, (20, 0), (20, 20), op.MUNTANYA)
    assert p.plecs == [((20, 0), (20, 20), "muntanya")] and r.plecs == []
    with pytest.raises(ValueError, match="surt"):
        op.plega(r, (20, 0), (20, 30))
    with pytest.raises(ValueError, match="desconegut"):
        op.plega(r, (20, 0), (20, 20), "zig")


def test_trasllada_mou_contorn_i_plecs():
    p = op.trasllada(op.plega(op.rectangle("c", 40, 20), (20, 0), (20, 20)), 100, 50)
    assert p.contorn.bounds == pytest.approx((100, 50, 140, 70))
    assert p.plecs[0][0] == (120, 50)
