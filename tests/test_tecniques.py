from pathlib import Path

import pytest
from shapely.geometry import Polygon

import tecniques
from etiquetes import Biblioteca
from parts import Part

BIB = Biblioteca.carrega(Path(__file__).resolve().parent.parent / "biblioteca")


def _caixa(**p):
    return Part("f", "caixa_5_cares", params=dict(amplada=20, alcada=30, profunditat=8, **p))


def test_caixa_es_una_sola_peca_amb_la_creu_i_solapes():
    (peca,) = tecniques.fabrica(_caixa(solapa=5))
    assert isinstance(peca.contorn, Polygon) and peca.contorn.is_valid
    creu = 20 * 30 + 2 * 8 * 30 + 2 * 20 * 8
    assert peca.contorn.area > creu                       # solapes
    assert len(peca.plecs) == 4                           # perímetre del fons
    assert peca.contorn.bounds[0] <= -8 and peca.contorn.bounds[2] >= 28


def test_caixa_amb_brida_afegeix_solapes_a_la_vora_oberta():
    (sense,) = tecniques.fabrica(_caixa(solapa=5, brida=0))
    (amb,) = tecniques.fabrica(_caixa(solapa=5, brida=4))
    assert amb.contorn.area > sense.contorn.area
    assert amb.contorn.is_valid and isinstance(amb.contorn, Polygon)
    assert any("darrere" in n for n in amb.notes) and not any("darrere" in n for n in sense.notes)


def test_mides_no_positives_son_error():
    with pytest.raises(ValueError, match="positives"):
        tecniques.fabrica(Part("f", "caixa_5_cares", params=dict(amplada=20, alcada=30, profunditat=0)))


def test_tecnica_desconeguda():
    with pytest.raises(ValueError, match="Cap tècnica"):
        tecniques.fabrica(Part("x", "cupula"))


def test_de_l_etiqueta_a_les_peces():
    part = BIB.get("finestra_quadrada_caixa5").crea_part("fin1", "paper", dict(profunditat=12),
                                                          ancoratge="nau")
    (peca,) = tecniques.fabrica(part)
    assert peca.nom == "fin1" and part.params["brida"] == 4     # model de paper
    assert peca.contorn.bounds[0] < -12                          # profunditat 12


def _p(tecnica, **p):
    return Part("e", tecnica, params=dict(amplada=20, alcada=30, **p))


def test_forat_no_te_peces_pero_retalla_el_mur():
    p = _p("forat", x=10, y=5)
    assert tecniques.fabrica(p) == []
    (t,) = tecniques.talls(p)
    assert t.bounds == (10, 5, 30, 35)


def test_sortint_no_retalla_i_te_brida():
    p = _p("sortint", profunditat=8)
    assert tecniques.talls(p) == []
    (peca,) = tecniques.fabrica(p)
    (caixa,) = tecniques.fabrica(Part("e", "caixa_5_cares", params=dict(amplada=20, alcada=30, profunditat=8, brida=0)))
    assert peca.contorn.area > caixa.contorn.area
    assert any("pel davant" in n for n in peca.notes)


def test_enfonsat_i_caixa_retallen_el_mur_igual():
    for t in ("enfonsat", "caixa_5_cares"):
        (c,) = tecniques.talls(_p(t, profunditat=8, x=1, y=2))
        assert c.bounds == (1, 2, 21, 32)


def test_frontissa_es_una_fulla_amb_tira_i_un_plec():
    p = _p("retall_frontissa", frontissa=5)
    (peca,) = tecniques.fabrica(p)
    assert peca.contorn.bounds == pytest.approx((-5, 0, 20, 30))
    assert peca.plecs == [((0, 0), (0, 30), "vall")]
    assert peca.contorn.area == pytest.approx(20 * 30 + 5 * 30)
    assert len(tecniques.talls(p)) == 1


def test_talls_amb_forma_no_implementada():
    with pytest.raises(ValueError, match="forma"):
        tecniques.talls(Part("e", "forat", params=dict(amplada=20, alcada=30, forma="arc")))


def test_tota_la_biblioteca_del_repo_es_fabrica():
    for e in BIB:
        part = e.crea_part(e.id, "paper")
        tecniques.fabrica(part)
        tecniques.talls(part)


