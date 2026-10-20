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
    x0, y0, x1, y1 = gran.bounds   # les ranures obertes al cantell són osques del contorn
    assert sorted((x1 - x0, y1 - y0)) == pytest.approx([84, 114], abs=0.05)
    assert 0.9 * 114 * 84 < gran.area < 114 * 84


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


def _coet():
    return trimesh.creation.revolve(np.array([[0, 0], [10, 0], [10, 40], [0, 60]]), sections=16)


def test_costella_uneix_la_punta_del_coet():
    # Els 16 triangles de la punta són massa estrets per a suports entre veïns: una sola
    # costella perpendicular a l'eix els uneix tots al cos.
    r = cares.make_faces(_coet(), 400, 120, 3.0, 0.0)
    assert r.stats["grups_de_plaques"] == 1
    assert 1 <= r.stats["costelles"] <= 2
    rib = next(p for p in r.parts if p.name.startswith("K"))
    assert rib.shape.is_valid


def test_sense_problemes_no_hi_ha_costelles(caixa):
    assert caixa.stats["costelles"] == 0


def _ninot():
    pytest.importorskip("manifold3d")
    parts = [trimesh.creation.box(s) for s in
             ((20, 12, 30), (12, 12, 12), (6, 6, 26), (6, 6, 26), (7, 7, 24), (7, 7, 24))]
    for p, o in zip(parts, ((0, 0, 0), (0, 0, 21), (13, 0, 2), (-13, 0, 2), (5, 0, -27), (-5, 0, -27))):
        p.apply_translation(o)
    return trimesh.boolean.union(parts)


def test_suports_i_costelles_encaixen_a_mitja_fusta_sense_solapar():
    """Els suports que creuen una costella hi encaixen a mitja fusta: cap punt de cap
    suport no queda dins de la costella."""
    import shapely
    calls = []
    orig, orig_nest = cares.half_lap, cares.nest
    seen = {}

    def spy(c, seam, shape, plane, t):
        res = orig(c, seam, shape, plane, t)
        if res and res[0]:
            calls.append((c, seam, plane))
        return res

    def nest_spy(parts, sheet, title, images=None):
        seen.update({id(p): p.shape for p in parts})
        seen["parts"] = parts
        return orig_nest(parts, sheet, title, images)

    cares.half_lap, cares.nest = spy, nest_spy
    try:
        r = cares.make_faces(_ninot(), 400, 120, 3.0, 0.0)
    finally:
        cares.half_lap, cares.nest = orig, orig_nest
    assert r.stats["mitges_fustes"] > 0
    t, checked = 3.0, 0
    for c, seam, (origin, N, u, v, rparts) in calls:
        # Només els intents que són de debò un suport final (el que hi ha en aquest punt): en
        # planificar se'n proven d'altres posicions que després es descarten.
        mine = [p for p in seen["parts"] if p.name.startswith(f"S{seam.number}.")
                and p.pose is not None and np.allclose(p.pose[0][:3, 3], c)]
        if len(mine) != 1:
            continue
        rib = shapely.union_all([seen[id(p)] for p in rparts])
        sh = seen[id(mine[0])]
        d3 = (seam.e1 - seam.e0) / np.linalg.norm(seam.e1 - seam.e0)
        x0, y0, x1, y1 = sh.bounds
        xs, ys = (g.ravel() for g in np.meshgrid(np.linspace(x0, x1, 60), np.linspace(y0, y1, 60)))
        ins = shapely.contains_xy(sh, xs, ys)
        for z in np.linspace(-0.45 * t, 0.45 * t, 4):
            p3 = c + np.outer(xs[ins], seam.a) + np.outer(ys[ins], -seam.np_) + z * d3
            near = np.abs((p3 - origin) @ N) < 0.45 * t
            q = np.column_stack([(p3[near] - origin) @ u, (p3[near] - origin) @ v])
            assert not shapely.contains_xy(rib, q[:, 0], q[:, 1]).any()
            checked += int(near.sum())
    assert checked > 0
    assert all(p.shape.geom_type == "Polygon" for p in r.parts if p.name[0] in "SK")


