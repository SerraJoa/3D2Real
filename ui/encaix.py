"""Pas d'encaix: on es col·loca la peça (terra, paret, sostre o cantonada) i com hi entra.

Amb la Z amunt ja triada a l'orientació, els plans de l'encaix són fixos i passen pels costats de
la caixa de la peça: terra i sostre (horitzontals) i parets (verticals, alineades amb X i Y).
L'ajust desplaça i gira la peça respecte d'ells en quatre vistes (planta, alçat, perfil i
isomètrica); el que queda a l'altre costat dels plans s'elimina (amb o sense cara de tall).
"""
import base64
import math

import numpy as np
import trimesh

import papercraft as pc

CARES_PREVIA = 300
FILES = [("sobre", "Sobre"), ("lateral", "Lateral"), ("sota", "Sota")]   # de dalt a baix
COLUMNES = [1, 2, 3]   # nombre de plans que toquen la peça
NOMS = {"sobre": ["Sostre", "Sostre + paret", "Sostre + cantonada"],
        "lateral": ["Paret", "Cantonada", "Paret en U"],
        "sota": ["Terra", "Terra + paret", "Terra + cantonada"]}
TIPUS = [(f"{f}{n}", NOMS[f][n - 1], f"encaix_{f}{n}.png") for f, _ in FILES for n in COLUMNES]
FRASE = ("De dalt a baix: penja d'un sostre, es fixa de costat o reposa a terra. D'esquerra a "
         "dreta: contra un pla, contra dos o contra tres.")
# Angle (°) de la normal de cada paret: 0 = +X, 90 = +Y (el darrere de l'alçat), 180 = -X
PARETS = {"lateral1": [90], "lateral2": [90, 0], "lateral3": [0, 90, 180],
          "sota2": [90], "sota3": [90, 0], "sobre2": [90], "sobre3": [90, 0]}
ZERO = (0.0,) * 6   # (tx, ty, tz, rx, ry, rz): desplaçament en unitats del model i girs en °


def plans(mesh, tipus: str) -> list[tuple[np.ndarray, np.ndarray]]:
    """(punt, normal cap al costat que es conserva) dels plans de l'encaix, a la caixa de la peça."""
    lo, hi = mesh.bounds
    out = []
    if tipus.startswith("sota"):
        out.append((np.array([0, 0, lo[2]]), np.array([0, 0, 1.0])))
    elif tipus.startswith("sobre"):
        out.append((np.array([0, 0, hi[2]]), np.array([0, 0, -1.0])))
    for a in PARETS.get(tipus, []):
        d = np.round([math.cos(math.radians(a)), math.sin(math.radians(a)), 0.0], 9)
        out.append((d * np.where(d > 0, hi, lo), -d))
    return out


def moviment(mesh, desp) -> np.ndarray:
    """Matriu 4×4: gira la peça al voltant del centre de la seva caixa (Rz·Ry·Rx) i la desplaça."""
    tx, ty, tz, rx, ry, rz = desp
    c = mesh.bounds.mean(0)
    R = trimesh.transformations.euler_matrix(*np.radians([rx, ry, rz]), axes="sxyz")
    return (trimesh.transformations.translation_matrix(c + [tx, ty, tz]) @ R
            @ trimesh.transformations.translation_matrix(-c))


def talla(mesh, tipus: str, desp=ZERO, cap: bool = True):
    """La peça mogu­da i tallada pels plans de l'encaix; `cap` hi genera la cara (si és estanca)."""
    if not any(desp):
        return mesh
    fixos = plans(mesh, tipus)
    out = mesh.copy()
    out.apply_transform(moviment(mesh, desp))
    for punt, normal in fixos:
        cut = out.slice_plane(punt, normal, cap=cap and out.is_watertight)
        if len(cut.faces):
            out = pc.clean(cut)
    return out


def plans_tallats(mesh, tipus: str, desp=ZERO) -> list[tuple[int, int]]:
    """(eix, sentit) dels plans que la peça mogu­da travessa de debò: només en aquests hi ha tapa."""
    if not any(desp):
        return []
    lo, hi = trimesh.Trimesh(mesh.vertices, mesh.faces, process=False).apply_transform(
        moviment(mesh, desp)).bounds
    out = []
    for p, n in plans(mesh, tipus):
        k = int(np.argmax(np.abs(n)))
        s = int(np.sign(n[k]))
        if (s > 0 and lo[k] < p[k] - 1e-9) or (s < 0 and hi[k] > p[k] + 1e-9):
            out.append((k, s))
    return out


