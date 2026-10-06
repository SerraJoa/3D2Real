import base64

import streamlit as st

import cares
import decor as dc
import laminacio
import laser
import papercraft as pc
import vista
import visor

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


def svg_img(svg: str, width: str = "100%") -> None:
    st.markdown(f'<img src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}" '
                f'style="width:{width}"/>', unsafe_allow_html=True)


def assembly_view(r, solids, key: str) -> None:
    """Vista 3D del model muntat; les dades s'empaqueten un cop per resultat."""
    cache = st.session_state.setdefault("_visor", {})
    if key not in cache or cache[key][0] is not r:
        cache[key] = (r, visor.pack(solids(r)))
    st.markdown("**Vista del muntatge**")
    visor.show([], key=f"visor_{key}", data=cache[key][1])


def ranges(ks: list[int]) -> str:
    """[0, 1, 2, 5] → "C1–C3, C6"."""
    out, start = [], None
    for i, k in enumerate(ks):
        if start is None:
            start = k
        if i == len(ks) - 1 or ks[i + 1] != k + 1:
            out.append(f"C{start + 1}" if start == k else f"C{start + 1}–C{k + 1}")
            start = None
    return ", ".join(out)


def decor_panel(m, frames, has_texture: bool, laser_branch: bool) -> dict:
    """Assignació de decoracions a les cares. Retorna {índex de cara: DecorSpec}."""
    sig = (len(m.faces), len(frames), round(float(m.area), 1))
    if st.session_state.get("decor_sig") != sig:  # la malla ha canviat: les cares també
        st.session_state["decor"] = {}
        st.session_state["decor_sig"] = sig
    decor: dict = st.session_state["decor"]
    with st.expander(f"🎨 Decoració de les cares ({len(decor)} decorades)", expanded=bool(decor)):
        v1, v2 = st.columns(2)
        with v1:
            svg_img(vista.faces_view(m, frames, set(decor), yaw=35, pitch=25), "95%")
        with v2:
            svg_img(vista.faces_view(m, frames, set(decor), yaw=215, pitch=-25), "95%")
        names = [f"C{fr.index + 1}" for fr in frames]
        chosen = st.multiselect("Cares", ["Totes"] + names, key="decor_faces")
        targets = list(range(len(frames))) if "Totes" in chosen else \
            [names.index(c) for c in chosen if c in names]
        kinds = (["textura"] if has_texture else []) + ["imatge", "patró", "dibuix"]
        kind = st.radio("Què", kinds, horizontal=True, key="decor_kind",
                        format_func={"textura": "Textura del model", "imatge": "Imatge",
                                     "patró": "Patró", "dibuix": "Dibuix a mà"}.get)
        spec = dc.DecorSpec(kind=kind)
        c1, c2 = st.columns(2)
        with c1:
            spec.frame = st.number_input("Marc (mm, 0 = sense marc)", 0.0, 50.0, 0.0, 0.5,
                                         key="decor_frame")
            if laser_branch:
                spec.laser = st.radio("Al làser", dc.LASER_MODES, horizontal=True, key="decor_laser",
                                      help="Tallar deixa sempre un marc de 3 mm com a mínim i "
                                           "respecta ranures i suports.")
        with c2:
            if kind == "imatge":
                up = st.file_uploader("Imatge", type=["png", "jpg", "jpeg"], key="decor_img")
                spec.image = up.getvalue() if up else None
                spec.fit = st.radio("Ajust", ["omplir", "encabir"], horizontal=True, key="decor_fit")
                if laser_branch:
                    spec.threshold = st.slider("Tallar: més fosc que", 0, 255, 128, key="decor_thr")
            elif kind == "patró":
                spec.pattern = st.selectbox("Patró", dc.PATTERNS, key="decor_pat")
                if spec.pattern == "text":
                    spec.text = st.text_input("Text", key="decor_text")
                elif spec.pattern != "color":
                    spec.spacing = st.number_input("Separació (mm)", 1.0, 100.0, 6.0, 0.5,
                                                   key="decor_sp")
                    spec.width = st.number_input("Gruix (mm)", 0.1, 20.0, 1.5, 0.1, key="decor_w")
                    if spec.pattern in ("ratlles", "quadrícula"):
                        spec.angle = st.slider("Angle (°)", 0, 180, 45, key="decor_ang")
                spec.color = st.color_picker("Color (paper)", "#1f4e79", key="decor_col")
            elif kind == "dibuix":
                spec.width = st.number_input("Gruix del traç (mm)", 0.1, 20.0, 1.0, 0.1,
                                             key="decor_dw")
                spec.color = st.color_picker("Color (paper)", "#1f4e79", key="decor_dcol")
        if kind == "dibuix":
            if len(targets) != 1:
                st.info("Tria una sola cara per dibuixar-hi.")
            else:
                import dibuix
                k = targets[0]
                prev = decor.get(k)
                old = prev.strokes if prev is not None and prev.kind == "dibuix" else []
                st.caption(f"Dibuixa sobre C{k + 1} (vista des de fora, amunt = amunt del model)")
                spec.strokes = dibuix.draw_on_face(frames[k].shape, f"dib_{k}_{sig}", old,
                                                   spec.color)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Aplica a les cares triades", disabled=not targets):
                if kind == "imatge" and not spec.image:
                    st.warning("Carrega una imatge primer.")
                else:
                    for k in targets:
                        decor[k] = spec
                    st.rerun()
        with b2:
            if st.button("Treu la decoració de les cares triades", disabled=not targets):
                for k in targets:
                    decor.pop(k, None)
                st.rerun()
        if decor:
            groups: dict = {}
            for k, d in sorted(decor.items()):
                desc = ({"textura": "textura", "imatge": "imatge", "dibuix": "dibuix"}.get(d.kind)
                        or f"patró {d.pattern}") + \
                    (f", marc {d.frame:g} mm" if d.frame else ", sense marc") + \
                    (f", {d.laser}" if laser_branch else "")
                groups.setdefault(desc, []).append(k)
            st.caption("Decorades — " + " · ".join(f"{ranges(ks)}: {desc}" for desc, ks in groups.items()))
    return decor


