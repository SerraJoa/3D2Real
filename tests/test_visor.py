"""Vista del muntatge: cada peça al seu lloc del model, i cap peça no en trepitja cap altra."""
import base64
import os
import sys

import numpy as np
import pytest
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cares  # noqa: E402
import laminacio as lm  # noqa: E402
import papercraft as pc  # noqa: E402
import visor  # noqa: E402

pytest.importorskip("manifold3d")


def overlaps(solids, tol=0.05):
    """Parelles de peces que comparteixen volum (mm³)."""
    out = []
    for i, a in enumerate(solids):
        for b in solids[i + 1:]:
            if np.any(a.mesh.bounds[0] > b.mesh.bounds[1]) or np.any(b.mesh.bounds[0] > a.mesh.bounds[1]):
                continue
            inter = trimesh.boolean.intersection([a.mesh, b.mesh], engine="manifold")
            with np.errstate(divide="ignore", invalid="ignore"):  # contacte sense volum
                v = 0.0 if inter.is_empty else inter.volume
            if v > tol:
                out.append((a.kind, b.kind, round(float(v), 2)))
    return out


def test_plaques_de_la_caixa_al_seu_lloc():
    m = trimesh.creation.box((60, 40, 30))
    r = cares.make_faces(m, 200, 80, 3.0)
    sol = visor.cares_solids(r)
    assert {s.kind for s in sol} == {"Plaques", "Suports"}
    assert all(s.mesh.is_watertight and s.mesh.volume > 0 for s in sol)
    # La cara de fora de les plaques és la superfície del model: la capsa coincideix.
    lo = np.min([s.mesh.bounds[0] for s in sol], axis=0)
    hi = np.max([s.mesh.bounds[1] for s in sol], axis=0)
    assert np.allclose(hi - lo, r.extra["mesh"].extents, atol=0.2)
    assert overlaps(sol) == []


def test_suports_del_con_no_xoquen_per_dins():
    """A la punta d'un con, els arcs de dues arestes veïnes es creuaven per dins."""
    r = cares.make_faces(trimesh.creation.cone(20, 70, sections=12), 200, 80, 3.0)
    assert r.stats["grups_de_plaques"] == 1
    assert overlaps(visor.cares_solids(r)) == []


def test_costella_no_trepitja_plaques_de_biaix():
    """La costella es retalla amb les plaques que talla, i les ranures segueixen el biaix."""
    r = cares.make_faces(trimesh.creation.icosphere(1, 30), 200, 80, 3.0)
    sol = visor.cares_solids(r)
    assert any(s.kind == "Costelles" for s in sol)
    assert overlaps(sol) == []


def test_capes_costella_i_tiges():
    m = trimesh.creation.icosphere(2, 30)
    r = lm.make_layers(m, 300, 80, 3.0, wall=6.0, align="costella")
    sol = visor.layers_solids(r)
    kinds = {s.kind for s in sol}
    assert {"Capes", "Costelles"} <= kinds
    assert overlaps(sol) == []
    # Les capes s'apilen: cada una al seu gruix, de baix a dalt del model.
    zs = sorted(round(s.mesh.bounds[0][2], 3) for s in sol if s.kind == "Capes")
    assert zs[0] == pytest.approx(r.extra["mesh"].bounds[0][2], abs=1e-3)
    r = lm.make_layers(m, 300, 80, 3.0)
    sol = visor.layers_solids(r)
    assert any(s.kind == "Tiges" for s in sol)
    assert overlaps(sol) == []


def test_paper_i_empaquetat():
    m = trimesh.creation.icosphere(1, 30)
    r = pc.make_papercraft(m, 80, 80, 5, "A4", False, False, 0, True)
    sol = visor.paper_solids(r)
    assert sum(len(s.mesh.faces) for s in sol) == len(r.mesh.faces)
    d = visor.pack(sol)
    n = len(base64.b64decode(d["pos"])) // 12
    assert n == 3 * d["triangles"]
    assert len(base64.b64decode(d["nrm"])) // 12 == n
    assert len(base64.b64decode(d["col"])) // 4 == n
    assert len(base64.b64decode(d["off"])) // 12 == n
    assert len(base64.b64decode(d["lpos"])) // 12 == len(base64.b64decode(d["lkind"]))  # un per punt
    assert d["kinds"] == ["Peces"]


def test_vista_del_model_i_simplificat():
    m = trimesh.creation.icosphere(3, 30)  # 1280 cares
    gran = visor.pack(visor.model_solids(m, "Model", "#9fb3c8", max_faces=500))
    assert gran["triangles"] <= 500  # una còpia més lleugera per veure-la
    d = visor.pack(visor.model_solids(m, "Simplificat", "#dcc29a", edges="totes"))
    assert d["triangles"] == len(m.faces)
    # Totes les arestes: dos punts per aresta.
    assert len(base64.b64decode(d["lpos"])) // 12 == 2 * len(m.edges_unique)
    cap = visor.pack(visor.model_solids(m, "Model", "#9fb3c8", edges="cap"))
    assert len(base64.b64decode(cap["lpos"])) == 0


def test_cerca_de_costelles_rapida_opcional():
    """Per defecte la cerca és completa; la ràpida és una opció i també dona un muntatge vàlid."""
    import inspect
    assert inspect.signature(cares.make_faces).parameters["fast_ribs"].default is False
    r = cares.make_faces(trimesh.creation.icosphere(1, 30), 200, 80, 3.0, fast_ribs=True)
    assert overlaps(visor.cares_solids(r)) == []


def test_mes_suports_petits_o_menys_de_grans():
    """La distància entre suports d'una aresta tria entre pocs suports grans o molts de petits."""
    m = trimesh.creation.box((200, 60, 40))
    pocs = cares.make_faces(m, 50, 200, 3.0)
    molts = cares.make_faces(m, 50, 200, 3.0, bracket_mm=12, bracket_spacing=30)
    assert molts.stats["suports"] > pocs.stats["suports"]
    assert overlaps(visor.cares_solids(molts)) == []


def test_suports_petits_quan_el_gran_no_hi_cap():
    """Si el suport gran no hi cap, l'aresta en rep més de petits (sense treure lloc a les altres)."""
    m = trimesh.creation.cylinder(20, 60, sections=10)
    r = cares.make_faces(m, 300, 120, 3.0)
    assert r.stats["arestes_sense_suport"] == 0
    assert r.stats["suports"] > r.stats["arestes"]
    assert overlaps(visor.cares_solids(r)) == []