def refa_tapa(mesh, talls: list[tuple[int, int]]):
    """Torna a fer la tapa de cada tall com UNA sola cara plana sobre una malla ja reduïda.

    La reducció desfà la tapa (la torça i la talla en trossos). Aquí es treuen els triangles
    gairebé plans enganxats al pla, el contorn que queda s'hi posa exactament i se'n fa una
    tapa nova d'una peça (un sol pla, perquè després es talli com una cara)."""
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    out = mesh.copy()
    for k, s in talls:
        c = out.bounds[0][k] if s > 0 else out.bounds[1][k]   # coordenada del pla de tall
        sortint = np.zeros(3)
        sortint[k] = -s   # cap al costat que s'ha tallat
        banda = 0.05 * float(max(out.extents))
        V, F = out.vertices, out.faces
        tapa = ((out.face_normals @ sortint) > 0.8) & (np.abs(V[F][:, :, k] - c).max(1) < banda)
        if not tapa.any():
            continue
        out = trimesh.Trimesh(V, F[~tapa], process=False)
        V = out.vertices.copy()
        brd = trimesh.grouping.group_rows(out.edges_sorted, require_count=1)
        arestes = out.edges[brd]
        V[np.unique(arestes), k] = c
        eixos = [a for a in range(3) if a != k]
        P2 = V[:, eixos]
        poli = unary_union(list(polygonize([LineString(P2[e]) for e in arestes])))
        if poli.is_empty:
            continue
        vs, fs, base = [], [], 0   # una tapa per illa: el tall pot deixar-ne més d'una
        for g in getattr(poli, "geoms", [poli]):
            if g.geom_type != "Polygon" or g.area < 1e-9:
                continue
            gv, gf = trimesh.creation.triangulate_polygon(g)
            vs.append(gv)
            fs.append(np.asarray(gf) + base)
            base += len(gv)
        if not vs:
            continue
        v, f = np.vstack(vs), np.vstack(fs)
        n0 = len(V)
        cap_v = np.zeros((len(v), 3))
        cap_v[:, eixos] = v
        cap_v[:, k] = c
        f = np.asarray(f)
        # orientació: la normal ha de mirar cap al costat tallat
        a, b, d = cap_v[f[:, 0]], cap_v[f[:, 1]], cap_v[f[:, 2]]
        orient = np.cross(b - a, d - a) @ sortint
        f = np.where((orient < 0)[:, None], f[:, ::-1], f)
        out = trimesh.Trimesh(np.vstack([V, cap_v]), np.vstack([out.faces, f + n0]), process=False)
        out.merge_vertices()
    return out


def desp_icona(mesh, tipus: str, prof: float = 15.0) -> tuple:
    """Desplaçament que enfonsa la peça `prof` % de la seva mida en cada pla (per a les icones)."""
    t = np.zeros(3)
    for _p, n in plans(mesh, tipus):
        t -= n * prof / 100 * mesh.extents[int(np.argmax(np.abs(n)))]
    return (*t, 0.0, 0.0, 0.0)


def _llosa(punt: np.ndarray, normal: np.ndarray, mig: float, alt: float, gruix: float):
    """Bloc que representa la paret, el terra o el sostre: darrere del pla (cap a -normal)."""
    n = normal / np.linalg.norm(normal)
    if abs(n[2]) > 0.9:
        u, v, hu, hv = np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), mig, mig
    else:
        u, v, hu, hv = np.cross(n, [0, 0, 1.0]), np.array([0, 0, 1.0]), mig, alt
        u /= np.linalg.norm(u)
    T = np.eye(4)
    T[:3, :3] = np.column_stack([u, v, n])
    sobre = 0.004 * mig   # surt una mica cap a la peça: tapa el tall net, sense parpelleig
    T[:3, 3] = punt - n * (gruix / 2 - sobre)
    box = trimesh.creation.box((2 * hu, 2 * hv, gruix + 2 * sobre))
    box.apply_transform(T)
    return box.subdivide_to_size(mig / 5)