@pytest.fixture(scope="module")
def capes_buides():
    m = trimesh.creation.box((40, 30, 20))
    return lm.make_layers(m, 400, 60, 3.0, 5.0, wall=6.0)


def test_buidar_estalvia_material_i_deixa_tapes(capes_buides):
    r = capes_buides
    assert r.stats["estalvi"] > 30
    holed = [p for p in r.parts if any(Polygon(h).area > 50 for h in p.shape.interiors)]
    # 30 mm d'alçada amb parets de 6 mm: les dues capes de dalt i de baix són tapes massisses.
    names = {p.name for p in holed}
    for tapa in ("L1", "L2", "L9", "L10"):
        assert tapa not in names
    assert names


def test_la_cavitat_no_arriba_a_la_superficie(capes_buides):
    for p in capes_buides.parts:
        for h in p.shape.interiors:
            hole = Polygon(h)
            if hole.area > 50:
                assert hole.distance(p.shape.exterior) >= 6.0 - 1e-6


def test_buidar_respecta_les_columnes_i_cada_capa_es_una_peca(capes_buides):
    r = capes_buides
    assert r.stats["peces"] == r.stats["capes"]
    assert r.stats["peces_sense_columna"] == 0
    for p in r.parts:
        small = [Polygon(h) for h in p.shape.interiors if Polygon(h).area < 50]
        assert len(small) >= lm.COLUMNS_PER_PIECE  # els forats de les columnes hi són


def test_buidar_no_parteix_el_tor():
    m = trimesh.creation.torus(30, 10, major_sections=16, minor_sections=8)
    massis = lm.make_layers(m, 400, 120, 3.0, 5.0)
    buit = lm.make_layers(m, 400, 120, 3.0, 5.0, wall=6.0)
    assert buit.stats["peces"] == massis.stats["peces"]
    assert buit.stats["estalvi"] > 0


@pytest.fixture(scope="module")
def caixa_costella():
    return lm.make_layers(trimesh.creation.box((40, 30, 20)), 400, 60, 3.0, 5.0, wall=6.0,
                          align="costella")


def test_costella_alinea_les_capes_buidades_amb_osques(caixa_costella):
    r = caixa_costella
    assert r.stats["costelles"] == 1
    rib = next(p for p in r.parts if p.name.startswith("R"))
    teeth = {t for _, t, _ in rib.labels}
    for p in r.parts:
        if not p.name.startswith("L"):
            continue
        cavity = [Polygon(h) for h in p.shape.interiors if Polygon(h).area > 50]
        if cavity:
            assert p.name in teeth                     # cada capa buidada té dent
            # La cavitat amb les dues osques: més estreta que la paret, però sense travessar-la.
            assert cavity[0].distance(p.shape.exterior) >= 6.0 / 2 - 1e-6
    # Les tapes (massisses) van amb columnes.
    assert r.stats["peces_sense_columna"] == 0


def test_dents_de_la_costella_entren_a_les_parets(caixa_costella):
    rib = next(p for p in caixa_costella.parts if p.name.startswith("R"))
    rect = np.array(rib.shape.minimum_rotated_rectangle.exterior.coords)
    long_side = max(np.linalg.norm(rect[i + 1] - rect[i]) for i in range(2))
    # Cavitat de 60 − 2·6 = 48 mm pel costat llarg, més 3 mm d'osca a cada paret
    # (la peça pot estar girada a la planxa).
    assert long_side == pytest.approx(48 + 2 * 3, abs=0.2)


def test_l_esfera_es_munta_amb_una_sola_costella_des_del_mig():
    import papercraft as pc
    m = pc.scale_to(pc.clean(trimesh.creation.icosphere(2, radius=30)), 90)
    z0, z1 = m.bounds[:, 2]
    K = int(math.ceil((z1 - z0) / 3))
    solid = [lm.slice_at(m, z0 + (k + 0.5) * 3 + 1e-7) for k in range(K)]
    ribs, notches, notes = lm.spine(solid, lm.hollow(solid, 6.0, 3.0), 3.0, 6.0)
    assert len(ribs) == 1
    assert "comença per" in notes[0] and "per dalt" in notes[0] and "per baix" in notes[0]


