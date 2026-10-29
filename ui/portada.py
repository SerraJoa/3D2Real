"""Selecció guiada per targetes quadrades 1:1 (imatge + text a la reserva inferior).

Cada pas mostra les seves opcions grans i centrades; les ja triades queden a dalt a l'esquerra,
en petit, com a referència i accés directe per tornar a triar (esborra aquest pas i els següents).
"""
import base64
import io
from pathlib import Path

import streamlit as st
from PIL import Image

from ui.encaix import TIPUS

ICONES = Path(__file__).resolve().parent.parent / "icones"
RESERVA = 20  # % de l'alçada del quadrat reservat al text

# (clau, text visible, imatge)
PRODUCTES = [("desplegables", "Desplegables", "desplegables.png"),
             ("cares", "Cares", "cares.png"),
             ("capes", "Capes", "capes.png")]
# Tecnologia de sortida per producte: (clau, text visible, valor que fa servir app.py, imatge)
MIXTA = "mixta"  # imatge composta: CNC a l'esquerra, 3D a la dreta
SORTIDES = {
    "desplegables": [("impressora", "Impressora", "Impressora", "impresora.png"),
                     ("cnc", "CNC / làser", "CNC / làser", "cnc laser.png")],
    "cares": [("cnc", "CNC / làser", "Làser / CNC", "cnc laser.png"),
              ("3d", "Impressora 3D", "Impressora 3D", "impr3D.webp"),
              ("mixta", "Mixta", "Mixta", MIXTA)],
    "capes": [("cnc", "CNC / làser", "Làser / CNC", "cnc laser.png"),
              ("3d", "Impressora 3D", "Impressora 3D", "impr3D.webp")],
}
ENCAIXOS = TIPUS
UVS = [("uvmodel", "UV del model", "uv_model.png"), ("uvimporta", "Importar UV", "uv_importa.png"),
       ("uvcap", "Sense UV", "uv_cap.png")]
ORIGENS = [("model", "Model", "carpeta.png"), ("imatge", "Imatge", "imatge.png")]
VIES = [("carpeta", "Carpeta", "carpeta.png"), ("ia", "IA", "ia.png")]
DISSENYS = [("dis_uv", "UV", "uv_importa.png"), ("dis_pintar", "Pintar", "dis_pintar.png"),
            ("dis_blanc", "En blanc", "dis_blanc.png")]
PASSOS_EXTRES = ["orient", "encaix", "malla", "cmat", "ccar", "csup", "tecnic", "disseny"]  # passos de l'espai de treball, un cop triat el model
PASSOS = ["producte", "sortida", "origen", "via"]  # "via" només si l'origen és una imatge

# Pregunta i frase descriptiva de cada pas (la frase pot dependre del producte triat).
TITOLS = {
    "producte": ("Què vols fabricar?",
                 "Tria el tipus de peça: un desplegable de paper per plegar, cares planes de "
                 "làser unides amb suports, o capes apilades que reprodueixen el volum."),
    "origen": ("D'on surt el model?",
               "Model: ja tens un fitxer 3D (STL, OBJ o GLB) i el carregues directament. "
               "Imatge: parteixes d'una imatge i el model 3D es crea automàticament."),
    "via": ("Com obtens la imatge?",
            "Carpeta: puges una imatge teva. IA: la descrius i se't genera."),
}
FRASES_SORTIDA = {
    "desplegables": "Impressora: imprimeixes el patró en paper. CNC / làser: el talles i el marques.",
    "cares": "CNC / làser talla plaques i suports; Impressora 3D els imprimeix; Mixta combina "
             "plaques d'una tecnologia i suports de l'altra.",
    "capes": "CNC / làser talla cada capa de planxa; Impressora 3D imprimeix les capes.",
}


def _titol(pas: str, producte: str | None) -> tuple[str, str]:
    if pas == "sortida":
        return "Amb quina tecnologia ho faràs?", FRASES_SORTIDA[producte]
    return TITOLS[pas]


def _jpeg(img: Image.Image, mida: int = 640) -> str:
    img = img.convert("RGBA")
    fons = Image.new("RGB", img.size, "white")
    fons.paste(img, mask=img.split()[3])
    fons.thumbnail((mida, mida))
    buf = io.BytesIO()
    fons.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _cobreix(img: Image.Image, w: int, h: int) -> Image.Image:
    """Retalla centrat perquè ompli w×h (com `object-fit: cover`)."""
    f = max(w / img.width, h / img.height)
    img = img.convert("RGBA").resize((round(img.width * f), round(img.height * f)))
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


@st.cache_resource
def _imatge(fitxer: str) -> str:
    if fitxer == MIXTA:
        mig = 320
        out = Image.new("RGBA", (2 * mig, 2 * mig), "white")
        out.paste(_cobreix(Image.open(ICONES / "cnc laser.png"), mig, 2 * mig), (0, 0))
        out.paste(_cobreix(Image.open(ICONES / "impr3D.webp"), mig, 2 * mig), (mig, 0))
        return _jpeg(out)
    return _jpeg(Image.open(ICONES / fitxer))


