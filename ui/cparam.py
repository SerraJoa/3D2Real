"""Cares: els paràmetres per apartats (material, cares, suports) i la mostra rotable que mostra l'efecte.

Cada funció dibuixa els seus controls i retorna un dict. `mostra` genera, sobre un cub de la mida de la
placa mitjana de la figura, les plaques i suports amb els paràmetres que hi ha ara.
"""
import numpy as np
import streamlit as st
import trimesh

import cares
import laser
import visor

DEF_CAR = dict(gap=0.0, chamfer_mm=1.0, merge_small=4.0, paper=False, lamp=None, plates_out="CNC")
MIDES = ["Automàtica (escala)", "Manual"]


def material() -> dict:
    thickness = st.number_input("Gruix del material (mm)", 0.5, 20.0, 3.0, 0.5, key="cm_gruix")
    sheet = st.selectbox("Planxa (mm)", [*laser.SHEETS, "Lliure"], key="cm_planxa")
    if sheet == "Lliure":
        s1, s2 = st.columns(2)
        sheet_mm = (s1.number_input("Amplada (mm)", 20.0, 5000.0, 600.0, 10.0, key="sheet_w"),
                    s2.number_input("Alçada (mm)", 20.0, 5000.0, 400.0, 10.0, key="sheet_h"))
    else:
        sheet_mm = laser.SHEETS[sheet]
    return dict(thickness=thickness, sheet_mm=sheet_mm, sheet=sheet)


def cares_p(out: str, pur_cnc: bool, lamp_controls, size: float) -> dict:
    d = dict(DEF_CAR)
    if not pur_cnc:
        d["plates_out"] = "3D"
        if out == "Mixta":
            d["plates_out"] = "CNC" if st.radio("Plaques", ["CNC", "3D"], key="plates_out") == "CNC" else "3D"
    d["gap"] = st.number_input("Espai entre cares (mm)", 0.0, 50.0, 0.0, 0.5, key="cc_gap",
                               help="Per a làmpades: deixa passar la llum entre plaques.")
    d["chamfer_mm"] = st.slider("Xamfrà de les plaques (mm)", 0.0, 10.0, 1.0, 0.5, key="cc_xamfra",
                                help="Talla les cantonades que punxen de les plaques, per a l'efecte "
                                     "(sobretot amb llum a dins). No s'aplica als suports. 0 = sense.")
    d["merge_small"] = st.slider("Fusiona plaques més petites que (gruixos)", 0.0, 8.0, 4.0, 0.5, key="cc_fusio",
                                 help="Les plaques on no hi cap un cercle d'aquests gruixos de diàmetre no "
                                      "poden rebre suports: es fusionen amb la veïna més propera, si es pot "
                                      "sense deformar el model massa. 0 = no. No s'aplica amb textura.")
    d["lamp"] = lamp_controls("cares", size, False)
    d["paper"] = st.checkbox("🗒️ Paper difusor per dins (tires per escletxa)", False, key="cc_paper",
                             help="Tires de paper que s'enganxen per dins i tapen les escletxes entre "
                                  "plaques, amb osques per esquivar els suports. Surten en planxes a part, "
                                  "per a tallar en paper.")
    st.caption("Les cares van millor amb models de poques zones planes (caixes, poliedres). Amb formes "
               "arrodonides i moltes cares, cada triangle és una placa: pot trigar molts minuts: baixa la "
               "simplificació o tria la cerca de costelles ràpida.")
    return d


def sup_def(plate_mm: float, thickness: float) -> dict:
    return dict(joint="encaix", bracket=int(cares.auto_bracket(plate_mm, 2.0, thickness)), per_edge=1,
                spacing=80, max_leg=50, grip=True, fill_gap=False, tenon_chamfer=0.5, fast_ribs=False,
                supports_out="CNC", support_kind="Aresta", bed=(220.0, 220.0))