def test_una_cintura_parteix_la_costella():
    # Rellotge de sorra: s'estreny al mig i torna a eixamplar-se. Cap capa no pot passar
    # per la cintura, així que la costella es parteix en dos trams que la comparteixen.
    import papercraft as pc
    prof = np.array([[0, 0], [30, 0], [30, 5], [12, 30], [30, 55], [30, 60], [0, 60]], float)
    m = pc.scale_to(pc.clean(trimesh.creation.revolve(prof, sections=24)), 90)
    z0, z1 = m.bounds[:, 2]
    K = int(math.ceil((z1 - z0) / 3))
    solid = [lm.slice_at(m, z0 + (k + 0.5) * 3 + 1e-7) for k in range(K)]
    ribs, notches, notes = lm.spine(solid, lm.hollow(solid, 6.0, 3.0), 3.0, 6.0)
    assert len(ribs) == 2
    shared = set.intersection(*({t for _, t, _ in p.labels} for p in ribs))
    assert len(shared) == 1


def _fora_del_model(r, prefix: str) -> float:
    """Volum màxim d'una peça muntada (suport o costella) que surt de la superfície del model."""
    worst = 0.0
    for name, shape, M, z0, z1 in r.extra["assembly"]:
        if name.startswith(prefix):
            s = laser.solid(shape, M, z0, z1)
            out = trimesh.boolean.difference([s, r.extra["mesh"]], engine="manifold")
            worst = max(worst, 0.0 if out.is_empty else float(out.volume))
    return worst


def test_les_costelles_no_sobresurten_de_la_superficie():
    pytest.importorskip("manifold3d")
    r = cares.make_faces(_ninot(), 60, 120, 3.0, 0.0, chamfer_mm=1.0)
    assert r.stats["costelles"] >= 1
    assert _fora_del_model(r, "K") < 0.5   # els tenons acaben a ras de la cara de fora, de biaix o no


def test_stl_per_peca_plans_i_al_gruix(caixa):
    import io
    import zipfile
    data, big = caixa.stl_zip("t", bed=(1000, 1000))
    assert big == []
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    assert len(names) == len(caixa.extra["assembly"])
    for n in names:
        m = trimesh.load(io.BytesIO(z.read(n)), file_type="stl")
        assert np.allclose(m.bounds[0], 0, atol=1e-6) and abs(m.extents[2] - 3.0) < 1e-3
    assert caixa.stl_zip("t", bed=(5, 5))[1]  # amb un llit minúscul cap peça no hi cap


def test_un_sol_tenó_continu_per_tot_el_braç():
    spans = cares.tenon_spans(2.0, 25.0, 3.0)
    assert spans == [(pytest.approx(2.02), pytest.approx(26.0))]
    assert cares.tenon_spans(2.0, 2.0, 3.0) == []
    # Si la ranura llarga no hi cap, es proven trams més curts a la punta.
    opts = cares.tenon_options(2.0, 25.0, 3.0)
    assert opts[0] == spans[0] and len(opts) > 1
    assert all(u0 >= 2.0 and u1 <= 26.0 and u1 - u0 >= cares.TENON_MIN - 1e-9 for u0, u1 in opts)


def test_escala_placa_i_braç_automàtic(caixa):
    p = cares.plate_scale(trimesh.creation.box((60, 40, 30)))
    assert 30 < p < 60
    assert cares.auto_bracket(60, 2.0, 3.0) == 30
    assert cares.auto_bracket(5, 2.0, 3.0) == 5       # mínim 1,5 gruixos
    assert cares.auto_bracket(500, 1.0, 3.0) == 60


def test_un_suport_per_aresta_centrat():
    r = cares.make_faces(trimesh.creation.box((60, 40, 30)), 200, 80, 3.0, per_edge=1)
    por_aresta = {}
    for p in r.parts:
        if p.name.startswith("S"):
            por_aresta.setdefault(p.name.split(".")[0], []).append(p)
    assert por_aresta and all(len(v) == 1 for v in por_aresta.values())


def test_agafar_plaques_petites_uneix_mes_sense_trencar_res():
    pytest.importorskip("manifold3d")
    m = _ninot()
    a = cares.make_faces(m, 60, 120, 3.0, grip=False)
    b = cares.make_faces(m, 60, 120, 3.0, grip=True)
    assert b.stats["grups_de_plaques"] <= a.stats["grups_de_plaques"]
    assert b.stats["arestes_sense_suport"] <= a.stats["arestes_sense_suport"]