def _yaw(tipus: str) -> float:
    """Càmera que té les parets al darrere (cap damunt la peça), una mica en diagonal."""
    parets = PARETS.get(tipus, [])
    if not parets:
        return 35.0
    m = math.degrees(math.atan2(sum(math.sin(math.radians(a)) for a in parets),
                                sum(math.cos(math.radians(a)) for a in parets)))
    return 90 - m + 25


def escena_svg(mesh, tipus: str, desp=ZERO, width: int = 340, cares: int = CARES_PREVIA,
               marc: tuple | None = None, pitch: float = 22.0, yaw: float | None = None) -> str:
    """La peça encastada a les parets/terra/sostre de l'encaix, amb la projecció i l'ombrejat de
    `vista`: la part que s'enfonsa queda dins el bloc, així es veu fins on entra."""
    low = pc.simplify(mesh, cares) if len(mesh.faces) > cares else mesh
    cutm = talla(low, tipus, desp, cap=False)
    ext = float(max(low.extents))
    centre, mig = (low.bounds.mean(0), 1.05 * ext) if marc is None else marc
    c0 = low.bounds.mean(0)
    llosas = []
    for p, n in plans(mesh, tipus):
        p = c0 - n * ((c0 - p) @ n)   # el punt del pla més proper al centre de la peça
        llosas.append(_llosa(p, n, 0.9 * ext, 0.9 * ext, 0.5 * ext))
    if llosas:   # un sol bloc, retallat a un cub: sense encreuaments que ordenin malament les cares
        bloc = trimesh.boolean.union(llosas, engine="manifold") if len(llosas) > 1 else llosas[0]
        cub = trimesh.creation.box([1.2 * ext] * 3)
        cub.apply_translation(c0)
        llosas = [trimesh.boolean.intersection([bloc, cub], engine="manifold").subdivide_to_size(0.12 * ext)]
    if yaw is None:
        yaw = _yaw(tipus)
    a, b = math.radians(yaw), math.radians(pitch)
    Rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    R = Rx @ Rz
    escala = width / (2 * mig)
    light = np.array([-0.4, -0.8, 0.45])
    light /= np.linalg.norm(light)
    items = []   # (profunditat, polígon svg)
    for m, color in [(cutm, (255, 150, 60))] + [(ll, (228, 232, 238)) for ll in llosas]:
        V = (m.vertices - centre) @ R.T
        N = m.face_normals @ R.T
        P = np.column_stack([V[:, 0], -V[:, 2]]) * escala + width / 2
        dep = V[m.faces][:, :, 1].mean(1)
        for f in range(len(m.faces)):
            if N[f, 1] > 0:
                continue
            sh = 0.8 + 0.2 * max(0.0, float(-N[f] @ light))
            rgb = tuple(int(c * sh) for c in color)
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in P[m.faces[f]])
            items.append((dep[f], f'<polygon points="{pts}" fill="rgb{rgb}" stroke="rgb{rgb}" '
                                  f'stroke-width="0.6"/>'))
    items.sort(key=lambda t: -t[0])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{width}" '
            f'viewBox="0 0 {width} {width}"><rect width="100%" height="100%" fill="white"/>'
            + "".join(t for _, t in items) + "</svg>")


def uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def etiqueta(tipus: str, *_) -> str:
    return next(t for k, t, _i in TIPUS if k == tipus)


def _dades(mesh, tipus: str) -> dict:
    """Malla reduïda centrada a la caixa de la peça, i els plans fixos (eix, sentit, coordenada)."""
    low = pc.simplify(mesh, CARES_PREVIA) if len(mesh.faces) > CARES_PREVIA else mesh
    c0 = mesh.bounds.mean(0)
    plans_ = []
    for p, n in plans(mesh, tipus):
        k = int(np.argmax(np.abs(n)))
        plans_.append(dict(k=k, s=int(np.sign(n[k])), c=float(p[k] - c0[k])))
    return dict(v=np.round(low.vertices - c0, 4).ravel().tolist(), f=low.faces.ravel().tolist(),
                ext=float(max(mesh.extents)), plans=plans_, yaw=_yaw(tipus), pitch=22.0)


