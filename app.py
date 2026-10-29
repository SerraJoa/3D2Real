import base64
import io
import math
import traceback
import zipfile

import numpy as np
import streamlit as st

import cares
import imatge3d
import decor as dc
import laminacio
import massissa
import laser
import papercraft as pc
import reduccio
import vista
import visor
from ui import carpeta, cparam, disseny, encaix, orientacio, pintura, portada, recursos, uv

st.set_page_config(page_title="Desplegables", layout="wide", initial_sidebar_state="collapsed")
with st.sidebar:
    st.header("⚙️ Configuració")
    st.text_input("Adreça de ComfyUI", "http://127.0.0.1:8188", key="comfy_url",
                  help="Servidor que genera les imatges i els models 3D a partir d'una imatge.")


if not portada.mostra():   # producte i tecnologia de sortida, pas a pas
    st.stop()


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


class _Fitxer:
    """Fitxer en memòria amb la mateixa interfície que un d'`st.file_uploader`."""

    def __init__(self, name: str, data: bytes):
        self.name, self._data = name, data

    def getvalue(self) -> bytes:
        return self._data


branch = {"desplegables": "📄 Desplegable de paper", "cares": "🔷 Cares (làser)",
          "capes": "🥞 Laminació (làser)"}[st.session_state["producte"]]
simplify_on = not branch.startswith("🥞")   # les capes tallen el model original
cares_on = branch.startswith("🔷")
out = portada.sortida_valor(st.session_state["producte"], st.session_state["sortida"])
# On va cada família de peces: "CNC" o "3D". A Cares, en mode Mixta es trien per separat.
plates_out = supports_out = "CNC" if out in ("Làser / CNC", "CNC / làser") else "3D"

ss = st.session_state
st.markdown("<style>.st-key-ia_caixa, .st-key-ia_caixa_img {background: rgba(124, 92, 214, 0.12); "
            "border: 1px solid rgba(124, 92, 214, 0.45); border-radius: 10px; padding: 0.8rem 1rem; "
            "margin: 0.4rem 0 0.8rem;}</style>", unsafe_allow_html=True)
origen = ss["origen"]
MODELS = (".stl", ".obj", ".glb", ".gltf")
if "fitxers" not in ss:   # el model arriba des de la targeta del pas: pàgina pròpia, no l'espai de treball
    _, mig, _ = st.columns([1, 2, 1])
    if origen == "model":
        portada.capcalera("Carrega el model", "STL, OBJ (amb MTL i imatges per a la textura) o GLB.")
        with mig:
            pujats = st.file_uploader("Model", type=["stl", "obj", "mtl", "glb", "gltf", "png", "jpg", "jpeg"],
                                      accept_multiple_files=True, label_visibility="collapsed")
            triats = carpeta.tria(MODELS, "model_carpeta")
            if triats and not pujats:   # el model de la carpeta porta els MTL i imatges del costat
                pujats = triats + carpeta.germans(triats[0], (".mtl", ".png", ".jpg", ".jpeg"))
        if any(u.name.lower().endswith(MODELS) for u in pujats):
            ss["fitxers"] = {u.name: u.getvalue() for u in pujats}
            st.rerun()
    else:
        # Imatge → model 3D (Hunyuan3D 2.1 via ComfyUI): la imatge s'accepta i el model surt sol.
        comfy = ss["comfy_url"]
        de_carpeta = ss["via"] == "carpeta"
        portada.capcalera("Carrega la imatge" if de_carpeta else "Descriu què vols",
                          "Millor l'objecte sol i sobre fons net." if de_carpeta else
                          "Escriu què vols veure i tria l'estil; en genera una imatge.")
        with mig:
            if de_carpeta:
                img_up = st.file_uploader("Imatge", type=["png", "jpg", "jpeg", "webp"], key="img3d",
                                          label_visibility="collapsed")
                if img_up is None:
                    triades = carpeta.tria((".png", ".jpg", ".jpeg", ".webp"), "img3d_carpeta")
                    img_up = triades[0] if triades else None
            else:
                with st.container(key="ia_caixa_img"):
                    st.caption("🤖 Amb IA: necessita ComfyUI i una GPU (Hunyuan3D / Z-Image).")
                    prompt = st.text_input("Què vols", placeholder="una guineu asseguda", key="img_prompt")
                    estil = st.selectbox("Estil", list(imatge3d.ESTILS), key="img_estil",
                                         help="Low poly força cares planes i pocs polígons: segmenta i "
                                              "redueix millor. Normal dóna més detall.")
                    if st.button("Genera la imatge", disabled=not prompt.strip(), use_container_width=True):
                        try:
                            with st.spinner("Generant la imatge…"):
                                png = imatge3d.genera_imatge(prompt.strip(), estil, comfy)
                            ss["img_generada"] = _Fitxer(prompt.strip()[:30].replace(" ", "_") + ".png", png)
                        except Exception as e:
                            st.error(str(e))
                img_up = ss.get("img_generada")
            if img_up is not None:
                st.image(img_up.getvalue(), use_container_width=True)
                with st.container(key="ia_caixa"):
                    st.caption("🤖 Amb IA: el model 3D es genera amb ComfyUI i una GPU. Sense GPU, "
                               "carrega el model (STL, OBJ o GLB) des de l'inici.")
                    nitida = st.checkbox("Malla nítida (cares planes)", False, key="img_nitida",
                                         help="Extreu la superfície del camp en brut de Hunyuan, sense "
                                              "suavitzar: conserva facetes i arestes vives. Cal el node "
                                              "SaveVoxelNpy (comfy_nodes/) a ComfyUI.")
                    detalls_fora = st.checkbox("Treu els detalls fins abans del 3D (millor malla)", False,
                                               key="img_sense_detalls",
                                               help="Una IA (FLUX.2 Klein, ~1 min) treu ulls, nas i boca de la imatge i "
                                                    "Hunyuan genera la malla des d'aquesta versió; la pell surt de "
                                                    "l'original. Només amb la malla nítida.",
                                               disabled=not nitida)
                if st.button("Accepta la imatge i continua", type="primary", use_container_width=True):
                    barra = st.progress(0.0, text="Generant el model 3D…")

                    def avanca(t: float) -> None:  # ComfyUI no diu l'avanç: estimació que s'acosta al 95 %
                        barra.progress(0.95 * (1 - math.exp(-t / 150)),
                                       text=f"Generant el model 3D… {int(t)} s (uns minuts)")
                    try:
                        glb = (imatge3d.genera_nitida if nitida else imatge3d.genera)(
                            img_up.getvalue(), comfy, progres=avanca, **({"detalls_fora": True} if nitida and detalls_fora else {}))
                        nom_glb = img_up.name.rsplit(".", 1)[0] + "_3d.glb"
                        ss["fitxers"] = {nom_glb: glb}
                        ss["recursos_origen"] = [("⬇️ Imatge d'origen", img_up.getvalue(), img_up.name, "image/jpeg" if img_up.name.lower().endswith((".jpg", ".jpeg")) else "image/png"),
                                                 ("⬇️ Model generat (GLB)", glb, nom_glb, "model/gltf-binary")]
                        for _t, dades_, nom_, _m in ss["recursos_origen"]:
                            carpeta.desa(nom_, dades_)
                        st.rerun()
                    except RuntimeError as e:
                        barra.empty()
                        st.error(str(e))
    st.stop()