def icona(fitxer: str) -> str:
    """Data URI d'una icona de `icones/` (per a les targetes de la ruta)."""
    return _imatge(fitxer)


def _css(imatges: dict[str, str]) -> str:
    regles = "".join(f".st-key-card_{k} button::before, .st-key-mini_{k} button::before "
                     f"{{ background-image: url({u}); }}" for k, u in imatges.items())
    return f"""<style>
    .st-key-portada button, .st-key-ruta button, .st-key-distabs button {{
        position: relative; overflow: hidden; width: 100%; aspect-ratio: 1 / 1; height: auto;
        margin: 0 auto;
        padding: 0; border-radius: 14px; display: block;
        border: 1px solid rgba(128,128,128,.35); background: var(--secondary-background-color);
        transition: transform .12s, box-shadow .12s;
    }}
    .st-key-portada button::before, .st-key-ruta button::before, .st-key-distabs button::before {{
        content: ""; position: absolute; inset: 0 0 {RESERVA}% 0;
        background-size: cover; background-position: center;
    }}
    .st-key-portada button > div, .st-key-ruta button > div, .st-key-distabs button > div {{
        position: absolute; inset: auto 0 0 0; height: {RESERVA}%;
        display: flex; align-items: center; justify-content: center;
    }}
    .st-key-portada button {{ max-width: 300px; }}
    .st-key-ruta button, .st-key-distabs button {{ max-width: 120px; }}
    .st-key-portada button p {{ font-size: 1.25rem; font-weight: 600; margin: 0; }}
    .st-key-ruta button p, .st-key-distabs button p {{ font-size: .8rem; font-weight: 600; margin: 0; white-space: nowrap; }}
    .st-key-portada button:hover, .st-key-ruta button:hover, .st-key-distabs button:hover {{
        transform: translateY(-3px); box-shadow: 0 8px 22px rgba(0,0,0,.25);
        border-color: var(--primary-color);
    }}
    {regles}
    </style>"""


def _opcions(tipus: str) -> list[tuple[str, str, str]]:
    """Opcions del pas que toca: (clau, text, imatge)."""
    if tipus == "producte":
        return PRODUCTES
    if tipus == "origen":
        return ORIGENS
    if tipus == "via":
        return VIES
    return [(k, t, img) for k, t, _v, img in SORTIDES[tipus]]


def capcalera(titol: str, frase: str) -> None:
    st.markdown(f"<div style='text-align:center;margin:0;font-size:1.9rem;font-weight:700'>{titol}</div>"
                f"<p style='text-align:center;opacity:.75;max-width:46rem;margin:.4rem auto 1.5rem'>"
                f"{frase}</p>", unsafe_allow_html=True)


def sortida_valor(producte: str, clau: str) -> str:
    return next(v for k, _t, v, _i in SORTIDES[producte] if k == clau)


def tots_recursos() -> list:
    """Recursos de l'origen (imatge, primer GLB) seguits dels del disseny, disponibles des del principi."""
    ss = st.session_state
    return list(ss.get("recursos_origen", [])) + list(ss.get("recursos", []))