_JS = r"""
export default function({ data, parentElement, setTriggerValue }) {
  let root = parentElement.querySelector('.ajust');
  if (!root) { root = document.createElement('div'); root.className = 'ajust'; parentElement.appendChild(root); }
  const S = root.__s || (root.__s = { t: [0, 0, 0], r: [0, 0, 0], cap: true });
  const rad = Math.PI / 180, ext = data.ext, V0 = data.v, F = data.f, nf = F.length / 3;
  const VISTES = [
    { nom: 'Planta', ax: [0, 1], dep: 2, sg: 1, rot: 2, et: ['X', 'Y', 'Gir Z'] },
    { nom: 'Alçat', ax: [0, 2], dep: 1, sg: -1, rot: 1, et: ['X', 'Z', 'Gir Y'] },
    { nom: 'Perfil', ax: [1, 2], dep: 0, sg: 1, rot: 0, et: ['Y', 'Z', 'Gir X'] },
    { nom: 'Isomètrica', iso: true }];
  root.innerHTML = '<div class="grid"></div>';
  const grid = root.querySelector('.grid');
  const sync = (kind, ax, val, from) => root.querySelectorAll(`input[data-k="${kind}${ax}"]`).forEach(i => {
    if (i !== from) i.value = val; i.nextElementSibling.textContent = fmt(kind, val); });
  const fmt = (kind, v) => kind === 't' ? `${(+v).toFixed(1)} %` : `${v}°`;
  const cells = VISTES.map(v => {
    const c = document.createElement('div'); c.className = 'cel';
    c.innerHTML = `<div class="tit">${v.nom}</div><canvas></canvas>`;
    if (!v.iso) {
      const sl = [['t', v.ax[0], v.et[0]], ['t', v.ax[1], v.et[1]], ['r', v.rot, v.et[2]]];
      for (const [kind, ax, et] of sl) {
        const row = document.createElement('label'); row.className = 'sl';
        const val = kind === 't' ? S.t[ax] : S.r[ax];
        row.innerHTML = `<span>${et}</span><input type="range" data-k="${kind}${ax}" min="${kind === 't' ? -60 : -180}"
          max="${kind === 't' ? 60 : 180}" step="${kind === 't' ? 0.5 : 1}" value="${val}"><b>${fmt(kind, val)}</b>`;
        const inp = row.querySelector('input');
        inp.oninput = () => { (kind === 't' ? S.t : S.r)[ax] = +inp.value; sync(kind, ax, inp.value, inp); draw(); };
        c.appendChild(row);
      }
    } else {
      const b = document.createElement('div'); b.className = 'btns';
      b.innerHTML = `<div class="seg"><button data-cap="1">Generar cara</button><button data-cap="0">Deixar buit</button></div>
        <button class="rst">Restableix</button><button class="ok">Continua</button><button class="bk">← Canvia d'encaix</button>`;
      c.appendChild(b);
    }
    grid.appendChild(c);
    return { v, cv: c.querySelector('canvas') };
  });
  const segs = root.querySelectorAll('[data-cap]');
  const pintaCap = () => segs.forEach(b => b.classList.toggle('on', (b.dataset.cap === '1') === S.cap));
  segs.forEach(b => b.onclick = () => { S.cap = b.dataset.cap === '1'; pintaCap(); });
  pintaCap();
  root.querySelector('.rst').onclick = () => { S.t = [0, 0, 0]; S.r = [0, 0, 0];
    root.querySelectorAll('input[data-k]').forEach(i => { i.value = 0; i.nextElementSibling.textContent = fmt(i.dataset.k[0], 0); }); draw(); };
  root.querySelector('.ok').onclick = () => setTriggerValue('tria', { t: S.t.map(x => x * ext / 100), r: S.r, cap: S.cap });
  root.querySelector('.bk').onclick = () => setTriggerValue('enrere', true);

  const L = [-0.4, -0.8, 0.45], ln = Math.hypot(...L);
  const transforma = () => {   // Rz·Ry·Rx al voltant del centre i desplaçament (el centre és l'origen)
    const [a, b, c] = S.r.map(x => x * rad), ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b),
          cc = Math.cos(c), sc = Math.sin(c);
    const M = [[cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa],
               [sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa], [-sb, cb * sa, cb * ca]];
    const t = S.t.map(x => x * ext / 100), out = new Float32Array(V0.length);
    for (let i = 0; i < V0.length; i += 3) for (let j = 0; j < 3; j++)
      out[i + j] = M[j][0] * V0[i] + M[j][1] * V0[i + 1] + M[j][2] * V0[i + 2] + t[j];
    return out;
  };
  const caixa = (p) => {   // bloc darrere del pla (cap al costat que s'elimina): 8 vèrtexs i 12 triangles
    const T = 0.3 * ext, H = 0.8 * ext, lo = [-H, -H, -H], hi = [H, H, H];
    if (p.s > 0) { lo[p.k] = p.c - T; hi[p.k] = p.c; } else { lo[p.k] = p.c; hi[p.k] = p.c + T; }
    const v = []; for (let i = 0; i < 8; i++) v.push([i & 1 ? hi[0] : lo[0], i & 2 ? hi[1] : lo[1], i & 4 ? hi[2] : lo[2]]);
    const q = [[0,1,3,2],[4,5,7,6],[0,1,5,4],[2,3,7,6],[0,2,6,4],[1,3,7,5]], tr = [];
    for (const [a, b, c, d] of q) { tr.push([v[a], v[b], v[c]], [v[a], v[c], v[d]]); }
    return tr;
  };
  const caixes = data.plans.map(caixa);
  const draw = () => {
    const V = transforma();
    for (const { v, cv } of cells.map((c, i) => ({ v: VISTES[i], cv: c.cv }))) {
      const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
      if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
      const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
      const sc = 0.5 * Math.min(w, h) / (0.8 * ext), ox = w / 2, oy = h / 2;
      let P;   // p → [x pantalla, y pantalla, profunditat (més gran = més lluny)]
      if (v.iso) {
        const a = data.yaw * rad, b = data.pitch * rad, ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b);
        P = (x, y, z) => { const X = x * ca - y * sa, Y = x * sa + y * ca;
          return [ox + X * sc, oy - (Y * sb + z * cb) * sc, Y * cb - z * sb]; };
      } else {
        const [u, vv] = v.ax;
        P = (x, y, z) => { const p = [x, y, z]; return [ox + p[u] * sc, oy - p[vv] * sc, -v.sg * p[v.dep]]; };
      }
      const tri = [];
      for (const bx of caixes) for (const t of bx) {
        const A = P(...t[0]), B = P(...t[1]), C = P(...t[2]);
        tri.push([(A[2] + B[2] + C[2]) / 3 + 1e3, A, B, C, null]);   // els blocs, sempre al darrere
      }
      for (let i = 0; i < nf; i++) {
        const a = F[3 * i], b = F[3 * i + 1], c = F[3 * i + 2];
        const pa = [V[3*a], V[3*a+1], V[3*a+2]], pb = [V[3*b], V[3*b+1], V[3*b+2]], pc = [V[3*c], V[3*c+1], V[3*c+2]];
        const A = P(...pa), B = P(...pb), C = P(...pc);
        const e1 = pb.map((x, j) => x - pa[j]), e2 = pc.map((x, j) => x - pa[j]);
        const n = [e1[1]*e2[2]-e1[2]*e2[1], e1[2]*e2[0]-e1[0]*e2[2], e1[0]*e2[1]-e1[1]*e2[0]], nl = Math.hypot(...n) || 1;
        const l = 0.45 + 0.55 * Math.abs((n[0]*L[0] + n[1]*L[1] + n[2]*L[2]) / (nl * ln));
        const cen = pa.map((x, j) => (x + pb[j] + pc[j]) / 3);
        const dins = data.plans.some(p => p.s * (cen[p.k] - p.c) < 0);   // a l'altre costat del pla
        tri.push([(A[2] + B[2] + C[2]) / 3, A, B, C, { l, dins }]);
      }
      tri.sort((p, q) => q[0] - p[0]);
      for (const [, A, B, C, f] of tri) {
        g.beginPath(); g.moveTo(A[0], A[1]); g.lineTo(B[0], B[1]); g.lineTo(C[0], C[1]); g.closePath();
        if (!f) { g.fillStyle = 'rgba(150,160,175,.38)'; g.fill(); continue; }
        const k = Math.round(235 * f.l);
        g.fillStyle = f.dins ? `rgb(${k},${Math.round(k * .3)},${Math.round(k * .25)})` : `rgb(${k},${Math.round(k * .62)},${Math.round(k * .25)})`;
        g.fill(); g.lineWidth = 0.5; g.strokeStyle = 'rgba(60,40,20,.5)'; g.stroke();
      }
    }
  };
  new ResizeObserver(draw).observe(grid);
  draw();
}
"""

