import itertools
from collections import Counter

import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon

import papercraft as pc

MESHES = {
    "caixa": lambda: trimesh.creation.box((40, 30, 20)),
    "esfera": lambda: trimesh.creation.icosphere(2, radius=30),
    "caixa_densa": lambda: trimesh.creation.box((40, 30, 20)).subdivide().subdivide(),
    "cilindre": lambda: trimesh.creation.cylinder(20, 50, sections=24),
    "tor": lambda: trimesh.creation.torus(30, 10, major_sections=16, minor_sections=8),
}


@pytest.fixture(params=sorted(MESHES))
def result(request):
    mesh = MESHES[request.param]()
    return mesh, pc.make_papercraft(mesh, target_faces=400, size_mm=120, tab_mm=5)


def test_cada_cara_un_cop_i_mides_reals(result):
    mesh, r = result
    m = pc.scale_to(pc.simplify(pc.clean(mesh), 400), 120)
    seen = Counter(fi for p in r.pieces for fi in p.tris)
    assert sorted(seen) == list(range(len(m.faces)))
    assert set(seen.values()) == {1}
    for p in r.pieces:
        for fi, t in p.tris.items():
            v = m.vertices[m.faces[fi]]
            for i in range(3):
                d3 = np.linalg.norm(v[i] - v[(i + 1) % 3])
                d2 = np.linalg.norm(t[i] - t[(i + 1) % 3])
                assert d2 == pytest.approx(d3, rel=1e-6, abs=1e-6)


def test_cap_solapament_dins_de_cada_peca(result):
    _, r = result
    for p in r.pieces:
        polys = [Polygon(t) for t in p.tris.values()] + [Polygon(t) for t in p.tabs]
        for a, b in itertools.combinations(polys, 2):
            assert a.intersection(b).area <= pc.OVERLAP_TOL * min(a.area, b.area) + 1e-6


def test_no_marca_arestes_compartides_com_a_solapament():
    # Dos triangles que només comparteixen una aresta no es solapen.
    s = pc._Shapes()
    s.add(Polygon([(0, 0), (10, 0), (0, 10)]))
    assert not s.hits(Polygon([(10, 0), (0, 10), (10, 10)]))
    assert s.hits(Polygon([(1, 1), (5, 1), (1, 5)]))


@pytest.mark.parametrize("nom", ["caixa", "caixa_densa", "cilindre"])
def test_solids_simples_surten_en_una_sola_peca(nom):
    r = pc.make_papercraft(MESHES[nom](), 400, 60)
    assert r.stats["peces"] == 1


def test_caixa_te_set_costures():
    # Una caixa de 12 triangles té 18 arestes: 11 plecs i 7 costures.
    r = pc.make_papercraft(MESHES["caixa"](), 400, 60)
    assert r.stats["costures"] == 7


def test_caixa_massa_gran_es_parteix_per_cabre():
    r = pc.make_papercraft(MESHES["caixa"](), 400, 120)
    assert r.stats["peces"] > 1
    assert r.stats["massa_grans"] == 0


def test_trossos_d_una_aresta_son_una_sola_costura():
    # Caixa densa: cada aresta de la caixa partida en 4 trossos és una costura.
    r = pc.make_papercraft(MESHES["caixa_densa"](), 400, 60)
    assert r.stats["costures"] == 7
    assert r.stats["arestes_tallades"] == 28


def test_no_dibuixa_plecs_entre_cares_coplanars():
    # Caixa densa: només les 12 arestes de la caixa pleguen o es tallen.
    r = pc.make_papercraft(MESHES["caixa_densa"](), 400, 60)
    total = sum(np.linalg.norm(c[1] - c[0]) for p in r.pieces for c, _ in p.fold_lines)
    tabs = sum(len(p.tabs) for p in r.pieces)
    # 6 arestes de 60/45/30 mm plegades com a molt, més les bases de les pestanyes.
    assert total <= 2 * (60 + 45 + 30) + tabs * 15 + 1e-6


def test_costures_numerades_dos_cops_i_amb_pestanya(result):
    _, r = result
    labels = Counter(s for p in r.pieces for _, s, _ in p.labels)
    assert len(labels) == r.stats["costures"]
    assert set(labels.values()) == {2}
    assert r.stats["pestanyes"] + r.stats["sense_pestanya"] == r.stats["arestes_tallades"]
    assert r.stats["sense_pestanya"] <= 0.05 * r.stats["arestes_tallades"]


def test_peces_dins_de_la_pagina(result):
    _, r = result
    W, H = pc.PAGES["A4"]
    assert r.stats["massa_grans"] == 0
    for p in r.pieces:
        pts = p.points()
        assert pts.min() >= 10 - 1e-6
        assert pts[:, 0].max() <= W - 10 + 1e-6
        assert pts[:, 1].max() <= H - 10 + 1e-6
    assert len(r.pages) == r.stats["pagines"]
    assert all(s.startswith("<svg") for s in r.pages)


def test_es_veu_la_cara_exterior():
    # A l'SVG (y cap avall) els triangles han de quedar en sentit horari
    # perquè, vistos des de fora, la malla és antihorària.
    r = pc.make_papercraft(MESHES["esfera"](), 400, 120)
    for p in r.pieces:
        for t in p.tris.values():
            assert pc._cross(t[1] - t[0], t[2] - t[0]) < 0


@pytest.mark.parametrize("fmt", ["stl", "obj"])
def test_carrega_fitxer_i_fusiona_vertexs(fmt):
    # Un STL guarda cada triangle amb vèrtexs propis: cal fusionar-los per desplegar.
    data = MESHES["caixa_densa"]().export(file_type=fmt)
    data = data.encode() if isinstance(data, str) else data
    mesh = pc.load_mesh(data, f"model.{fmt}")
    assert len(mesh.faces) == 192
    r = pc.make_papercraft(mesh, 400, 60)
    assert r.stats["peces"] == 1


def test_simplifica_malles_grans():
    r = pc.make_papercraft(trimesh.creation.icosphere(4, radius=30), 300, 120)
    assert r.faces <= 300
    assert r.stats["sense_pestanya"] <= 0.05 * r.stats["arestes_tallades"]
