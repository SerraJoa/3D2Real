import base64

import streamlit as st

import cares
import laminacio
import laser
import papercraft as pc

st.set_page_config(page_title="Desplegables", layout="wide")
st.title("✂️ Desplegables — 3D → paper i làser")
st.caption("Importació → reducció → desplegable de paper · cares amb suports · laminació per capes")


def show(svgs: list[str], label: str) -> None:
    for i, svg in enumerate(svgs, 1):
        b64 = base64.b64encode(svg.encode()).decode()
        st.markdown(f"**{label} {i}**")
        st.markdown(f'<img src="data:image/svg+xml;base64,{b64}" '
                    'style="width:100%;border:1px solid #ccc;background:white"/>',
                    unsafe_allow_html=True)


uploaded = st.file_uploader("Carrega STL o OBJ", type=["stl", "obj"])
if uploaded:
    try:
        # ---- Fases comunes: importació i reducció
        mesh = pc.load_mesh(uploaded.getvalue(), uploaded.name)
        st.success(f"{len(mesh.faces):,} cares · {len(mesh.vertices):,} vèrtexs")
        c1, c2 = st.columns(2)
        with c1:
            maxf = max(10, len(mesh.faces))
            target = st.slider("Simplificació — nombre de cares", 10, maxf, max(10, min(maxf, 300)))
        with c2:
            size = st.number_input("Mida final — costat més llarg (mm)", 20.0, 2000.0, 120.0, 10.0)

        branch = st.radio("Branca", ["📄 Desplegable de paper", "🔷 Cares (làser)",
                                     "🥞 Laminació (làser)"], horizontal=True)

        if branch.startswith("📄"):
            c1, c2 = st.columns(2)
            with c1:
                page = st.selectbox("Paper", list(pc.PAGES))
                landscape = st.checkbox("Apaïsat")
                face_numbers = st.checkbox("Numerar les cares")
            with c2:
                tab = st.slider("Amplada de pestanyes (mm)", 2.0, 12.0, 5.0, 0.5)
                zones = st.checkbox("Zones naturals: tancar els problemes en peces petites", True,
                                    help="On el desplegament deixaria triangles solts, els agrupa "
                                         "en tires estretes que es despleguen soles.")
                lines = st.slider("Tallar per arestes marcades — angle mínim (°)", 0, 90, 0, 5,
                                  help="0 = no.")
            if st.button("🚀 Generar desplegable", type="primary"):
                with st.spinner("Desplegant…"):
                    st.session_state["paper"] = pc.make_papercraft(
                        mesh, target, size, tab, page, landscape, face_numbers, lines, zones)
            r = st.session_state.get("paper")
            if r:
                s = r.stats
                st.success(f"{r.faces} cares · {s['peces']} peces ({s['zones']} zones naturals) · "
                           f"{s['pagines']} pàgines · {s['costures']} costures · "
                           f"{s['pestanyes']} pestanyes")
                st.caption(f"Pestanyes: {s['pestanyes_encongides']} encongides, "
                           f"{s['pestanyes_dentades']} dentades, "
                           f"{s['pestanyes_canviades']} canviades de costat i "
                           f"{s['pestanyes_retallades']} retallades per no xocar.")
                if s["sense_pestanya"]:
                    st.warning(f"{s['sense_pestanya']} trossos de costura no tenen lloc per a una "
                               "pestanya: enganxa'ls amb cinta per darrere.")
                if s["massa_grans"]:
                    st.warning(f"{s['massa_grans']} peces no caben a la pàgina.")
                st.download_button("⬇️ Descarrega les pàgines (SVG en un ZIP)", r.zip_bytes(),
                                   "desplegable.zip", "application/zip")
                st.info("Contínua = tall · ratlles = plec de vall · punt i ratlla = plec de "
                        "muntanya · gris = pestanya · els números vermells iguals s'uneixen.")
                show(r.pages, "Pàgina")

        else:
            c1, c2 = st.columns(2)
            with c1:
                thickness = st.number_input("Gruix del material (mm)", 0.5, 20.0, 3.0, 0.5)
                sheet = st.selectbox("Planxa (mm)", list(laser.SHEETS))
            if branch.startswith("🔷"):
                with c2:
                    gap = st.number_input("Espai entre cares (mm)", 0.0, 50.0, 0.0, 0.5,
                                          help="Per a làmpades: deixa passar la llum entre plaques.")
                    joint = st.radio("Suports", ["encaix", "cola"], horizontal=True,
                                     help="Encaix: arc amb tenons que entren en ranures de les "
                                          "plaques (els tenons es veuen per fora). Cola: estel "
                                          "enganxat per dins, del tot invisible.")
                    bracket = st.slider("Llargada dels braços dels suports (mm)", 8, 60, 25)
                if st.button("🚀 Generar cares", type="primary"):
                    with st.spinner("Tallant cares i suports…"):
                        st.session_state["cares"] = cares.make_faces(
                            mesh, target, size, thickness, gap, bracket, laser.SHEETS[sheet], joint)
                r, prefix = st.session_state.get("cares"), "cares"
                if r:
                    s = r.stats
                    st.success(f"{s['plaques']} plaques · {s['suports']} suports · "
                               f"{s['costelles']} costelles · {s['mitges_fustes']} mitges fustes · "
                               f"{s['ranures']} ranures · "
                               f"{s['planxes']} planxes")
                    import vista
                    st.markdown("**Grups de plaques** (un color per grup unit; vora negra = placa "
                                "sense cap suport)")
                    v = vista.plates_view(r, width=260, yaw=25, pitch=25)
                    st.markdown(f'<img src="data:image/svg+xml;base64,'
                                f'{base64.b64encode(v.encode()).decode()}"/>',
                                unsafe_allow_html=True)
                    if s["grups_de_plaques"] > 1:
                        st.warning(f"Les plaques queden en {s['grups_de_plaques']} grups sense "
                                   "suport entre ells: hi ha plaques massa petites per a suports.")
            else:
                with c2:
                    column = st.number_input("Diàmetre de les tiges (mm)", 1.0, 20.0, 5.0, 0.5)
                    wall = st.number_input("Buidar: gruix de paret (mm, 0 = massís)", 0.0, 50.0,
                                           6.0, 0.5,
                                           help="Les capes es buiden deixant aquesta paret per tots "
                                                "costats; les columnes queden dins d'una anella "
                                                "unida a la paret.")
                if st.button("🚀 Generar capes", type="primary"):
                    with st.spinner("Tallant capes…"):
                        st.session_state["capes"] = laminacio.make_layers(
                            mesh, target, size, thickness, column, laser.SHEETS[sheet], wall)
                r, prefix = st.session_state.get("capes"), "capes"
                if r:
                    s = r.stats
                    st.success(f"{s['capes']} capes · {s['peces']} peces · {s['columnes']} "
                               f"columnes · {s['estalvi']} % de material estalviat · "
                               f"{s['planxes']} planxes")
                    if s["peces_sense_columna"] or s["peces_amb_una_columna"]:
                        st.warning(f"{s['peces_amb_una_columna']} peces amb una sola columna i "
                                   f"{s['peces_sense_columna']} sense cap (massa estretes): "
                                   "alinea-les amb el contorn gravat.")
            if r:
                if r.stats["massa_grans"]:
                    st.warning(f"{r.stats['massa_grans']} peces no caben a la planxa.")
                st.download_button("⬇️ Descarrega les planxes (SVG + muntatge en un ZIP)",
                                   r.zip_bytes(prefix), f"{prefix}.zip", "application/zip")
                st.info("Vermell = tallar · blau = gravar.")
                with st.expander("Instruccions de muntatge"):
                    st.text("\n".join(r.notes))
                show(r.sheets, "Planxa")
    except Exception as e:
        st.error(str(e))