_CSS = """
.ajust { font-family: sans-serif; color: var(--st-text-color, inherit); }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; max-width: 1250px; margin: 0 auto; }
@media (min-width: 1100px) { .grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.cel { display: flex; flex-direction: column; gap: 6px; }
.tit { font-weight: 600; text-align: center; }
.cel canvas { width: 100%; aspect-ratio: 1 / 1; border-radius: 14px; background: #f7f7f5;
              border: 1px solid rgba(128,128,128,.35); }
.sl { display: grid; grid-template-columns: 3.2rem 1fr 3.6rem; align-items: center; gap: 6px; font-size: .85rem; }
.sl b { font-weight: 500; text-align: right; }
.btns { display: flex; flex-direction: column; gap: 8px; }
.btns button { border: 1px solid #888; border-radius: 10px; background: transparent; color: inherit;
               padding: 6px 12px; cursor: pointer; }
.btns .ok { background: #ff4b4b; border-color: #ff4b4b; color: white; font-weight: 600; }
.seg { display: flex; } .seg button { flex: 1; } .seg button:first-child { border-radius: 10px 0 0 10px; }
.seg button:last-child { border-radius: 0 10px 10px 0; }
.seg button.on { background: #5a8cdc; border-color: #5a8cdc; color: white; }
"""

