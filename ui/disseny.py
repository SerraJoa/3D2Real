"""Pas Disseny: una imatge per cara o per un grup de cares, triades sobre el model en 3D.

El model simplificat es pot girar arrossegant; en clicar una cara es tria (o es destria), i la
imatge carregada s'hi aplica amb "Aplica". Les cares són les mateixes que fan servir el desplegable
i les cares (`decor.face_frames`), i el resultat és un {índex de cara: DecorSpec} que les branques
ja saben aplicar.
"""
import numpy as np
import streamlit as st

import dibuix
from ui import carpeta, pintura

YAW, PITCH = 35.0, 25.0

_JS = r"""
export default function({ data, parentElement, setStateValue, setTriggerValue }) {
  let root = parentElement.querySelector('.dis');
  if (!root) { root = document.createElement('div'); root.className = 'dis'; parentElement.appendChild(root); }
  const S = root.__s || (root.__s = { yaw: data.yaw, pitch: data.pitch, sel: new Set(), rev: data.rev });
  S.pot = data.pot;
  if (S.rev !== data.rev) { S.rev = data.rev; S.sel = new Set(); }
  root.innerHTML = `<canvas></canvas>
    <div class="bar"><span class="lab"></span><span class="gap"></span>
      <button class="all">Totes</button><button class="none">Cap</button></div>`;
  const cv = root.querySelector('canvas'), lab = root.querySelector('.lab');
  const V = Float32Array.from(data.v), F = data.f, FR = data.fr, nf = F.length / 3;
  // arestes entre cares diferents (o de vora): es dibuixen com a contorn de la cara
  const ek = new Map();
  for (let i = 0; i < nf; i++) for (let e = 0; e < 3; e++) {
    const a = F[3 * i + e], b = F[3 * i + (e + 1) % 3], k = a < b ? a * 1e6 + b : b * 1e6 + a;
    (ek.get(k) || ek.set(k, []).get(k)).push(i);
  }
  const border = Array.from({ length: nf }, () => [false, false, false]);
  for (let i = 0; i < nf; i++) for (let e = 0; e < 3; e++) {
    const a = F[3 * i + e], b = F[3 * i + (e + 1) % 3], k = a < b ? a * 1e6 + b : b * 1e6 + a;
    const o = ek.get(k).filter(j => j !== i);
    border[i][e] = o.length === 0 || o.some(j => FR[j] !== FR[i]);
  }
  const rad = Math.PI / 180;
  let tris = [];
  const draw = () => {
    const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    const sc = 0.46 * Math.min(w, h) / data.R, ox = w / 2, oy = h / 2;
    const ya = S.yaw * rad, pi = S.pitch * rad, c = Math.cos(ya), s = Math.sin(ya);
    const P = new Array(V.length / 3);
    for (let i = 0; i < P.length; i++) {
      const x = V[3 * i], y = V[3 * i + 1], z = V[3 * i + 2];
      const X = x * c - y * s, Y = x * s + y * c, Zs = z * Math.cos(pi) + Y * Math.sin(pi);
      P[i] = [ox + X * sc, oy - Zs * sc, Y * Math.cos(pi) - z * Math.sin(pi), X, Zs];
    }
    tris = [];
    for (let i = 0; i < nf; i++) {
      const A = P[F[3 * i]], B = P[F[3 * i + 1]], C = P[F[3 * i + 2]];
      const e1 = [B[3] - A[3], B[2] - A[2], B[4] - A[4]], e2 = [C[3] - A[3], C[2] - A[2], C[4] - A[4]];
      const nx = e1[1] * e2[2] - e1[2] * e2[1], ny = e1[2] * e2[0] - e1[0] * e2[2], nz = e1[0] * e2[1] - e1[1] * e2[0];
      const nl = Math.hypot(nx, ny, nz) || 1;
      const l = 0.45 + 0.55 * Math.abs((-0.4 * nx - 0.8 * ny + 0.5 * nz) / (nl * 1.0198));
      tris.push([(A[2] + B[2] + C[2]) / 3, A, B, C, l, i]);
    }
    tris.sort((p, q) => q[0] - p[0]);
    for (const [, A, B, C, l, i] of tris) {
      const f = FR[i], sel = S.sel.has(f), dec = data.dec[f];
      const base = sel ? [236, 128, 40] : dec ? [70, 130, 205] : [205, 188, 150];
      const col = `rgb(${Math.round(base[0] * l)},${Math.round(base[1] * l)},${Math.round(base[2] * l)})`;
      g.beginPath(); g.moveTo(A[0], A[1]); g.lineTo(B[0], B[1]); g.lineTo(C[0], C[1]); g.closePath();
      g.fillStyle = col; g.fill(); g.lineWidth = 0.8; g.strokeStyle = col; g.stroke();
      g.lineWidth = 1.4; g.strokeStyle = 'rgba(30,25,20,.8)';
      const Q = [A, B, C];
      for (let e = 0; e < 3; e++) if (border[i][e]) {
        g.beginPath(); g.moveTo(Q[e][0], Q[e][1]); g.lineTo(Q[(e + 1) % 3][0], Q[(e + 1) % 3][1]); g.stroke();
      }
    }
    const t = [...S.sel].sort((a, b) => a - b).map(k => 'C' + (k + 1));
    lab.textContent = S.pot ? 'Pot de pintura: clica una cara per pintar-la' : t.length ? `${t.length} triades: ${t.slice(0, 12).join(', ')}${t.length > 12 ? '…' : ''}`
                               : 'Clica les cares on vols la imatge · arrossega per girar';
  };
  const hit = (x, y) => {
    for (let k = tris.length - 1; k >= 0; k--) {
      const [, A, B, C, , i] = tris[k];
      const d = (B[1] - C[1]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[1] - C[1]);
      if (Math.abs(d) < 1e-9) continue;
      const a = ((B[1] - C[1]) * (x - C[0]) + (C[0] - B[0]) * (y - C[1])) / d;
      const b = ((C[1] - A[1]) * (x - C[0]) + (A[0] - C[0]) * (y - C[1])) / d;
      if (a >= 0 && b >= 0 && 1 - a - b >= 0) return FR[i];
    }
    return null;
  };
  const envia = () => setStateValue('sel', [...S.sel].sort((a, b) => a - b));
  let down = null;
  cv.onpointerdown = e => { down = { x: e.clientX, y: e.clientY, yaw: S.yaw, pitch: S.pitch, moved: false };
                            cv.setPointerCapture(e.pointerId); };
  cv.onpointermove = e => {
    if (!down) return;
    const dx = e.clientX - down.x, dy = e.clientY - down.y;
    if (Math.hypot(dx, dy) > 4) down.moved = true;
    if (down.moved) { S.yaw = down.yaw - dx * 0.5; S.pitch = Math.max(-89, Math.min(89, down.pitch + dy * 0.4)); draw(); }
  };
  cv.onpointerup = e => {
    const d = down; down = null;
    if (!d || d.moved) return;
    const r = cv.getBoundingClientRect(), f = hit(e.clientX - r.left, e.clientY - r.top);
    if (f === null) return;
    if (S.pot) { setTriggerValue('clic', { f }); return; }
    S.sel.has(f) ? S.sel.delete(f) : S.sel.add(f);
    draw(); envia();
  };
  root.querySelector('.all').onclick = () => { S.sel = new Set(FR); draw(); envia(); };
  root.querySelector('.none').onclick = () => { S.sel = new Set(); draw(); envia(); };
  new ResizeObserver(draw).observe(cv);
  draw();
}
"""