def mostra() -> bool:
    """Dibuixa la ruta triada (petita, a dalt) i el pas pendent (gran, al mig).

    Retorna True quan tots els passos estan triats i l'app pot continuar.
    """
    ss = st.session_state
    passos = PASSOS if ss.get("origen") == "imatge" else PASSOS[:3]
    triats = []  # (pas, clau): només mentre els passos anteriors estan triats
    for pas in passos:
        if not ss.get(pas):
            break
        triats.append((pas, ss[pas]))

    imatges = {}
    for k, _t, img in PRODUCTES + ORIGENS + VIES + ENCAIXOS + UVS + DISSENYS:
        imatges[k] = _imatge(img)
    for opts in SORTIDES.values():
        for k, _t, _v, img in opts:
            imatges.setdefault(k, _imatge(img))
    # Passos de després de la ruta (orientació, encaix): (clau, (text, data URI)) un cop triats
    extres = [(k, ss[f"{k}_mini"]) for k in PASSOS_EXTRES if f"{k}_mini" in ss]
    for k, (_t, u) in extres:
        imatges[k] = u
    recurs_css = """<style>
    .st-key-recursos { position: fixed; top: 3.6rem; right: 1.5rem; z-index: 1000; width: auto; }
    .st-key-recursos button { min-height: 3rem; padding: .4rem 1.4rem; font-size: 1.15rem; font-weight: 600;
        border: 2px solid var(--primary-color); border-radius: 14px; background: var(--background-color);
        box-shadow: 0 4px 14px rgba(0,0,0,.25); }
    </style>"""
    st.markdown(_css(imatges) + recurs_css, unsafe_allow_html=True)

    def etiqueta(pas: str, clau: str) -> str:
        return next(t for k, t, *_ in _opcions(pas if pas != "sortida" else ss["producte"]) if k == clau)

    if triats:
        with st.container(key="ruta"):
            n_mini = len(triats) + len(extres)
            cols = st.columns([1] * n_mini + [max(1, 12 - n_mini)], gap="small")
            for col, (k, (text, _u)) in zip(cols[len(triats):], extres):
                with col, st.container(key=f"mini_{k}"):
                    if st.button(text, key=f"ruta_{k}", use_container_width=True, help="Torna a triar"):
                        for p in PASSOS_EXTRES[PASSOS_EXTRES.index(k):]:
                            for suf in ("", "_mini", "_tipus", "_import"):
                                ss.pop(p + suf, None)
                        ss.pop("pantalla", None)
                        if k != "disseny":   # tornar al disseny conserva el desplegat; la resta, no
                            for r in ("paper", "cares", "veure", "recursos", "desplegat_html", "vista_tex"):
                                ss.pop(r, None)
                        st.rerun()
            if tots_recursos():   # a la dreta de la ruta: descàrregues del que s'ha generat
                with cols[-1], st.container(key="recursos"):
                    with st.popover("📦 Recursos"):
                        if ss.get("desplegat_html"):
                            from ui import recursos
                            recursos.obre("🔍 Visualitza el desplegat (pestanya nova)", ss["desplegat_html"],
                                          "obre_desplegat")
                        for i, (text, dades, nom, mime) in enumerate(tots_recursos()):
                            st.download_button(text, dades, nom, mime, key=f"rec_{i}", use_container_width=True)
            for col, (pas, clau) in zip(cols, triats):
                with col, st.container(key=f"mini_{clau}"):
                    if st.button(etiqueta(pas, clau), key=f"ruta_{pas}", use_container_width=True,
                                 help="Torna a triar"):
                        for p in PASSOS[PASSOS.index(pas):]:
                            ss.pop(p, None)
                        for p in PASSOS_EXTRES:   # orientació i encaix depenen del model
                            for suf in ("", "_mini", "_tipus", "_import"):
                                ss.pop(p + suf, None)
                        for r in ("paper", "cares", "veure", "pantalla", "recursos", "desplegat_html", "vista_tex"):
                            ss.pop(r, None)
                        ss.pop("fitxers", None)
                        ss.pop("recursos_origen", None)
                        if pas in ("origen", "via"):  # una altra imatge o model: res de l'anterior serveix
                            for k in ("img_generada",):
                                ss.pop(k, None)
                        st.rerun()

    if len(triats) == len(passos):
        return True

    pas = passos[len(triats)]
    titol, frase = _titol(pas, ss.get("producte"))
    clau = cartes(pas, _opcions(pas if pas != "sortida" else ss["producte"]), titol, frase)
    if clau:
        ss[pas] = clau
        st.rerun()
    return False


def cartes(pas: str, opcions: list[tuple[str, str, str]], titol: str, frase: str) -> str | None:
    """Pas de targetes grans i centrades; retorna la clau de la que s'ha clicat."""
    triada = None
    with st.container(key="portada"):
        st.markdown("<div style='height:3vh'></div>", unsafe_allow_html=True)
        capcalera(titol, frase)
        marge = {4: [1, 2.5, 2.5, 2.5, 2.5, 1], 3: [1.5, 2.5, 2.5, 2.5, 1.5],
                 2: [3, 2.5, 2.5, 3]}[len(opcions)]
        cols = st.columns(marge, gap="large")
        for col, (clau, text, _img) in zip(cols[1:1 + len(opcions)], opcions):
            with col, st.container(key=f"card_{clau}"):
                if st.button(text, key=f"btn_{pas}_{clau}", use_container_width=True):
                    triada = clau
    return triada


def graella(pas: str, opcions: list[tuple[str, str, str]], titol: str, frase: str) -> str | None:
    """Les opcions de l'encaix en 3 columnes (1, 2 i 3 plans) i 3 files (sota, lateral, sobre)."""
    from ui.encaix import COLUMNES, FILES
    st.markdown("<style>.st-key-portada button { max-width: 150px !important; }"
                ".st-key-portada button p { font-size: .8rem !important; white-space: nowrap; }"
                "</style>", unsafe_allow_html=True)
    triada = None
    n = len(COLUMNES)
    with st.container(key="portada"):
        capcalera(titol, frase)
        cols = st.columns([1.2] + [1] * n + [1.2], gap="small")
        for col, c in zip(cols[1:], COLUMNES):
            col.markdown(f"<div style='text-align:center;font-weight:600'>{c} pla{'' if c == 1 else 'ns'}</div>"
                         , unsafe_allow_html=True)
        for i, (_f, nom) in enumerate(FILES):
            cols = st.columns([1.2] + [1] * n + [1.2], gap="small", vertical_alignment="center")
            cols[0].markdown(f"<div style='text-align:right;font-weight:600'>{nom}</div>", unsafe_allow_html=True)
            for col, (clau, text, _img) in zip(cols[1:], opcions[i * n:(i + 1) * n]):
                with col, st.container(key=f"card_{clau}"):
                    if st.button(text, key=f"btn_{pas}_{clau}", use_container_width=True):
                        triada = clau
    return triada