_component = None


def tria(mesh, tallable: bool = True):
    """Pas de l'espai de treball: targetes d'encaix i, un cop triat, quatre vistes amb tres
    lliscadors per eix (desplaçar en els dos eixos visibles i girar). Retorna (tipus, desp, cap)."""
    global _component
    import streamlit as st

    from ui import portada
    ss = st.session_state
    tipus = ss.get("encaix_tipus")
    if not tipus:
        k = portada.graella("encaix", TIPUS, "On anirà col·locat?", FRASE)
        if k:
            ss["encaix_tipus"] = k
            st.rerun()
        return None
    portada.capcalera(etiqueta(tipus), "Desplaça i gira la peça: el que queda dins del pla "
                                       "(en vermell) s'elimina.")
    if not tallable:
        st.info("Amb textura la peça no es pot tallar: es manté tal com està.")
        c1, c2 = st.columns(2)
        if c1.button("← Canvia d'encaix", use_container_width=True):
            ss.pop("encaix_tipus")
            st.rerun()
        if c2.button("Continua", type="primary", use_container_width=True):
            return tipus, ZERO, True
        return None
    if _component is None:
        _component = st.components.v2.component("desplegables_ajust", js=_JS, css=_CSS)
    clau = ("ajust_dades", tipus, len(mesh.faces), tuple(np.round(mesh.bounds.ravel(), 3)))
    if ss.get("ajust_clau") != clau:
        ss["ajust_clau"], ss["ajust_dades"] = clau, _dades(mesh, tipus)
    res = _component(data=ss["ajust_dades"], key=f"ajust_{tipus}",
                     on_tria_change=lambda: None, on_enrere_change=lambda: None)
    if res.enrere:
        ss.pop("encaix_tipus")
        st.rerun()
    if res.tria:
        return tipus, tuple(float(x) for x in (*res.tria["t"], *res.tria["r"])), bool(res.tria["cap"])
    return None


def genera_icones(mesh, carpeta, prof: float = 15.0, mida: int = 600) -> None:
    """Dibuixa les nou icones de la graella amb la peça encastada (PNG, via Inkscape)."""
    import subprocess
    import tempfile
    from pathlib import Path
    low = pc.simplify(mesh, 1500)
    marc = (low.bounds.mean(0), 1.05 * float(max(low.extents)))
    for clau, _t, img in TIPUS:
        svg = escena_svg(low, clau, desp_icona(low, clau, prof), width=mida, cares=len(low.faces),
                         marc=marc, pitch=-22 if clau.startswith("sobre") else 22)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "i.svg"
            f.write_text(svg)
            subprocess.run(["inkscape", str(f), "-o", str(Path(carpeta) / img), "-w", str(mida)],
                           check=True, capture_output=True)