_CSS = """
.dis { font-family: sans-serif; color: var(--st-text-color, inherit); }
.dis canvas { width: 100%; height: 520px; border-radius: 14px; background: #f1efe9;
              border: 1px solid rgba(128,128,128,.35); touch-action: none; cursor: pointer; display: block; }
.dis .bar { display: flex; gap: 8px; align-items: center; margin-top: 8px; font-size: .9rem; }
.dis .gap { flex: 1; }
.dis button { border: 1px solid #888; border-radius: 12px; background: transparent; color: inherit;
              padding: 2px 12px; cursor: pointer; }
"""

_component = None
NOMS = {"uv": "Pell (UV)", "grup": "Grup", "cara": "Cara"}


def _ranges(ks: list[int]) -> str:
    out, i = [], 0
    ks = sorted(ks)
    while i < len(ks):
        j = i
        while j + 1 < len(ks) and ks[j + 1] == ks[j] + 1:
            j += 1
        out.append(f"C{ks[i] + 1}" if i == j else f"C{ks[i] + 1}–C{ks[j] + 1}")
        i = j + 1
    return ", ".join(out)


def _dades(mesh, frames, ops, pot) -> dict:
    centre = mesh.bounds.mean(0)
    V = mesh.vertices - centre
    fr = np.zeros(len(mesh.faces), dtype=int)
    for f in frames:
        fr[f.faces] = f.index
    amb = {k for o in ops for k in o["cares"]}
    return dict(v=np.round(V, 3).ravel().tolist(), f=mesh.faces.ravel().tolist(), fr=fr.tolist(),
                dec=[int(k in amb) for k in range(len(frames))],
                R=float(np.linalg.norm(V, axis=1).max()), yaw=YAW, pitch=PITCH, pot=bool(pot),
                rev=st.session_state.get("dis_rev", 0))


def _descriu(o: dict) -> str:
    quin = {"uv": "pell", "imatge": "imatge", "color": f"color {o.get('color', '')}", "dibuix": "dibuix"}[o["tipus"]]
    return f"{NOMS[o['nivell']]} · {_ranges(o['cares'])} · {quin}"


