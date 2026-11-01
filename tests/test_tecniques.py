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
