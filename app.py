import base64

import streamlit as st

import cares
import imatge3d
import decor as dc
import laminacio
import laser
import papercraft as pc
import reduccio
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


MAX_FACES = 1000  # el lliscador de simplificació arriba fins aquí


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


class _Fitxer:
    """Fitxer en memòria amb la mateixa interfície que un d'`st.file_uploader`."""

    def __init__(self, name: str, data: bytes):
        self.name, self._data = name, data

    def getvalue(self) -> bytes:
        return self._data


uploaded = st.file_uploader("Carrega el model: STL, OBJ (amb MTL i imatges per a la textura) o GLB",
                            type=["stl", "obj", "mtl", "glb", "gltf", "png", "jpg", "jpeg"],
                            accept_multiple_files=True)
with st.expander("📷 O crea'l des d'una imatge", expanded=False):
    st.caption("Genera una malla 3D amb Hunyuan3D 2.1 a través d'un ComfyUI en marxa. "
               "La part de darrere la inventa el model; triga uns minuts.")
    comfy = st.text_input("Adreça de ComfyUI", "http://127.0.0.1:8188")
    origen = st.radio("Imatge", ["Pujar-la", "Generar-la amb un prompt"], horizontal=True,
                      key="img_origen")
    img_up = None
    if origen == "Pujar-la":
        img_up = st.file_uploader("Imatge de l'objecte (millor sol i sobre fons net)",
                                  type=["png", "jpg", "jpeg", "webp"], key="img3d")
    else:
        g1, g2 = st.columns([3, 1])
        prompt = g1.text_input("Què vols", placeholder="una guineu asseguda", key="img_prompt")
        estil = g2.selectbox("Estil", list(imatge3d.ESTILS), key="img_estil",
                             help="Low poly força cares planes i pocs polígons: segmenta i "
                                  "redueix millor. Normal dóna més detall.")
        if st.button("Genera la imatge", disabled=not prompt.strip()):
            try:
                with st.spinner("Generant la imatge…"):
                    png = imatge3d.genera_imatge(prompt.strip(), estil, comfy)
                st.session_state["img_generada"] = _Fitxer(
                    prompt.strip()[:30].replace(" ", "_") + ".png", png)
            except Exception as e:
                st.error(str(e))
        img_up = st.session_state.get("img_generada")
        if img_up is not None:
            st.image(img_up.getvalue(), width=320)
    if img_up is not None and st.button("Genera el model 3D"):
        try:
            with st.spinner("Generant la malla…"):
                glb = imatge3d.genera(img_up.getvalue(), comfy)
            st.session_state["glb_generat"] = _Fitxer(img_up.name.rsplit(".", 1)[0] + "_3d.glb", glb)
        except Exception as e:
            st.error(str(e))
    if "glb_generat" in st.session_state:
        st.success(f"Model generat: {st.session_state['glb_generat'].name} "
                   "(s'usa mentre no en carreguis cap altre)")
if not uploaded and "glb_generat" in st.session_state:
    uploaded = [st.session_state["glb_generat"]]
models = [u for u in (uploaded or []) if u.name.lower().endswith((".stl", ".obj", ".glb", ".gltf"))]

