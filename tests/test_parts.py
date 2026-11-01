import json

import pytest

from parts import Part, PlaFabricacio


def _castell():
    return PlaFabricacio([
        Part("nau", "cos"),
        Part("torre", "torre", ancoratge="nau"),
        Part("teulada", "teulada", ancoratge="nau"),
        Part("cupula", "cupula", ancoratge="torre", origen="detectat", confianca=0.5),
    ])


def test_part_valida_els_camps():
    with pytest.raises(ValueError):
        Part("", "cos")
    with pytest.raises(ValueError):
        Part("a", "cos", origen="ia")
    with pytest.raises(ValueError):
        Part("a", "cos", confianca=1.5)
    with pytest.raises(ValueError):
        Part("a", "cos", ancoratge="a")


def test_noms_unics():
    pla = PlaFabricacio([Part("nau", "cos")])
    with pytest.raises(ValueError):
        pla.afegeix(Part("nau", "torre"))


def test_ordre_de_muntatge_posa_cada_part_despres_del_seu_ancoratge():
    pla = _castell()
    assert [p.nom for p in pla.ordre_muntatge()] == ["nau", "torre", "cupula", "teulada"]


def test_ordre_de_muntatge_no_depen_de_l_ordre_d_entrada():
    pla = PlaFabricacio([Part("cupula", "cupula", ancoratge="torre"),
                         Part("torre", "torre", ancoratge="nau"),
                         Part("nau", "cos")])
    assert [p.nom for p in pla.ordre_muntatge()] == ["nau", "torre", "cupula"]


def test_ancoratge_inexistent_i_cicle():
    pla = PlaFabricacio([Part("a", "cos", ancoratge="x")])
    with pytest.raises(ValueError, match="no existeix"):
        pla.comprova()
    cicle = PlaFabricacio([Part("a", "cos", ancoratge="b"), Part("b", "cos", ancoratge="a")])
    with pytest.raises(ValueError, match="Cicle"):
        cicle.ordre_muntatge()


def test_treu_emporta_els_descendents():
    pla = _castell()
    pla.treu("torre")
    assert [p.nom for p in pla] == ["nau", "teulada"]


def test_dubtoses():
    assert [p.nom for p in _castell().dubtoses()] == ["cupula"]


def test_json_d_anada_i_tornada():
    pla = _castell()
    pla.part("nau").cares = [0, 1, 2]
    pla.part("nau").params = {"alcada": 3.5}
    de_nou = PlaFabricacio.de_dict(json.loads(json.dumps(pla.a_dict())))
    assert de_nou.a_dict() == pla.a_dict()
    assert de_nou.part("nau").cares == [0, 1, 2]


def test_versio_desconeguda():
    with pytest.raises(ValueError, match="Versió"):
        PlaFabricacio.de_dict(dict(versio=99, parts=[]))