from parts import PlaFabricacio  # noqa: E402


def _nau(**p):
    return Part("nau", "cos", params=dict(amplada=100, profunditat=40, alcada=50, **p))


def test_cos_dona_parets_i_base():
    parets, base = tecniques.fabrica(_nau())
    assert parets.meta["parets"] == [(0, 100), (100, 140), (140, 240), (240, 280)]
    assert len(parets.plecs) == 3 and base.contorn.area == pytest.approx(4000)
    sense = tecniques.fabrica(_nau(sense_base=True))
    assert len(sense) == 1 and sense[0].contorn.area < parets.contorn.area


def test_cos_amb_base_de_planta():
    tri = tecniques.fabrica(Part("t", "cos", params=dict(base=[(0, 0), (60, 0), (30, 40)], alcada=20)))
    assert len(tri[0].meta["parets"]) == 3
    with pytest.raises(ValueError, match="3 punts"):
        tecniques.fabrica(Part("t", "cos", params=dict(base=[(0, 0), (1, 1)], alcada=20)))
    with pytest.raises(ValueError, match="vàlid"):
        tecniques.fabrica(Part("t", "cos", params=dict(base=[(0, 0), (2, 2), (2, 0), (0, 2)], alcada=20)))


def test_columna_te_tira_i_dues_tapes():
    tira, dalt, baix = tecniques.fabrica(Part("c", "columna", params=dict(diametre=10, alcada=40, costats=8)))
    assert len(tira.plecs) == 7
    assert dalt.contorn.area == pytest.approx(baix.contorn.area) and dalt.contorn.area > 0
    with pytest.raises(ValueError):
        tecniques.fabrica(Part("c", "columna", params=dict(diametre=10, alcada=40, costats=2)))


def _pla_amb_finestra(**fin):
    return PlaFabricacio([
        _nau(),
        Part("fin", "forat", ancoratge="nau", params=dict(amplada=20, alcada=15, x=10, y=20, **fin)),
    ])


def test_fabrica_pla_retalla_la_paret_del_pare():
    sense = tecniques.fabrica_pla(PlaFabricacio([_nau()]))["nau"][0]
    peces = tecniques.fabrica_pla(_pla_amb_finestra(cara=2))
    parets = peces["nau"][0]
    assert parets.contorn.area == pytest.approx(sense.contorn.area - 20 * 15)
    assert len(parets.contorn.interiors) == 1
    assert parets.contorn.interiors[0].bounds[0] == pytest.approx(140 + 10)   # paret 2 comença a x=140
    assert peces["fin"] == [] and peces["nau"][1].nom == "nau_base"


def test_fabrica_pla_errors():
    with pytest.raises(ValueError, match="no té la paret"):
        tecniques.fabrica_pla(_pla_amb_finestra(cara=9))
    with pytest.raises(ValueError, match="no cap"):
        tecniques.fabrica_pla(PlaFabricacio([_nau(), Part("g", "forat", ancoratge="nau",
                              params=dict(amplada=200, alcada=15))]))
    with pytest.raises(ValueError, match="no en té"):
        tecniques.fabrica_pla(PlaFabricacio([Part("c", "columna", params=dict(diametre=10, alcada=40)),
                              Part("g", "forat", ancoratge="c", params=dict(amplada=2, alcada=2))]))


def test_pla_sencer_amb_finestra_enfonsada_i_porta_mobil():
    pla = PlaFabricacio([
        _nau(),
        BIB.get("finestra_quadrada_caixa5").crea_part("fin", "paper", ancoratge="nau",
                                                       posicio=dict(x=10, y=20, cara=0)),
        BIB.get("porta_quadrada_frontissa").crea_part("porta", "paper", ancoratge="nau",
                                                       posicio=dict(x=60, y=0, cara=0)),
    ])
    peces = tecniques.fabrica_pla(pla)
    assert len(peces["nau"][0].contorn.interiors) == 1       # la porta toca el terra: osca, no forat
    assert [q.nom for q in peces["fin"]] == ["fin"] and [q.nom for q in peces["porta"]] == ["porta"]
    assert peces["nau"][0].contorn.area < tecniques.fabrica(_nau())[0].contorn.area