uploaded = [_Fitxer(n, b) for n, b in ss["fitxers"].items()]
models = [u for u in uploaded if u.name.lower().endswith(MODELS)]

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

def malla_controls(nfaces: int):
    """Opcions de la malla: mida final i simplificació (només si el producte simplifica)."""
    size = st.number_input("Mida final — costat més llarg (mm)", 20.0, 2000.0, 120.0, 10.0)
    if simplify_on:
        maxf = max(10, min(nfaces, MAX_FACES))
        target = st.slider("Simplificació — nombre de cares", 10, maxf, max(10, min(maxf, 300)),
                           help=f"Fins a {MAX_FACES} (més ja no es pot retallar ni muntar). "
                                "Es treuen primer les cares que continuen les veïnes sense "
                                "canviar d'inclinació, i al final les vores i els detalls.")
    else:
        target = nfaces   # capes: es talla el model original, sense simplificar
        method, sym, detail, harm, flat, estr = "Ràpida", "no", 0, False, False, False
    if simplify_on:
        r1 = r2 = r3 = r4 = st.container()
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
            off = method != "Respecta la forma"
            harm = st.checkbox("Harmonitzar", True, disabled=off,
                               help="Pas final: gira arestes i relaxa vèrtexs perquè els triangles "
                                    "siguin més regulars (menys de prims), sense moure les vores "
                                    "vives ni sortir de la superfície. No s'aplica amb simetria.")
            harm_t = st.slider("Tolerància de pla (°)", 1.0, 30.0, 8.0, 0.5, disabled=off or not harm,
                               help="Dos triangles veïns que difereixen menys d'aquest angle es "
                                    "consideren al mateix pla i es poden girar per regularitzar-los. "
                                    "Més alt = més regularització, però pot arrodonir arestes suaus.")
            flat = st.checkbox("Aplanar", True, disabled=off,
                               help="Posa al mateix pla les cares veïnes que ja són gairebé "
                                    "coplanars (una base, el lateral d'una pota): es tallen com "
                                    "una sola placa i el desplegable no les parteix.")
            flat_a = st.slider("Aplanar: angle màxim (°)", 1.0, 30.0, 8.0, 0.5, disabled=off or not flat,
                               help="Màxima inclinació de les cares que s'ajunten en un pla.")
            flat_d = st.slider("Aplanar: distància màxima (% mida)", 0.1, 5.0, 1.2, 0.1,
                               disabled=off or not flat,
                               help="Màxima distància d'un vèrtex al pla ajustat, en % de la diagonal.")
            estr = st.checkbox("Treure estretes", True, disabled=off,
                               help="Elimina els triangles llargs i estrets i petits, que aporten poc i "
                                    "compliquen el muntatge: se'n col·lapsa l'aresta curta i els veïns "
                                    "s'hi adapten, només si la forma gairebé no canvia. No s'aplica amb simetria.")
            estr_d = st.slider("Estretes: desviació màxima (% mida)", 0.1, 3.0, 0.8, 0.1,
                               disabled=off or not estr,
                               help="Quant pot allunyar-se de la forma original el vèrtex que queda. "
                                    "Més alt = en treu més, a canvi de més deformació.")
            estr_q = st.slider("Estretes: estretor", 0.1, 0.6, 0.3, 0.05, disabled=off or not estr,
                               help="Qualitat màxima d'un triangle per considerar-lo estret (1 = equilàter). "
                                    "Més alt = en considera estretes més.")
            # False = no es fa; si no, la tolerància (vegeu `reduccio.reduce`)
            harm = harm_t if harm else False
            flat = (flat_a, flat_d) if flat else False
            estr = (estr_d, estr_q) if estr else False
    return size, target, method, sym, detail, harm, flat, estr


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
        loose = pc.small_parts(mesh)   # filaments i restes soltes (< 2 % de la peça més gran)
        if loose.any():
            mesh = pc.keep_faces(mesh, ~loose)
            texture = texture.keep(~loose) if texture is not None else None

        # ---- Orientació: sis vistes (eix amunt) i un lliscador de gir; en clicar-ne una, continua
        is_gltf = models[0].name.lower().endswith((".glb", ".gltf"))
        sig = (models[0].name, len(models[0].getvalue()))
        if ss.get("orient_sig") != sig:
            for k in ("orient", "orient_mini", "encaix", "encaix_mini", "encaix_tipus", "uv", "uv_mini", "uv_import", "malla", "malla_mini", "cmat", "cmat_mini", "ccar", "ccar_mini", "csup", "csup_mini", "veure", "pantalla", "tecnic", "tecnic_mini", "recursos", "desplegat_html", "vista_tex", "disseny", "disseny_mini"):
                ss.pop(k, None)
            ss["orient_sig"] = sig
        if "orient" not in ss:
            portada.capcalera("Com ha d'anar col·locat?",
                              "Tria quina cara va cap amunt i gira'l amb el lliscador. "
                              "Clica la vista que vulguis per continuar.")
            triada = orientacio.tria(mesh, "+Y" if is_gltf else "+Z")
            if triada:
                up, turn = triada
                ss["orient"] = triada
                ss["orient_mini"] = (f"{up} · {turn:g}°", orientacio.miniatura(mesh, up, turn))
                st.rerun()
            st.stop()
        up, turn = ss["orient"]
        orient = (up, turn, 0, 0)
        mesh.apply_transform(pc.orientation_matrix(*orient))
        # ---- Encaix: terra, paret, sostre o cantonada, amb gir i profunditat
        if "encaix" not in ss:
            triat = encaix.tria(mesh)
            if triat:
                ss["encaix"] = triat
                ss["encaix_mini"] = (encaix.etiqueta(*triat),
                                     encaix.uri(encaix.escena_svg(mesh, triat[0], triat[1], width=200)))
                st.rerun()
            st.stop()
        enc = ss["encaix"]
        mesh0 = mesh.copy()   # orientada i sense tallar: la UV s'hi refereix
        M = encaix.moviment(mesh0, enc[1])
        talls = encaix.plans_tallats(mesh0, enc[0], enc[1]) if enc[2] else []
        mesh = encaix.talla(mesh, *enc)   # plans realment tallats amb cara: la reducció en refà la tapa
        orient += enc

        # ---- UV: es tria al Disseny (final); aquí només queda la que porta el fitxer
        model_tex = texture
        texture = None

        def textura_uv():
            """Textura passada a la malla tallada, segons la UV triada al Disseny (o None)."""
            uvk = ss.get("uv", "uvcap")
            if uvk == "uvcap" or (uvk == "uvimporta" and "uv_import" not in ss) \
                    or (uvk == "uvmodel" and model_tex is None):
                return None
            if uvk == "uvmodel" and not any(enc[1]):
                return model_tex
            clau = (sig, orient, uvk, len(ss["uv_import"][0].faces) if uvk == "uvimporta" else 0)
            if ss.get("uv_tex_clau") != clau:
                with st.spinner("Passant la UV a la malla…"):
                    if uvk == "uvimporta":
                        imp, imp_tex = ss["uv_import"]
                        src_m = uv.aliniar(imp, mesh0, pc.orientation_matrix(up, turn, 0, 0), M)
                        img, src_uv = imp_tex.image, imp_tex.face_uv
                    else:
                        src_m = mesh0.copy()
                        src_m.apply_transform(M)
                        img, src_uv = model_tex.image, model_tex.face_uv
                    ss["uv_tex_clau"] = clau
                    ss["uv_tex"] = dc.Texture(img, uv.transfer(src_m, src_uv, mesh))
            return ss["uv_tex"]

        def textura_prep():
            """La UV triada, passada a la malla simplificada i a mida (la dels dissenys per cara)."""
            t = textura_uv()
            if t is None:
                return None
            clau = ("uv_prep", ss.get("uv_tex_clau"), len(prepared.faces), round(float(prepared.area), 1))
            if ss.get("uv_prep_clau") != clau:
                src_m = mesh.copy()
                src_m.apply_scale(float(max(prepared.extents)) / float(max(mesh.extents)))
                src_m.apply_translation(prepared.bounds.mean(0) - src_m.bounds.mean(0))
                ss["uv_prep"] = dc.Texture(t.image, uv.transfer(src_m, t.face_uv, prepared))
                ss["uv_prep_clau"] = clau
            return ss["uv_prep"]

        # ---- Malla: model simplificat gran a l'esquerra i, a la vora, les opcions; en continuar
        # ---- es desen i l'espai de treball queda per a la figura
        src = (models[0].name, len(models[0].getvalue()), orient)
        malla = ss.get("malla")
        if malla is None:
            vista_col, ctrl_col = st.columns([3, 2], gap="large")
            with ctrl_col:
                malla = malla_controls(len(mesh.faces))
            ctx = ctrl_col
        else:
            ctx = st.container()
        size, target, method, sym, detail, harm, flat, estr = malla
        with ctx:
            if simplify_on:
                if method == "Respecta la forma" and len(mesh.faces) > target:
                    red_cache = st.session_state.setdefault("_reduccio", {})
                    key = (src, target, sym, detail, harm, flat, estr)
                    if key not in red_cache:
                        red_cache.clear()
                        with st.spinner("Reduint la malla respectant la forma…"):
                            red_cache[key] = reduccio.reduce(mesh, target, sym, float(detail), texture,
                                                             mesh if texture is not None else None, harm, flat, estr)
                    reduced, red_info = red_cache[key]
                    # Les branques fan servir aquesta reducció (papercraft.simplify la reconeix).
                    mesh.metadata["reduccio"] = (target, reduced)
                    if red_info["simetria"]:
                        st.caption(f"Simetria trobada: pla perpendicular a {red_info['simetria']['normal']}"
                                   f" (desviació {100 * red_info['simetria']['error']:.1f} % de la mida).")
                    elif sym != "no":
                        st.caption("El model no és simètric (o no hi cap amb tan poques cares): es "
                                   "redueix sencer.")
                if talls and len(mesh.faces) > target:   # la tapa de terra es conserva sencera i plana
                    mesh.metadata["reduccio"] = (target, encaix.refa_tapa(pc.simplify(mesh, target), talls))
                prepared, _ = dc.prepare(mesh, target, size, None)
                frames = dc.face_frames(prepared)
            else:
                prepared, frames = mesh, []   # capes: es talla el model original

        if "malla" not in ss:
            cache = st.session_state.setdefault("_model_view", {})
            with vista_col:
                if simplify_on:
                    if cache.get("simple_key") != (src, target, size, method, sym, detail, harm, flat, estr):
                        cache.clear()
                        cache.update(simple_key=(src, target, size, method, sym, detail, harm, flat, estr),
                                     simple=visor.pack(visor.model_solids(prepared, "Simplificat", "#dcc29a",
                                                                          edges="totes")))
                    st.markdown(f"**Simplificat** · {len(prepared.faces):,} cares · "
                                f"{max(prepared.extents):.0f} mm")
                    visor.show([], key="visor_simplificat", height=560, data=cache["simple"])
                else:   # capes: es tallen tal com són
                    if cache.get("src") != src:
                        cache.clear()
                        cache.update(src=src, original=visor.pack(visor.model_solids(mesh, "Model", "#9fb3c8")))
                    shown = cache["original"]["triangles"]
                    st.markdown(f"**Model** · {len(mesh.faces):,} cares"
                                + (f" (es mostra amb {shown:,})" if shown < len(mesh.faces) else ""))
                    visor.show([], key="visor_original", height=560, data=cache["original"])
            with ctrl_col:
                if st.button("Continua", type="primary", use_container_width=True):
                    low = pc.simplify(prepared, 300) if len(prepared.faces) > 300 else prepared
                    svg = vista.view_svg(low, ["#dcc29a"] * len(low.faces), width=200, yaw=35, pitch=22)
                    ss["malla"] = (size, target, method, sym, detail, harm, flat, estr)
                    ss["malla_mini"] = (f"{len(prepared.faces):,} cares",
                                        "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode())
                    st.rerun()
            st.stop()

        def uri_svg(svg: str) -> str:
            return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

        def resum(text: str, svg: str, recursos: list) -> None:
            """Targeta «Tècnic» al carrusel de dalt i botó de recursos a la dreta."""
            ss["tecnic_mini"] = (text, uri_svg(svg))
            ss["recursos"] = recursos
            for _t, dades_, nom_, _m in recursos:   # còpia a la carpeta de sortida per defecte
                carpeta.desa(nom_, dades_)

        def glb_recurs():
            return ("⬇️ Model (GLB)", mesh.export(file_type="glb"),
                    models[0].name.rsplit(".", 1)[0] + ".glb", "model/gltf-binary")

        def gen_paper(decor):
            tab_, page_, land_, nums_, lines_, zones_ = ss["gp"]
            with st.spinner("Desplegant…"):
                r_ = ss["paper"] = pc.make_papercraft(mesh, target, size, tab_, page_, land_, nums_, lines_,
                                                      zones_, decor=decor, texture=textura_uv())
            ss["desplegat_html"] = recursos.pagina_html("Pàgina", r_.pages)
            resum(f"Tècnic · {r_.stats['pagines']} pàg.", r_.pages[0],
                  [("⬇️ Pàgines (ZIP)", r_.zip_bytes(), "desplegable.zip", "application/zip"), glb_recurs()])

        def recursos_cares(r_) -> list:
            """Descàrregues de les cares: planxes CNC en ZIP i/o STL de les peces 3D, i el model."""
            mat_, car_, sup_ = ss["cmat"], ss["ccar"], ss["csup"]
            po = car_["plates_out"] if out == "Mixta" else plates_out
            so = sup_["supports_out"] if out == "Mixta" else supports_out
            noms = {p.name for p in r_.extra["parts0"]}
            cnc = {n for n in noms if (po if n[0] == "C" else so) == "CNC"}
            res = []
            if cnc == noms:
                res.append(("⬇️ Planxes (SVG + muntatge, ZIP)", r_.zip_bytes("cares"), "cares.zip", "application/zip"))
            elif cnc:
                z, _over = laser.cnc_zip(r_, "cares", cnc, mat_["sheet_mm"])
                res.append(("⬇️ Planxes CNC (SVG + muntatge, ZIP)", z, "cares_cnc.zip", "application/zip"))
            if cnc != noms:
                z, _big = r_.stl_zip("cares", sup_["bed"], None if not cnc else noms - cnc)
                res.append(("⬇️ STL (una peça per fitxer, ZIP)", z, "cares_stl.zip", "application/zip"))
            return res + [glb_recurs()]

        def gen_cares(decor):
            a, kw = ss["gc"]
            with st.spinner("Tallant cares i suports…"):
                r_ = ss["cares"] = cares.make_faces(mesh, target, size, *a, decor=decor,
                                                    texture=textura_uv(), **kw)
            low = pc.simplify(prepared, 300) if len(prepared.faces) > 300 else prepared
            resum(f"Tècnic · {r_.stats['plaques']} plaques",
                  vista.view_svg(low, ["#dcc29a"] * len(low.faces), width=200, yaw=35, pitch=22),
                  recursos_cares(r_))

        def fi_disseny(text: str, uri: str) -> None:
            ss["disseny"], ss["disseny_mini"] = True, (text, uri)
            ss["pantalla"] = None

        def aplica_capes(laser: bool, sense_uv: bool = False) -> None:
            """Compon totes les capes, regenera i surt de l'apartat Disseny."""
            paper_on = branch.startswith("📄")
            ops = disseny.capes_de(prepared, frames)
            if not sense_uv and ss.get("uv", "uvcap") != "uvcap" and textura_prep() is not None \
                    and not any(o["tipus"] == "uv" for o in ops):   # pell de base a totes les cares
                ops = [dict(nivell="uv", tipus="uv", cares=list(range(len(frames))))] + ops
            fet = pintura.decoracio(frames, prepared, textura_prep(), ops, ss.get("dis_marc", 0.0), laser,
                                    ss.get("dis_thr", 20))
            ss["paper_decor" if paper_on else "cares_decor"] = fet
            (gen_paper if paper_on else gen_cares)(fet)
            if ops:   # render amb tot el que s'ha posat: pell i capes
                fi_, rgb = pintura.render(frames, prepared, textura_prep(), ops, ss.get("dis_marc", 0.0))
                d_ = visor.pack(visor.model_solids(fi_, "Texturitzat", "#dcc29a", max_faces=200000))
                col = np.zeros((3 * len(fi_.faces), 4), np.uint8)
                col[:, :3] = np.repeat(rgb, 3, axis=0)
                d_["col"] = visor._b64(col, np.uint8)
                ss["vista_tex"] = d_
            else:
                ss.pop("vista_tex", None)
            ss["celebra"] = True
            if not ops:
                fi_disseny("En blanc", portada.icona("dis_blanc.png"))
            elif len(ops) == 1 and ops[0]["tipus"] == "uv":
                fi_disseny("UV", uv.miniatura(textura_prep().image))
            else:
                fi_disseny(f"{len(fet)} cares", portada.icona("dis_pintar.png"))
            ss["veure"] = True
            st.rerun()

        # ---- Apartat Disseny: tres capes apilables (UV, pintar, en blanc) amb botons petits sempre a dalt
        if ss.get("pantalla") in ("uv", "pintar", "blanc") and simplify_on and frames:
            paper_on = branch.startswith("📄")
            tab = ss["pantalla"]
            with st.container(key="distabs"):
                cols = st.columns([1, 1, 1, 9], gap="small")
                for col, (clau, text, _i), nom in zip(cols, portada.DISSENYS, ("uv", "pintar", "blanc")):
                    with col, st.container(key=f"mini_{clau}"):
                        if st.button(text, key=f"dt_{nom}", use_container_width=True):
                            ss["pantalla"] = nom
                            st.rerun()
            actiu = {"uv": "dis_uv", "pintar": "dis_pintar", "blanc": "dis_blanc"}[tab]
            st.markdown(f"<style>.st-key-mini_{actiu} button {{ outline: 3px solid #5a8cdc; }}</style>",
                        unsafe_allow_html=True)
            ops = disseny.capes_de(prepared, frames)
            if tab == "uv":
                st.caption("La textura és la pell de tot el desplegable; a sobre s'apilen les capes de pintura.")
                uvk = uv.seleccio(model_tex is not None)
                if st.button("Aplica el disseny", type="primary"):
                    aplica_capes(not paper_on)
                if ops:
                    st.caption("Capes de pintura: " + " · ".join(disseny._descriu(o) for o in ops))
            elif tab == "pintar":
                if disseny.pagina(prepared, frames, not paper_on, textura_prep(), "Aplica el disseny") is not None:
                    aplica_capes(not paper_on)
            else:
                st.caption("Sense disseny: el desplegable tal com és.")
                if st.button("Treu totes les capes i aplica", type="primary"):
                    ops.clear()
                    ss["dis_rev"] = ss.get("dis_rev", 0) + 1
                    aplica_capes(not paper_on, sense_uv=True)
            st.stop()

        def resultat_paper(r) -> None:
            s_ = r.stats
            st.success("🎉 Felicitats, el projecte s'ha acabat! Aquí tens el muntatge i el render; "
                       "els fitxers, a Recursos.")
            st.caption(f"{r.faces} cares · {s_['peces']} peces ({s_['zones']} zones naturals) · "
                       f"{s_['pagines']} pàgines · {s_['costures']} costures · {s_['pestanyes']} pestanyes")
            st.caption(f"Pestanyes: {s_['pestanyes_encongides']} encongides, {s_['pestanyes_diagonals']} tallades en diagonal, "
                       f"{s_['pestanyes_canviades']} canviades de costat i {s_['pestanyes_retallades']} retallades "
                       "per no xocar.")
            if s_["sense_pestanya"]:
                st.warning(f"{s_['sense_pestanya']} trossos de costura no tenen lloc per a una pestanya: "
                           "enganxa'ls amb cinta per darrere.")
            if s_["massa_grans"]:
                st.warning(f"{s_['massa_grans']} peces no caben a la pàgina.")
            if ss.pop("celebra", False):
                st.balloons()
            tex_ = ss.get("vista_tex")
            cols = st.columns([3, 3, 2] if tex_ else [3, 2], gap="large")
            with cols[0]:
                assembly_view(r, visor.paper_solids, "paper")
            if tex_:
                with cols[1]:
                    st.markdown("**Texturitzat**")
                    visor.show([], key="visor_tex", data=tex_)
            with cols[-1]:   # on s'acaba: tot el que es pot endur
                with st.container(key="recursos_final", border=True):
                    st.markdown("### 📦 Recursos")
                    if ss.get("desplegat_html"):
                        recursos.obre("🔍 Visualitza el desplegat (pestanya nova)", ss["desplegat_html"],
                                      "obre_desplegat_final")
                    for i, (text, dades, nom, mime) in enumerate(portada.tots_recursos()):
                        st.download_button(text, dades, nom, mime, key=f"recf_{i}", use_container_width=True,
                                           type="primary" if i == 0 else "secondary")
            st.info("Contínua = tall · ratlles = plec de vall · punt i ratlla = plec de muntanya · "
                    "gris = pestanya · els números vermells iguals s'uneixen.")

        def resultat_cares(r) -> None:
            s = r.stats
            st.success("🎉 Felicitats, el projecte s'ha acabat! Aquí tens el muntatge i el render; "
                       "els fitxers, a Recursos.")
            st.caption(f"{s['plaques']} plaques · {s['suports']} suports · {s['costelles']} costelles · "
                       f"{s['mitges_fustes']} mitges fustes · {s['ranures']} ranures · {s['planxes']} planxes")
            if s["grups_de_plaques"] > 1:
                st.warning(f"Les plaques queden en {s['grups_de_plaques']} grups sense suport entre ells (a la "
                           "vista, un color per grup): hi ha plaques massa petites per a suports.")
            if s["massa_grans"]:
                st.warning(f"{s['massa_grans']} peces no caben a la planxa.")
            if ss.pop("celebra", False):
                st.balloons()
            tex_ = ss.get("vista_tex")
            cols = st.columns([3, 3, 2] if tex_ else [3, 2], gap="large")
            with cols[0]:
                assembly_view(r, visor.cares_solids, "cares")
            if tex_:
                with cols[1]:
                    st.markdown("**Texturitzat**")
                    visor.show([], key="visor_tex", data=tex_)
            with cols[-1]:
                with st.container(key="recursos_final", border=True):
                    st.markdown("### 📦 Recursos")
                    for i, (text, dades, nom, mime) in enumerate(portada.tots_recursos()):
                        st.download_button(text, dades, nom, mime, key=f"recf_{i}", use_container_width=True,
                                           type="primary" if i == 0 else "secondary")
            st.info("Vermell = tallar · blau = gravar · verd = només referència (plaques amb gravat decoratiu: "
                    "es tallen amb la cara de fora amunt).")
            with st.expander("Instruccions de muntatge"):
                st.text("\n".join(r.notes))
            show(r.sheets, "Planxa")

        # ---- Desplegable ja generat: el Tècnic ha passat al carrusel; queda triar disseny i el resultat
        if (branch.startswith("📄") or cares_on) and ss.get("tecnic"):
            if ss.get("paper" if branch.startswith("📄") else "cares") is None:
                ss.pop("tecnic", None)
                ss.pop("tecnic_mini", None)
                st.rerun()
            if not ss.get("disseny"):
                triat = portada.cartes("dis", portada.DISSENYS, "Quin disseny vols?",
                                       "UV: la pell d'un model amb textura. Pintar: imatges i colors per "
                                       "capes. En blanc: tal com és.")
                if triat == "dis_uv":
                    ss["pantalla"] = "uv"
                    st.rerun()
                elif triat == "dis_pintar":
                    ss["pantalla"] = "pintar"
                    st.rerun()
                elif triat == "dis_blanc":
                    ss["pantalla"] = "blanc"
                    st.rerun()
                st.stop()
            (resultat_paper if branch.startswith("📄") else resultat_cares)(ss["paper" if branch.startswith("📄") else "cares"])
            st.stop()

        # ---- Cares (CNC): material, cares i suports, cadascun al seu apartat amb una mostra rotable
        if cares_on:
            pur_cnc = out in ("Làser / CNC", "CNC / làser")
            plate_mm = cares.plate_scale(prepared)
            fase = "cmat" if "cmat" not in ss else "ccar" if "ccar" not in ss else "csup"
            titol, frase = {"cmat": ("Material", "El gruix i la planxa de què es tallen plaques i suports."),
                            "ccar": ("Cares", "Com són les plaques: espai entre elles, xamfrà i fusió de les petites."),
                            "csup": ("Suports", "Com s'uneixen les plaques: tipus, mida i repartiment dels suports.")}[fase]
            portada.capcalera(titol, frase)
            esq, dre = st.columns([2, 3], gap="large")
            mat, car, sup = ss.get("cmat"), ss.get("ccar"), None
            with esq:
                if fase == "cmat":
                    mat = cparam.material()
                    nou, text, icona = mat, f"Material · {mat['thickness']:g} mm", "capes.png"
                elif fase == "ccar":
                    car = cparam.cares_p(out, pur_cnc, lamp_controls, size)
                    nou, text, icona = car, f"Cares · xamfrà {car['chamfer_mm']:g} mm", "cares.png"
                else:
                    sup = cparam.suports(plate_mm, mat["thickness"], out, pur_cnc)
                    nou, text, icona = sup, f"Suports · {sup['joint']}", "encaix_sota2.png"
                if fase != "csup":
                    if st.button("Continua", type="primary", use_container_width=True):
                        ss[fase], ss[f"{fase}_mini"] = nou, (text, portada.icona(icona))
                        st.rerun()
                elif st.button("🚀 Generar cares", type="primary", use_container_width=True):
                    ss["csup"], ss["csup_mini"] = nou, (text, portada.icona(icona))
                    ss["gc"] = cparam.args(mat, car, sup)
                    gen_cares(ss.get("cares_decor", {}))
                    ss["tecnic"] = True
                    st.rerun()
            with dre:
                cparam.mostra(mat or dict(thickness=3.0, sheet_mm=(600.0, 400.0)), car or cparam.DEF_CAR,
                              sup or cparam.sup_def(plate_mm, (mat or {}).get("thickness", 3.0)), plate_mm)
            st.stop()

        decor = {}   # el disseny triat s'aplica en generar; el quadre de després el pot retocar

        if branch.startswith("📄"):
            st.subheader("Tècnic")
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

            ss["gp"] = (tab, page, landscape, face_numbers, lines, zones)
            if st.button("🚀 Generar desplegable", type="primary"):
                gen_paper(ss.get("paper_decor", {}))
                ss["tecnic"] = True
                st.rerun()

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
            if not cares_on:
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
                    rot_mode = st.radio("Rotació de les peces", ["Desactivada", "Activada"], horizontal=True,
                                        help="Desactivada: les peces es giren lliurement per aprofitar la planxa "
                                             "(menys material perdut). Activada: cada capa es talla girada un angle respecte de l'ona "
                                             "del cartró (la llum cola entre les ones). En apilar, "
                                             "posa les fletxes cap al mateix costat.")
                    rotation = None
                    if rot_mode == "Activada":
                        rotation = float(st.select_slider("Gir entre capes consecutives (°)",
                                                          [0, 15, 30, 45, 60, 90, 120], 90,
                                                          help="0 = ones alineades (la llum passa "
                                                               "recta). 90 = creuades."))
                    lamp = lamp_controls("capes", size, True)
                    with st.expander("🧰 Eines (properament)", expanded=False):
                        st.caption("Encara no implementades: els botons hi són per reservar el lloc.")
                        t1, t2 = st.columns(2)
                        t1.button("🌊 Generador d'ona", disabled=True, key="eina_ona",
                                  help="Genera l'ona del cartró i l'aplica a les capes.")
                        t2.button("✍️ Ona/gir manual per capa", disabled=True, key="eina_ona_manual",
                                  help="Introdueix a mà l'ona o el gir de cada capa.")
                        t1.button("🔩 Suport predefinit", disabled=True, key="eina_suport",
                                  help="Capa sense buidar amb retalls i patrons de forats "
                                       "predefinits (p. ex. quatre forats i un de central).")
                        t2.button("⭕ Foradar lliure", disabled=True, key="eina_foradar",
                                  help="Forma bàsica o spline projectada, escalable, girable i "
                                       "desplaçable, que resta de la forma final.")
                if st.button("🚀 Generar capes", type="primary"):
                    with st.spinner("Tallant capes…"):
                        st.session_state["capes"] = laminacio.make_layers(
                            mesh, target, size, thickness, column, sheet_mm, wall,
                            align, lamp=lamp, rotation=rotation)
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
                    with st.expander("🧱 Materials i filtre de peces", expanded=False):
                        names = [p.name for p in r.extra["parts0"]]
                        mats = [x.strip() for x in st.text_input(
                            "Materials (separats per comes)", "Material A", key="mats_capes"
                        ).split(",") if x.strip()] or ["Material A"]
                        rule = st.radio("Assignació", ["Tots al primer", "Alternar capes", "Manual"],
                                        horizontal=True, key="mats_regla")
                        manual: dict[str, list[str]] = {}
                        if rule == "Manual":
                            for mt in mats[1:]:
                                manual[mt] = st.multiselect(f"Peces de {mt}", names, key=f"mats_m_{mt}")
                        ribs = [n for n in names if n.startswith("R")]
                        rib_mat = mats[0]
                        if ribs:
                            rib_mat = st.selectbox(f"Material de les costelles ({len(ribs)})",
                                                   [*mats, "— no es fan"], key="mats_costelles",
                                                   help="Totes les costelles (R) en bloc. Si en "
                                                        "vols de concretes en un altre material, "
                                                        "tria-les a Manual.")
                        skip = st.multiselect("Peces que no es fan", names, key="mats_skip")
                        assign: dict[str, str | None] = {}
                        for n in names:
                            if n in skip:
                                assign[n] = None
                            elif n in ribs and not any(n in ns for ns in manual.values()):
                                assign[n] = None if rib_mat.startswith("—") else rib_mat
                            elif rule == "Alternar capes" and n.startswith("L"):
                                assign[n] = mats[(int("".join(c for c in n[1:] if c.isdigit())) - 1)
                                                 % len(mats)]
                            else:
                                assign[n] = next((mt for mt, ns in manual.items() if n in ns), mats[0])
                        if st.button("Aplica materials i filtre"):
                            laser.regroup(r, assign, sheet_mm)
                            st.rerun()
                        if r.sheet_materials:
                            st.caption("Planxes per material: " + " · ".join(
                                f"{mt}: {r.sheet_materials.count(mt)}"
                                for mt in dict.fromkeys(r.sheet_materials)))
            if r:
                if r.stats["massa_grans"]:
                    st.warning(f"{r.stats['massa_grans']} peces no caben a la planxa.")
                if prefix == "capes":
                    plates_out = supports_out = "CNC" if out == "Làser / CNC" else "3D"
                names = {p.name for p in r.extra["parts0"]}
                cnc = {n for n in names if (plates_out if n[0] == "C" else supports_out) == "CNC"}
                if prefix == "capes" or cnc == names or not cnc:
                    cnc_all, d3_all = cnc == names, not cnc
                else:
                    cnc_all = d3_all = False
                if cnc_all:
                    st.download_button("⬇️ Descarrega les planxes (SVG + muntatge en un ZIP)",
                                       r.zip_bytes(prefix), f"{prefix}.zip", "application/zip")
                    st.info("Vermell = tallar · blau = gravar · verd = només referència (plaques "
                            "amb gravat decoratiu: es tallen amb la cara de fora amunt).")
                if not cnc_all:
                    if not d3_all:   # mixta: les planxes només amb el que va a CNC
                        zip_cnc, over = laser.cnc_zip(r, prefix, cnc, sheet_mm)
                        st.download_button("⬇️ Descarrega les planxes CNC (SVG + muntatge en un ZIP)",
                                           zip_cnc, f"{prefix}_cnc.zip", "application/zip")
                        if over:
                            st.warning(f"{over} peces CNC no caben a la planxa.")
                    b1, b2 = st.columns(2)
                    bed = (b1.number_input("Llit X (mm)", 20.0, 1000.0, 220.0, 10.0, key=f"bx_{prefix}"),
                           b2.number_input("Llit Y (mm)", 20.0, 1000.0, 220.0, 10.0, key=f"by_{prefix}"))
                    data, big = r.stl_zip(prefix, bed, None if d3_all else names - cnc)
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
        traceback.print_exc()   # el missatge surt a la pantalla; el traçat, al registre del servidor
        st.error(str(e))