def lamp_controls(prefix: str, size: float, with_len: bool):
    """Controls del portalàmpades intern. Retorna el dict per a make_faces / make_layers, o None."""
    if not st.checkbox("💡 Portalàmpades intern", False, key=f"{prefix}_lamp",
                       help="Un pas circular per al portalàmpades i, opcional, un canal de l'amplada "
                            "d'un suport concret per lliscar-hi."):
        return None
    d = st.number_input("Ø del pas circular (mm)", 5.0, 200.0, 40.0, 1.0, key=f"{prefix}_ld")
    slot = st.number_input("Amplada del canal (mm, 0 = cap)", 0.0, 100.0, 0.0, 0.5, key=f"{prefix}_ls",
                           help="Canal des del pas cap a fora, per lliscar-hi un suport concret.")
    angle = st.slider("Direcció del canal (°)", 0, 359, 0, key=f"{prefix}_la") if slot > 0 else 0
    z = st.number_input("Alçada des de la base (mm)", 0.0, float(size) * 3, round(size * 0.2), 1.0,
                        key=f"{prefix}_lz")
    out = dict(d=d, slot=slot, angle=angle, z=z)
    if with_len:
        out["len"] = st.number_input("Llargada del pas (mm)", 1.0, float(size) * 3, 30.0, 1.0, key=f"{prefix}_ll")
    cx, cy = st.columns(2)
    out["x"] = cx.number_input("Desplaçament X (mm)", -500.0, 500.0, 0.0, 1.0, key=f"{prefix}_lx")
    out["y"] = cy.number_input("Desplaçament Y (mm)", -500.0, 500.0, 0.0, 1.0, key=f"{prefix}_ly")
    return out

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
        loose = pc.small_parts(mesh)
        if loose.any() and st.checkbox(
                f"Treure {int(loose.sum()):,} cares de peces soltes menudes", True,
                help="Filaments o restes soltes (menys del 2 % de l'àrea de la peça més gran): "
                     "s'haurien de retallar i muntar com a peces a part."):
            mesh = pc.keep_faces(mesh, ~loose)
            texture = texture.keep(~loose) if texture is not None else None
        st.success(f"{len(mesh.faces):,} cares · {len(mesh.vertices):,} vèrtexs"
                   + (" · amb textura" if texture is not None else ""))

        # ---- Orientació: quin eix del fitxer va amunt i quant gira al voltant de la vertical
        is_gltf = models[0].name.lower().endswith((".glb", ".gltf"))
        with st.expander("🧭 Orientació del model", expanded=False):
            o1, o2 = st.columns(2)
            with o1:
                up = st.selectbox("Eix del fitxer que va amunt", ["auto", *pc.UPS], 0,
                                  help="Auto: +Y per als GLB/glTF (es desen amb la Y amunt) i +Z "
                                       "per a la resta.")
            with o2:
                turn = st.select_slider("Gir al voltant de la vertical (°)", [0, 90, 180, 270], 0)
            orient = (("+Y" if is_gltf else "+Z") if up == "auto" else up, turn)
            mesh.apply_transform(pc.orientation_matrix(*orient))
            st.download_button("⬇️ Descarrega el model reorientat (GLB)", mesh.export(file_type="glb"),
                               models[0].name.rsplit(".", 1)[0] + "_reorientat.glb",
                               "model/gltf-binary")
        c1, c2 = st.columns(2)
        with c1:
            maxf = max(10, min(len(mesh.faces), MAX_FACES))
            target = st.slider("Simplificació — nombre de cares", 10, maxf, max(10, min(maxf, 300)),
                               help=f"Fins a {MAX_FACES} (més ja no es pot retallar ni muntar). "
                                    "Es treuen primer les cares que continuen les veïnes sense "
                                    "canviar d'inclinació, i al final les vores i els detalls.")
        with c2:
            size = st.number_input("Mida final — costat més llarg (mm)", 20.0, 2000.0, 120.0, 10.0)
        r1, r2, r3, r4 = st.columns([2, 1, 1, 1])
        with r1:
            method = st.radio("Reducció", ["Respecta la forma", "Ràpida"], horizontal=True,
                              help="Respecta la forma: dona més triangles als detalls (relleu, "
                                   "vores i el dibuix de la textura: ulls, boca…) i tracta igual "
                                   "les zones equivalents. Ràpida: només l'error geomètric global. "
                                   "Totes dues treuen primer les cares que continuen les veïnes "
                                   "sense canviar d'inclinació.")
        with r2:
            sym = st.selectbox("Simetria", ["no", "auto", "x", "y", "z"],
                               disabled=method != "Respecta la forma",
                               help="No (per defecte): no se n'imposa cap. Auto: si el model ja "
                                    "és simètric, el resultat ho serà exactament. x, y o z: la "
                                    "força amb el pla pel centre.")
        with r3:
            detail = st.slider("Pes dels detalls", 0, 60, 30, disabled=method != "Respecta la forma",
                               help="Quant costa simplificar el relleu, les vores i el dibuix de "
                                    "la textura respecte de la resta (0 = com la ràpida).")
        with r4:
            harm = st.checkbox("Harmonitzar", True, disabled=method != "Respecta la forma",
                               help="Pas final: gira arestes i relaxa vèrtexs perquè els triangles "
                                    "siguin més regulars (menys de prims), sense moure les vores "
                                    "vives ni sortir de la superfície. No s'aplica amb simetria.")
            flat = st.checkbox("Aplanar", True, disabled=method != "Respecta la forma",
                               help="Posa al mateix pla les cares veïnes que ja són gairebé "
                                    "coplanars (una base, el lateral d'una pota): es tallen com "
                                    "una sola placa i el desplegable no les parteix.")
        src = (models[0].name, len(models[0].getvalue()), orient)
        if method == "Respecta la forma" and len(mesh.faces) > target:
            red_cache = st.session_state.setdefault("_reduccio", {})
            key = (src, target, sym, detail, harm, flat)
            if key not in red_cache:
                red_cache.clear()
                with st.spinner("Reduint la malla respectant la forma…"):
                    red_cache[key] = reduccio.reduce(mesh, target, sym, float(detail), texture,
                                                     mesh if texture is not None else None, harm, flat)
            reduced, red_info = red_cache[key]
            # Les branques fan servir aquesta reducció (papercraft.simplify la reconeix).
            mesh.metadata["reduccio"] = (target, reduced)
            if red_info["simetria"]:
                st.caption(f"Simetria trobada: pla perpendicular a {red_info['simetria']['normal']}"
                           f" (desviació {100 * red_info['simetria']['error']:.1f} % de la mida).")
            elif sym != "no":
                st.caption("El model no és simètric (o no hi cap amb tan poques cares): es "
                           "redueix sencer.")
        prepared, _ = dc.prepare(mesh, target, size, None)
        frames = dc.face_frames(prepared)

        # ---- Vista del model: tal com s'ha carregat i com queda amb la simplificació
        cache = st.session_state.setdefault("_model_view", {})
        if cache.get("src") != src:
            cache.clear()
            cache.update(src=src, original=visor.pack(visor.model_solids(mesh, "Model", "#9fb3c8")))
        if cache.get("simple_key") != (target, size, method, sym, detail, harm, flat):
            cache.update(simple_key=(target, size, method, sym, detail, harm, flat), simple=visor.pack(visor.model_solids(
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
                sheet = st.selectbox("Planxa (mm)", [*laser.SHEETS, "Lliure"])
                if sheet == "Lliure":
                    s1, s2 = st.columns(2)
                    sheet_mm = (s1.number_input("Amplada (mm)", 20.0, 5000.0, 600.0, 10.0, key="sheet_w"),
                                s2.number_input("Alçada (mm)", 20.0, 5000.0, 400.0, 10.0, key="sheet_h"))
                else:
                    sheet_mm = laser.SHEETS[sheet]
            if branch.startswith("🔷"):
                with c2:
                    gap = st.number_input("Espai entre cares (mm)", 0.0, 50.0, 0.0, 0.5,
                                          help="Per a làmpades: deixa passar la llum entre plaques.")
                    joint = st.radio("Suports", ["encaix", "cola"], horizontal=True,
                                     help="Encaix: arc amb tenons que entren en ranures de les "
                                          "plaques (els tenons es veuen per fora). Cola: estel "
                                          "enganxat per dins, del tot invisible.")
                    plate_mm = cares.plate_scale(prepared)
                    sizing = st.radio("Mida dels suports", ["Automàtica (escala)", "Manual"],
                                      horizontal=True,
                                      help="Automàtica: el braç surt de la placa mitjana dividida per "
                                           "l'escala, i per defecte un suport centrat per aresta.")
                    if sizing.startswith("Auto"):
                        ratio = st.slider("Escala placa mitjana / braç", 1.0, 4.0, 2.0, 0.1,
                                          help="2 = el braç fa la meitat de la placa mitjana. Més "
                                               "alt: suports més petits i més fàcils d'encabir; "
                                               "per sota d'1,5 és fàcil que les plaques es "
                                               "quedin soltes.")
                        bracket = int(cares.auto_bracket(plate_mm, ratio, thickness))
                        per = st.selectbox("Suports per aresta", ["1 centrat", "2", "3", "segons la distància"],
                                           help="Els suports es reparteixen simètricament des del "
                                                "mig cap als costats.")
                        per_edge = {"1 centrat": 1, "2": 2, "3": 3}.get(per, 0)
                        spacing = st.slider("Distància (si és segons la distància, mm)", 20, 200, 80,
                                            disabled=per_edge > 0)
                    else:
                        bracket = st.slider("Llargada dels braços dels suports (mm)", 8, 60, 25)
                        per_edge = 0
                        spacing = st.slider("Distància entre suports d'una mateixa aresta (mm)", 20, 200, 80,
                                            help="Amb els braços: pocs suports grans (distància i "
                                                 "braços llargs) o molts de petits (curts i a prop), "
                                                 "que caben millor a les plaques estretes.")
                    escala = plate_mm / bracket
                    (st.success if escala >= 2 else st.warning if escala >= 1.5 else st.error)(
                        f"Placa mitjana {plate_mm:.0f} mm · braç {bracket} mm · escala "
                        f"{escala:.1f}" + ("" if escala >= 1.5 else
                                           " — massa justa: baixa les cares o escurça el braç"))
                    chamfer_mm = st.slider("Xamfrà de les plaques (mm)", 0.0, 10.0, 1.0, 0.5,
                                           help="Talla les cantonades que punxen de les plaques, "
                                                "per a l'efecte (sobretot amb llum a dins). Amb "
                                                "espai entre cares, la punta de cada suport omple "
                                                "l'escletxa fins a fora i aquest és el radi de la "
                                                "seva cantonada. 0 = sense.")
                    merge_small = st.slider("Fusiona plaques més petites que (gruixos)", 0.0, 8.0, 4.0, 0.5,
                                            help="Les plaques on no hi cap un cercle d'aquests "
                                                 "gruixos de diàmetre no poden rebre suports: es "
                                                 "fusionen amb la veïna més propera, si es pot sense "
                                                 "deformar el model massa. 0 = no. No s'aplica "
                                                 "amb textura.")
                    grip = st.checkbox("Agafa les plaques petites pels extrems", True,
                                       help="Si el braç no hi cap sencer en una placa petita, es posa "
                                            "igualment recolzat a mitges i enganxat, sense tenó.")
                    fill_gap = st.checkbox("Les puntes dels suports omplen l'escletxa (es veuen per fora)",
                                           False, help="Només té sentit amb espai entre cares. "
                                                       "Desactivat: suports del tot per dins.")
                    tenon_chamfer = st.slider("Xamfrà dels tenons (mm)", 0.0, 1.5, 0.5, 0.1,
                                              help="A les puntes dels tenons de suports i "
                                                   "costelles, perquè entrin més fàcilment a les "
                                                   "ranures (0,5–1 mm).")
                    fast_ribs = st.checkbox("Cerca de costelles ràpida", False,
                                            help="Amb formes arrodonides (moltes plaques petites) la "
                                                 "cerca completa pot trigar molts minuts. La ràpida "
                                                 "prova menys plans i s'atura als 10 s, però pot "
                                                 "deixar més grups de plaques sense unir.")
                    lamp = lamp_controls("cares", size, False)
                    paper = st.checkbox("🗒️ Paper difusor per dins (tires per escletxa)", False,
                                        help="Tires de paper que s'enganxen per dins i tapen les escletxes "
                                             "entre plaques, amb osques per esquivar els suports. Surten "
                                             "en planxes a part, per a tallar en paper.")
                st.caption("Les cares van millor amb models de poques zones planes (caixes, poliedres). "
                           "Amb formes arrodonides i moltes cares, cada triangle és una placa: pot "
                           "trigar molts minuts: baixa la simplificació o tria la cerca de costelles ràpida.")
                if st.button("🚀 Generar cares", type="primary"):
                    with st.spinner("Tallant cares i suports…"):
                        st.session_state["cares"] = cares.make_faces(
                            mesh, target, size, thickness, gap, bracket, sheet_mm, joint,
                            decor=decor, texture=texture, fast_ribs=fast_ribs,
                            bracket_spacing=spacing, chamfer_mm=chamfer_mm,
                            tenon_chamfer=tenon_chamfer, fill_gap=fill_gap, merge_small=merge_small, per_edge=per_edge, grip=grip,
                            lamp=lamp, paper=paper)
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
                    lamp = lamp_controls("capes", size, True)
                if st.button("🚀 Generar capes", type="primary"):
                    with st.spinner("Tallant capes…"):
                        st.session_state["capes"] = laminacio.make_layers(
                            mesh, target, size, thickness, column, sheet_mm, wall,
                            align, lamp=lamp)
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
                out = st.radio("Sortida", ["Làser / CNC", "Impressora 3D"], horizontal=True,
                               key=f"sortida_{prefix}")
                if out == "Làser / CNC":
                    st.download_button("⬇️ Descarrega les planxes (SVG + muntatge en un ZIP)",
                                       r.zip_bytes(prefix), f"{prefix}.zip", "application/zip")
                    st.info("Vermell = tallar · blau = gravar · verd = només referència (plaques "
                            "amb gravat decoratiu: es tallen amb la cara de fora amunt).")
                else:
                    b1, b2 = st.columns(2)
                    bed = (b1.number_input("Llit X (mm)", 20.0, 1000.0, 220.0, 10.0, key=f"bx_{prefix}"),
                           b2.number_input("Llit Y (mm)", 20.0, 1000.0, 220.0, 10.0, key=f"by_{prefix}"))
                    data, big = r.stl_zip(prefix, bed)
                    st.download_button("⬇️ Descarrega els STL (una peça per fitxer, plana)",
                                       data, f"{prefix}_stl.zip", "application/zip")
                    if big:
                        st.warning(f"No caben al llit: {', '.join(big)}.")
                    st.info("Cada peça va tombada amb la cara plana al llit i el gruix del "
                            "material com a alçada. Els encaixos tenen 0,1 mm de joc: ajusta'l "
                            "a la teva impressora si cal.")
                with st.expander("Instruccions de muntatge"):
                    st.text("\n".join(r.notes))
                show(r.sheets, "Planxa")
    except Exception as e:
        st.error(str(e))