def test_buidar_un_suport_gran_deixa_una_paret_contínua():
    disc = Point(0, 0).buffer(16.0).difference(Polygon([(0, 0), (-4, 16), (4, 16)]))
    out = cares.hollow(disc, 3.0)
    assert out.geom_type == "Polygon" and len(out.interiors) == 1
    assert out.area < 0.7 * disc.area and out.is_valid
    assert cares.hollow(Point(0, 0).buffer(5.0), 3.0).equals(Point(0, 0).buffer(5.0))  # petit: no es toca


def test_portalampades_a_cares_costella_massissa_amb_forat():
    m = trimesh.creation.box((120, 120, 120))
    r = cares.make_faces(m, 400, 120, 3.0, 0.0, lamp=dict(z=60, d=40, slot=0, angle=0, x=0, y=0))
    assert any("Portalàmpades: costella" in n for n in r.notes)
    rib = [p for p in r.parts if p.name.startswith("K")]
    assert rib and any(len(g.interiors) and Polygon(g.interiors[0]).area > 0.9 * np.pi * 20 ** 2
                       for p in rib for g in getattr(p.shape, "geoms", [p.shape]))


def test_portalampades_massa_gran_avisa():
    m = trimesh.creation.box((40, 40, 40))
    r = cares.make_faces(m, 400, 40, 3.0, 0.0, lamp=dict(z=20, d=60, slot=0, angle=0, x=0, y=0))
    assert any("no hi cap" in n for n in r.notes)


def test_paper_difusor_tires_amb_osques_pels_suports():
    m = trimesh.creation.box((40, 30, 20))
    r = cares.make_faces(m, 400, 120, 3.0, 4.0, paper=True, paper_margin=5.0)
    assert r.stats["tires_de_paper"] >= r.stats["arestes"]   # una per aresta com a mínim
    assert len(r.sheets) >= 2 and "Paper" in r.sheets[-1]
    sense = cares.make_faces(m, 400, 120, 3.0, 4.0)
    assert sense.stats["tires_de_paper"] == 0


def test_portalampades_obre_un_pas_a_les_capes_de_l_alcada():
    from shapely.geometry import Point
    m = trimesh.creation.cylinder(30, 80, sections=40)
    r = lm.make_layers(m, 300, 80, 3.0, lamp=dict(x=0, y=0, z=20, len=30, d=24, slot=10, angle=0))
    assert r.stats["capes_amb_portalampades"] == 10
    capes = {n: sh for n, sh, *_ in r.extra["assembly"]}
    mig = capes["L14"]        # a 20..50 mm: dins del rang
    assert not mig.intersects(Point(0, 0).buffer(11.5))
    assert capes["L2"].intersects(Point(0, 0).buffer(5))  # una capa de baix, intacta


def test_paper_difusor_es_una_pinta_unida_pel_llom():
    m = trimesh.creation.box((120, 120, 120))
    r = cares.make_faces(m, 400, 120, 3.0, 4.0, bracket_mm=20,
                         lamp=dict(z=60, d=40, slot=12, angle=0, x=0, y=0), paper=True)
    pap = dict((n, s) for n, s, *_ in r.paper)
    assert pap and all(s.geom_type == "Polygon" for s in pap.values())   # una peça sola per aresta
    assert any(len(s.exterior.coords) > 5 for s in pap.values())         # amb osques (dents)


def test_paper_pegat_per_vertex_amb_xamfra():
    m = trimesh.creation.box((40, 30, 20))
    a = cares.make_faces(m, 400, 120, 3.0, 4.0, paper=True)
    b = cares.make_faces(m, 400, 120, 3.0, 4.0, paper=True, chamfer_mm=3.0)
    names = [n for n, *_ in b.paper]
    assert sum(n.startswith("V") for n in names) == 8      # un pegat per vèrtex del cub
    assert not any(n.startswith("V") for n, *_ in a.paper)
    assert sum(not n.startswith("V") for n in names) == len(a.paper)   # les pintes no canvien