uploaded = st.file_uploader("Carrega el model: STL, OBJ (amb MTL i imatges per a la textura) o GLB",
                            type=["stl", "obj", "mtl", "glb", "gltf", "png", "jpg", "jpeg"],
                            accept_multiple_files=True)
models = [u for u in (uploaded or []) if u.name.lower().endswith((".stl", ".obj", ".glb", ".gltf"))]
if models:
    try:
        # ---- Fases comunes: importació i reducció
        files = {u.name: u.getvalue() for u in uploaded}
        if models[0].name.lower().endswith(".stl"):
            mesh, texture = pc.load_mesh(models[0].getvalue(), models[0].name), None
        else:
            mesh, texture = dc.load_textured({k: v for k, v in files.items()
                                              if k == models[0].name or
                                              not k.lower().endswith((".stl", ".obj", ".glb"))})
        st.success(f"{len(mesh.faces):,} cares · {len(mesh.vertices):,} vèrtexs"
                   + (" · amb textura" if texture is not None else ""))
        c1, c2 = st.columns(2)
        with c1:
            maxf = max(10, len(mesh.faces))
            target = st.slider("Simplificació — nombre de cares", 10, maxf, max(10, min(maxf, 300)))
        with c2:
            size = st.number_input("Mida final — costat més llarg (mm)", 20.0, 2000.0, 120.0, 10.0)
        prepared, _ = dc.prepare(mesh, target, size, None)
        frames = dc.face_frames(prepared)

        # ---- Vista del model: tal com s'ha carregat i com queda amb la simplificació
        cache = st.session_state.setdefault("_model_view", {})
        src = (models[0].name, len(models[0].getvalue()))
        if cache.get("src") != src:
            cache.clear()
            cache.update(src=src, original=visor.pack(visor.model_solids(mesh, "Model", "#9fb3c8")))
        if cache.get("simple_key") != (target, size):
            cache.update(simple_key=(target, size), simple=visor.pack(visor.model_solids(
                prepared, "Simplificat", "#dcc29a", edges="totes")))
        v1, v2 = st.columns(2)
        with v1:
            shown = cache["original"]["triangles"]
            st.markdown(f"**Model carregat** · {len(mesh.faces):,} cares"
                        + (f" (es mostra amb {shown:,})" if shown < len(mesh.faces) else ""))
            visor.show([], key="visor_original", height=320, data=cache["original"])
        with v2:
            st.markdown(f"**Simplificat** · {len(prepared.faces):,} cares · "
                        f"{max(prepared.extents):.0f} mm")
            visor.show([], key="visor_simplificat", height=320, data=cache["simple"])

        branch = st.radio("Branca", ["📄 Desplegable de paper", "🔷 Cares (làser)",
                                     "🥞 Laminació (làser)"], horizontal=True)

        decor = {} if branch.startswith("🥞") else \
            decor_panel(prepared, frames, texture is not None, not branch.startswith("📄"))

        if branch.startswith("📄"):
            c1, c2 = st.columns(2)
            with c1:
                page = st.selectbox("Paper", list(pc.PAGES))
                landscape = st.checkbox("Apaïsat")
                face_numbers = st.checkbox("Numerar les cares (C1, C2…)")
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
                        mesh, target, size, tab, page, landscape, face_numbers, lines, zones,
                        decor=decor, texture=texture)
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
                assembly_view(r, visor.paper_solids, "paper")
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
                    spacing = st.slider("Distància entre suports d'una mateixa aresta (mm)", 20, 200, 80,
                                        help="Amb els braços: pocs suports grans (distància i "
                                             "braços llargs) o molts de petits (curts i a prop), "
                                             "que caben millor a les plaques estretes.")
                    chamfer_mm = st.number_input("Xamfrà a les cantonades (mm)", 0.0, 10.0, 1.0, 0.5,
                                                 help="Talla les cantonades que punxen del contorn "
                                                      "de plaques, suports i costelles. Els forats, "
                                                      "ranures i osques no es toquen. 0 = sense.")
                    fast_ribs = st.checkbox("Cerca de costelles ràpida", False,
                                            help="Amb formes arrodonides (moltes plaques petites) la "
                                                 "cerca completa pot trigar molts minuts. La ràpida "
                                                 "prova menys plans i s'atura als 10 s, però pot "
                                                 "deixar més grups de plaques sense unir.")
                st.caption("Les cares van millor amb models de poques zones planes (caixes, poliedres). "
                           "Amb formes arrodonides i moltes cares, cada triangle és una placa: pot "
                           "trigar molts minuts: baixa la simplificació o tria la cerca de costelles ràpida.")
                if st.button("🚀 Generar cares", type="primary"):
                    with st.spinner("Tallant cares i suports…"):
                        st.session_state["cares"] = cares.make_faces(
                            mesh, target, size, thickness, gap, bracket, laser.SHEETS[sheet], joint,
                            decor=decor, texture=texture, fast_ribs=fast_ribs,
                            bracket_spacing=spacing, chamfer_mm=chamfer_mm)
                r, prefix = st.session_state.get("cares"), "cares"
                if r:
                    s = r.stats
                    st.success(f"{s['plaques']} plaques · {s['suports']} suports · "
                               f"{s['costelles']} costelles · {s['mitges_fustes']} mitges fustes · "
                               f"{s['ranures']} ranures · "
                               f"{s['planxes']} planxes")
                    if s["grups_de_plaques"] > 1:
                        st.warning(f"Les plaques queden en {s['grups_de_plaques']} grups sense "
                                   "suport entre ells (a la vista, un color per grup): hi ha "
                                   "plaques massa petites per a suports.")
                    assembly_view(r, visor.cares_solids, "cares")
            else:
                with c2:
                    column = st.number_input("Diàmetre de les tiges (mm)", 1.0, 20.0, 5.0, 0.5)
                    wall = st.number_input("Buidar: gruix de paret (mm, 0 = massís)", 0.0, 50.0,
                                           6.0, 0.5,
                                           help="Les capes es buiden deixant aquesta paret per tots "
                                                "costats.")
                    align = st.radio("Alineació", ["costella", "columnes"], horizontal=True,
                                     help="Costella: una peça vertical dins la cavitat que encaixa "
                                          "en osques de la paret de cada capa (cal buidar). "
                                          "Columnes: tiges passants.")
                if st.button("🚀 Generar capes", type="primary"):
                    with st.spinner("Tallant capes…"):
                        st.session_state["capes"] = laminacio.make_layers(
                            mesh, target, size, thickness, column, laser.SHEETS[sheet], wall,
                            align)
                r, prefix = st.session_state.get("capes"), "capes"
                if r:
                    s = r.stats
                    st.success(f"{s['capes']} capes · {s['peces']} peces · {s['costelles']} "
                               f"costelles · {s['columnes']} columnes · "
                               f"{s['estalvi']} % de material estalviat · "
                               f"{s['planxes']} planxes")
                    if s["peces_sense_columna"] or s["peces_amb_una_columna"]:
                        st.warning(f"{s['peces_amb_una_columna']} peces amb una sola columna i "
                                   f"{s['peces_sense_columna']} sense cap (massa estretes): "
                                   "alinea-les amb el contorn gravat.")
                    assembly_view(r, visor.layers_solids, "capes")
            if r:
                if r.stats["massa_grans"]:
                    st.warning(f"{r.stats['massa_grans']} peces no caben a la planxa.")
                st.download_button("⬇️ Descarrega les planxes (SVG + muntatge en un ZIP)",
                                   r.zip_bytes(prefix), f"{prefix}.zip", "application/zip")
                st.info("Vermell = tallar · blau = gravar · verd = només referència (plaques "
                        "amb gravat decoratiu: es tallen amb la cara de fora amunt).")
                with st.expander("Instruccions de muntatge"):
                    st.text("\n".join(r.notes))
                show(r.sheets, "Planxa")
    except Exception as e:
        st.error(str(e))