def capes_de(mesh, frames) -> list:
    """Les capes del disseny (es buiden si la malla ha canviat)."""
    ss = st.session_state
    sig = (len(mesh.faces), len(frames), round(float(mesh.area), 1))
    if ss.get("dis_sig") != sig:
        ss["dis_sig"], ss["dis_ops"], ss["dis_rev"] = sig, [], ss.get("dis_rev", 0) + 1
    return ss["dis_ops"]


def pagina(mesh, frames, laser: bool, textura=None, accio: str = "Aplica el disseny") -> dict | None:
    """Pas Disseny. `textura` és la UV passada a `mesh` (o None). Retorna {cara: DecorSpec}
    quan es clica el botó final, o None.

    Capes (en aquest ordre): pell UV, grup de cares i cara; no són excloents. El pot de pintura
    pinta amb un clic. Al làser tot es passa a gris: negre = tall, la resta = potència.
    """
    global _component
    if _component is None:
        _component = st.components.v2.component("desplegables_disseny", js=_JS, css=_CSS)
    ss = st.session_state
    ops: list = capes_de(mesh, frames)
    pot = bool(ss.get("dis_pot")) and ss.get("dis_tipus") == "color" and ss.get("dis_nivell") != "uv"
    visor_col, ctrl = st.columns([3, 2], gap="large")
    with visor_col:
        res = _component(data=_dades(mesh, frames, ops, pot), key="disseny_triades",
                         on_sel_change=lambda: None, on_clic_change=lambda: None)
    sel = [int(k) for k in (res.sel or []) if int(k) < len(frames)]
    with ctrl:
        nivells = (["uv"] if textura is not None else []) + ["grup", "cara"]
        nivell = st.radio("Nivell", nivells, horizontal=True, key="dis_nivell", format_func=NOMS.get,
                          help="Les capes es dibuixen en l'ordre pell → grup → cara.")
        if nivell == "uv":
            st.caption("Posa la pell del model a les cares triades (o a totes si no n'hi ha cap).")
            if st.button("Posa la pell", use_container_width=True):
                ops.append(dict(nivell="uv", tipus="uv", cares=sel or list(range(len(frames)))))
                ss["dis_rev"] += 1
                st.rerun()
        else:
            tipus = st.radio("Què", ["imatge", "color"] + (["dibuix"] if nivell == "cara" else []),
                             horizontal=True, key="dis_tipus",
                             format_func={"imatge": "Imatge", "color": "Color", "dibuix": "Dibuix"}.get)
            nou = dict(nivell=nivell, tipus=tipus)
            llest = bool(sel)
            if tipus == "imatge":
                up = st.file_uploader("Imatge", type=["png", "jpg", "jpeg"], key="dis_img")
                if up is None:
                    triades = carpeta.tria((".png", ".jpg", ".jpeg"), "dis_img_carpeta")
                    up = triades[0] if triades else None
                nou.update(imatge=up.getvalue() if up else None,
                           ajust=st.radio("Ajust", ["omplir", "encabir"], horizontal=True, key="dis_fit"))
                llest = llest and up is not None
            elif tipus == "color":
                nou["color"] = st.color_picker("Color", "#1f4e79", key="dis_color")
                st.toggle("Pot de pintura: un clic pinta la cara", key="dis_pot")
            else:
                nou["color"] = st.color_picker("Color del traç", "#000000", key="dis_color_d")
                if len(sel) == 1:
                    nou["traços"] = dibuix.draw_on_face(frames[sel[0]].shape, f"dib_{sel[0]}_{ss['dis_rev']}",
                                                        [], nou["color"])
                else:
                    st.info("Tria una sola cara per dibuixar-hi.")
                    llest = False
            if st.button("Aplica a les triades", disabled=not llest, use_container_width=True):
                ops.append(dict(nou, cares=sel))
                ss["dis_rev"] += 1
                st.rerun()
        if res.clic is not None and pot:
            ops.append(dict(nivell=nivell, tipus="color", color=ss.get("dis_color", "#1f4e79"),
                            cares=[int(res.clic["f"])]))
            ss["dis_rev"] += 1
            st.rerun()
        marc = st.number_input("Marc (mm, 0 = sense marc)", 0.0, 50.0, 0.0, 0.5, key="dis_marc")
        llindar = 20
        if laser:
            st.caption("Al làser tot es passa a gris: el negre és tall i la resta, potència de gravat.")
            llindar = st.slider("Tall: més fosc que", 0, 128, 20, key="dis_thr")
        if ops:
            st.markdown("**Capes**")
            for i, o in enumerate(ops):
                c1, c2 = st.columns([6, 1])
                c1.caption(_descriu(o))
                if c2.button("✖", key=f"dis_del_{i}_{ss['dis_rev']}", help="Treu aquesta capa"):
                    ops.pop(i)
                    ss["dis_rev"] += 1
                    st.rerun()
        if accio and st.button(accio, type="primary", use_container_width=True):
            return pintura.decoracio(frames, mesh, textura, ops, marc, laser, llindar)
    return None
