import base64

import streamlit as st

import papercraft as pc

st.set_page_config(page_title="Desplegables", layout="wide")
st.title("✂️ Desplegables — 3D → paper")
st.caption("Malla 3D → simplificació → desplegament sense solapaments → pestanyes → pàgines SVG")

uploaded = st.file_uploader("Carrega STL o OBJ", type=["stl", "obj"])
if uploaded:
    try:
        mesh = pc.load_mesh(uploaded.getvalue(), uploaded.name)
        st.success(f"{len(mesh.faces):,} cares · {len(mesh.vertices):,} vèrtexs")
        c1, c2, c3 = st.columns(3)
        with c1:
            maxf = max(10, len(mesh.faces))
            target = st.slider("Simplificació — nombre de cares", 10, maxf, max(10, min(maxf, 300)))
            size = st.number_input("Mida final — costat més llarg (mm)", 20.0, 2000.0, 120.0, 10.0)
        with c2:
            page = st.selectbox("Paper", list(pc.PAGES))
            landscape = st.checkbox("Apaïsat")
        with c3:
            tab = st.slider("Amplada de pestanyes (mm)", 2.0, 12.0, 5.0, 0.5)
            face_numbers = st.checkbox("Numerar les cares")

        if st.button("🚀 Generar desplegable", type="primary"):
            with st.spinner("Desplegant…"):
                st.session_state["result"] = pc.make_papercraft(
                    mesh, target, size, tab, page, landscape, face_numbers)

        r = st.session_state.get("result")
        if r:
            s = r.stats
            st.success(f"{r.faces} cares · {s['peces']} peces · {s['pagines']} pàgines · "
                       f"{s['costures']} costures · {s['pestanyes']} pestanyes")
            if s["sense_pestanya"]:
                st.warning(f"{s['sense_pestanya']} trossos de costura no tenen lloc per a una "
                           "pestanya: enganxa'ls amb cinta per darrere.")
            if s["massa_grans"]:
                st.warning(f"{s['massa_grans']} peces no caben a la pàgina: redueix la mida final "
                           "o tria un paper més gran.")
            st.download_button("⬇️ Descarrega les pàgines (SVG en un ZIP)", r.zip_bytes(),
                               "desplegable.zip", "application/zip")
            st.info("Contínua = tall · ratlles = plec de vall · punt i ratlla = plec de muntanya · "
                    "gris = pestanya · els números vermells iguals s'uneixen.")
            for i, svg in enumerate(r.pages, 1):
                b64 = base64.b64encode(svg.encode()).decode()
                st.markdown(f"**Pàgina {i}**")
                st.markdown(f'<img src="data:image/svg+xml;base64,{b64}" '
                            'style="width:100%;border:1px solid #ccc"/>', unsafe_allow_html=True)
    except Exception as e:
        st.error(str(e))

st.markdown("---")
st.subheader("Roadmap")
st.write("Fet: desplegament sense solapaments, peces que caben al paper, pestanyes, costures "
         "numerades, plecs de vall i muntanya. Següent: PDF d'impressió multipàgina, "
         "vista 3D amb les peces acolorides i triar a mà on tallar.")
