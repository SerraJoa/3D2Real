import json
from pathlib import Path

import pytest

from etiquetes import Biblioteca, Etiqueta, Mida, ModelAplicacio
from parts import PlaFabricacio

BIBLIOTECA = Path(__file__).resolve().parent.parent / "biblioteca"


def _finestra(**k):
    base = dict(id="f1", element="finestra", forma="quadrada", espai="superficie", tipus="forat",
                mides={"amplada": Mida(20, 2, 100), "alcada": Mida(30, 2, 100)},
                models={"*": ModelAplicacio(muntatge=["retalla"]),
                        "paper": ModelAplicacio(params={"marge": 1.0, "amplada": 25},
                                                muntatge=["cúter"])})
    base.update(k)
    return Etiqueta(**base)


def test_validacions_de_l_etiqueta():
    with pytest.raises(ValueError, match="Espai"):
        _finestra(espai="aire")
    with pytest.raises(ValueError, match="segona paret"):
        _finestra(segona_paret=True)
    _finestra(espai="planta", segona_paret=True)
    with pytest.raises(ValueError, match="«forma»"):
        _finestra(forma="")


def test_mida_fora_de_rang():
    with pytest.raises(ValueError):
        Mida(200, 2, 100)
    with pytest.raises(ValueError):
        Mida(5, 10, 2)


def test_resol_aplica_defecte_model_i_mides_en_aquest_ordre():
    e = _finestra()
    assert e.resol() == dict(amplada=20, alcada=30)
    assert e.resol(desplegable="paper") == dict(amplada=25, alcada=30, marge=1.0)
    assert e.resol(dict(amplada=40), "paper") == dict(amplada=40, alcada=30, marge=1.0)


def test_resol_rebutja_mides_alienes_i_fora_de_rang():
    e = _finestra()
    with pytest.raises(ValueError, match="no té la mida"):
        e.resol(dict(profunditat=3))
    with pytest.raises(ValueError, match="fora del rang"):
        e.resol(dict(alcada=1))


def test_model_amb_fallback_al_base():
    e = _finestra()
    assert e.model("paper").muntatge == ["cúter"]
    assert e.model("cnc").muntatge == ["retalla"]
    assert _finestra(models={}).model("3d").muntatge == []


def test_crea_part_porta_tecnica_params_i_muntatge():
    p = _finestra().crea_part("finestra_1", "paper", dict(alcada=50), ancoratge="nau",
                              origen="detectat", confianca=0.8)
    assert (p.tecnica, p.ancoratge, p.origen, p.confianca) == ("forat", "nau", "detectat", 0.8)
    assert p.params["alcada"] == 50 and p.params["amplada"] == 25
    assert p.params["etiqueta"] == "f1" and p.params["muntatge"] == ["cúter"]
    pla = PlaFabricacio([p])
    assert json.loads(json.dumps(pla.a_dict()))["parts"][0]["params"]["forma"] == "quadrada"


def test_biblioteca_cerca_i_duplicats():
    bib = Biblioteca([_finestra(), _finestra(id="f2", forma="arc")])
    assert [e.id for e in bib.cerca(element="finestra", forma="arc")] == ["f2"]
    assert len(bib.cerca(tipus="forat")) == 2
    with pytest.raises(ValueError, match="Ja hi ha"):
        bib.afegeix(_finestra())
    with pytest.raises(ValueError, match="Eix"):
        bib.cerca(color="vermell")
    with pytest.raises(KeyError, match="cap etiqueta"):
        bib.get("x")


def test_carrega_diu_quin_fitxer_falla(tmp_path):
    (tmp_path / "bo.json").write_text(json.dumps(
        dict(versio=1, id="a", element="e", forma="f", espai="maqueta", tipus="t")))
    assert len(Biblioteca.carrega(tmp_path)) == 1
    (tmp_path / "dolent.json").write_text(json.dumps(dict(versio=1, id="b")))
    with pytest.raises(ValueError, match="dolent.json"):
        Biblioteca.carrega(tmp_path)
    (tmp_path / "dolent.json").write_text("{no és json")
    with pytest.raises(ValueError, match="dolent.json"):
        Biblioteca.carrega(tmp_path)
    (tmp_path / "dolent.json").write_text(json.dumps(dict(versio=2)))
    with pytest.raises(ValueError, match="Versió"):
        Biblioteca.carrega(tmp_path)


def test_la_biblioteca_del_repo_es_valida():
    bib = Biblioteca.carrega(BIBLIOTECA)
    f = bib.get("finestra_quadrada_forat")
    p = f.crea_part("f", "paper", dict(amplada=15))
    assert p.params["amplada"] == 15 and p.params["marge"] == 1.0