def suports(plate_mm: float, thickness: float, out: str, pur_cnc: bool) -> dict:
    d = sup_def(plate_mm, thickness)
    if not pur_cnc:
        d["supports_out"] = "3D"
        if out == "Mixta":
            d["supports_out"] = "CNC" if st.radio("Suports", ["CNC", "3D"], key="supports_out") == "CNC" else "3D"
        if d["supports_out"] == "3D":
            d["support_kind"] = st.radio("Tipus de suport 3D", ["Aresta", "Vèrtex (properament)"],
                                         horizontal=True, key="support_kind",
                                         help="Aresta: un suport per aresta. Vèrtex: una peça per vèrtex "
                                              "que uneix 3 o més plaques.")
            if d["support_kind"].startswith("Vèrtex"):
                st.info("Encara no disponible: es generen suports d'aresta.")
    d["joint"] = st.radio("Suports", ["encaix", "cola"], horizontal=True, key="cs_unio",
                          help="Encaix: arc amb tenons que entren en ranures de les plaques (els tenons es "
                               "veuen per fora). Cola: estel enganxat per dins, del tot invisible.")
    sizing = st.radio("Mida dels suports", MIDES, horizontal=True, key="cs_mida",
                      help="Automàtica: el braç surt de la placa mitjana dividida per l'escala, i per "
                           "defecte un suport centrat per aresta.")
    if sizing.startswith("Auto"):
        ratio = st.slider("Escala placa mitjana / braç", 1.0, 4.0, 2.0, 0.1, key="cs_escala",
                          help="2 = el braç fa la meitat de la placa mitjana. Més alt: suports més petits "
                               "i més fàcils d'encabir; per sota d'1,5 és fàcil que les plaques es quedin "
                               "soltes.")
        d["bracket"] = int(cares.auto_bracket(plate_mm, ratio, thickness))
        per = st.selectbox("Suports per aresta", ["1 centrat", "2", "3", "segons la distància"], key="cs_per",
                           help="Els suports es reparteixen simètricament des del mig cap als costats.")
        d["per_edge"] = {"1 centrat": 1, "2": 2, "3": 3}.get(per, 0)
        d["spacing"] = st.slider("Distància (si és segons la distància, mm)", 20, 200, 80, key="cs_dist",
                                 disabled=d["per_edge"] > 0)
    else:
        d["bracket"] = st.slider("Llargada dels braços dels suports (mm)", 8, 60, 25, key="cs_braç")
        d["per_edge"] = 0
        d["spacing"] = st.slider("Distància entre suports d'una mateixa aresta (mm)", 20, 200, 80, key="cs_dist2",
                                 help="Amb els braços: pocs suports grans (distància i braços llargs) o "
                                      "molts de petits (curts i a prop), que caben millor a les plaques "
                                      "estretes.")
    escala = plate_mm / d["bracket"]
    (st.success if escala >= 2 else st.warning if escala >= 1.5 else st.error)(
        f"Placa mitjana {plate_mm:.0f} mm · braç {d['bracket']} mm · escala {escala:.1f}"
        + ("" if escala >= 1.5 else " — massa justa: baixa les cares o escurça el braç"))
    d["max_leg"] = st.slider("Llargada màxima del braç (% de la placa)", 0, 100, 50, 5, key="cs_maxleg",
                             help="Un suport no passa d'aquest percentatge de la fondària de la placa més "
                                  "petita que uneix (des de l'aresta). 0 = sense límit.")
    d["grip"] = st.checkbox("Agafa les plaques petites pels extrems", True, key="cs_grip",
                            help="Si el braç no hi cap sencer en una placa petita, es posa igualment "
                                 "recolzat a mitges i enganxat, sense tenó.")
    d["fill_gap"] = st.checkbox("Les puntes dels suports omplen l'escletxa (es veuen per fora)", False,
                                key="cs_omple", help="Només té sentit amb espai entre cares.")
    d["tenon_chamfer"] = st.slider("Xamfrà dels tenons (mm)", 0.0, 1.5, 0.5, 0.1, key="cs_xtenons",
                                   help="A les puntes dels tenons de suports i costelles, perquè entrin més "
                                        "fàcilment a les ranures (0,5–1 mm).")
    d["fast_ribs"] = st.checkbox("Cerca de costelles ràpida", False, key="cs_rapida",
                                 help="Amb formes arrodonides la cerca completa pot trigar molts minuts. La "
                                      "ràpida prova menys plans i s'atura als 10 s.")
    if not pur_cnc and d["supports_out"] == "3D":
        b1, b2 = st.columns(2)
        d["bed"] = (b1.number_input("Llit X (mm)", 20.0, 1000.0, 220.0, 10.0, key="bx_cares"),
                    b2.number_input("Llit Y (mm)", 20.0, 1000.0, 220.0, 10.0, key="by_cares"))
    return d


def args(mat: dict, car: dict, sup: dict) -> tuple:
    """(args posicionals, kwargs) de `cares.make_faces` amb els paràmetres dels tres apartats."""
    return ((mat["thickness"], car["gap"], sup["bracket"], mat["sheet_mm"], sup["joint"]),
            dict(fast_ribs=sup["fast_ribs"], bracket_spacing=sup["spacing"], chamfer_mm=car["chamfer_mm"],
                 tenon_chamfer=sup["tenon_chamfer"], fill_gap=sup["fill_gap"], merge_small=car["merge_small"],
                 per_edge=sup["per_edge"], grip=sup["grip"], lamp=car["lamp"], paper=car["paper"],
                 max_leg_frac=sup["max_leg"] / 100))


def mostra(mat: dict, car: dict, sup: dict, plate_mm: float) -> None:
    """Mostra rotable: un cub de la mida de la placa mitjana, tallat amb els paràmetres actuals."""
    costat = float(np.clip(plate_mm * 1.3, 40, 120))
    a, kw = args(mat, car, sup)
    kw.update(lamp=None, paper=False, merge_small=0.0, fast_ribs=True)   # la mostra és un cub simple
    sig = repr((a, sorted(kw.items()), costat))
    memo = st.session_state.setdefault("_mostra_cares", {})
    if memo.get("sig") != sig:
        r = cares.make_faces(trimesh.creation.box((costat,) * 3), 12, costat, *a, **kw)
        memo.clear()
        memo.update(sig=sig, dades=visor.pack(visor.cares_solids(r)), stats=r.stats)
    st.markdown("**Mostra**")
    st.caption(f"Un cub de {costat:.0f} mm (la mida d'una placa de la teva figura): arrossega per girar-lo.")
    visor.show([], key="visor_mostra", height=480, data=memo["dades"])
