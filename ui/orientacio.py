"""Pas d'orientació: sis vistes del model (cada eix amunt) amb un sol lliscador de gir.

Cada vista és un botó quadrat amb un anell orbital com els dels programes 3D; el lliscador
fa girar totes les malles (reduïdes a ~300 cares) al voltant de la seva vertical, i en
clicar-ne una es tria aquest eix amunt amb el gir actual.
"""
import base64

import numpy as np
import streamlit as st

import papercraft as pc
import vista

CARES_PREVIA = 300
YAW, PITCH = 35.0, 22.0   # càmera fixa de les vistes (graus)


def _dades(mesh, defecte: str) -> dict:
    """Vèrtexs de la malla reduïda per a cada eix amunt, centrats, i triangles comuns."""
    low = pc.simplify(mesh, CARES_PREVIA) if len(mesh.faces) > CARES_PREVIA else mesh
    centre = low.bounds.mean(0)
    V0 = low.vertices - centre
    vistes = []
    for up in pc.UPS:
        M = pc.orientation_matrix(up)[:3, :3]
        V = V0 @ M.T
        vistes.append(dict(up=up, defecte=up == defecte, v=np.round(V, 3).ravel().tolist(),
                           zmin=float(V[:, 2].min()), rmax=float(np.hypot(V[:, 0], V[:, 1]).max())))
    return dict(f=low.faces.ravel().tolist(), vistes=vistes,
                R=float(np.linalg.norm(V0, axis=1).max()), yaw=YAW, pitch=PITCH)


def miniatura(mesh, up: str, turn: float) -> str:
    """Imatge (data URI SVG) del model amb l'orientació triada, per a la ruta de dalt."""
    low = pc.simplify(mesh, CARES_PREVIA) if len(mesh.faces) > CARES_PREVIA else mesh
    m = low.copy()
    m.apply_transform(pc.orientation_matrix(up, turn))
    svg = vista.view_svg(m, ["#c9a77c"] * len(m.faces), width=200, yaw=YAW, pitch=PITCH)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


_JS = r"""
export default function({ data, parentElement, setTriggerValue }) {
  let root = parentElement.querySelector('.orient');
  if (!root) { root = document.createElement('div'); root.className = 'orient'; parentElement.appendChild(root); }
  const S = root.__s || (root.__s = { turn: 0 });
  root.innerHTML = `
    <div class="grid"></div>
    <div class="bar"><span class="lab"></span>
      <input type="range" min="0" max="359" step="1" value="0">
      <button class="z">0°</button></div>`;
  const grid = root.querySelector('.grid'), rng = root.querySelector('input'), lab = root.querySelector('.lab');
  const rad = Math.PI / 180, ya = data.yaw * rad, pi = data.pitch * rad;
  const tiles = data.vistes.map(v => {
    const b = document.createElement('button'); b.className = 'tile';
    b.innerHTML = '<canvas></canvas><span></span>';
    b.querySelector('span').textContent = v.up + ' amunt' + (v.defecte ? ' · del fitxer' : '');
    b.onclick = () => setTriggerValue('tria', { up: v.up, turn: S.turn });
    grid.appendChild(b);
    return { v, cv: b.querySelector('canvas'), V: Float32Array.from(v.v) };
  });
  const draw = () => {
    const t = S.turn * rad;
    for (const T of tiles) {
      const cv = T.cv, dpr = window.devicePixelRatio || 1;
      const w = cv.clientWidth, h = cv.clientHeight;
      if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
      const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
      const sc = 0.42 * Math.min(w, h) / (data.R * 1.15), ox = w / 2, oy = h / 2;
      const P = (x, y, z, turn) => {
        const a = turn + ya, c = Math.cos(a), s = Math.sin(a);
        const X = x * c - y * s, Y = x * s + y * c;
        const Zs = z * Math.cos(pi) + Y * Math.sin(pi);   // alçada a la pantalla; D = profunditat
        return [ox + X * sc, oy - Zs * sc, Y * Math.cos(pi) - z * Math.sin(pi), X, Zs];
      };
      const ring = (front, turn, r, z) => { g.beginPath(); let on = false;
        for (let i = 0; i <= 72; i++) { const th = i * 5 * rad, p = P(r * Math.cos(th), r * Math.sin(th), z, 0);
          // la meitat del fons es dibuixa abans que el model i la del davant després
          const isFront = p[2] < 0; if (isFront !== front) { on = false; continue; }
          on ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]); on = true; } g.stroke(); };
      const r = Math.max(T.v.rmax * 1.12, data.R * 0.35), zr = T.v.zmin;
      g.lineWidth = 2; g.strokeStyle = 'rgba(90,140,220,.85)'; ring(false, 0, r, zr);
      const V = T.V, F = data.f, n = F.length / 3, tri = [];
      for (let i = 0; i < n; i++) {
        const a = F[3 * i], b = F[3 * i + 1], c = F[3 * i + 2];
        const A = P(V[3 * a], V[3 * a + 1], V[3 * a + 2], t), B = P(V[3 * b], V[3 * b + 1], V[3 * b + 2], t),
              C = P(V[3 * c], V[3 * c + 1], V[3 * c + 2], t);
        // normal en l'espai de la càmera (x, profunditat, alçada) i llum fixa; cara doble
        const e1 = [B[3] - A[3], B[2] - A[2], B[4] - A[4]], e2 = [C[3] - A[3], C[2] - A[2], C[4] - A[4]];
        const nx = e1[1] * e2[2] - e1[2] * e2[1], ny = e1[2] * e2[0] - e1[0] * e2[2], nzz = e1[0] * e2[1] - e1[1] * e2[0];
        const nl = Math.hypot(nx, ny, nzz) || 1;
        const l = 0.38 + 0.62 * Math.abs((-0.4 * nx - 0.8 * ny + 0.5 * nzz) / (nl * 1.0198));
        tri.push([(A[2] + B[2] + C[2]) / 3, A, B, C, l]);
      }
      tri.sort((p, q) => q[0] - p[0]);
      for (const [, A, B, C, l] of tri) {
        g.beginPath(); g.moveTo(A[0], A[1]); g.lineTo(B[0], B[1]); g.lineTo(C[0], C[1]); g.closePath();
        const k = Math.round(215 * l); g.fillStyle = `rgb(${k},${Math.round(k * 0.85)},${Math.round(k * 0.62)})`;
        g.fill(); g.lineWidth = 0.6; g.strokeStyle = 'rgba(60,40,20,.55)'; g.stroke();
      }
      g.lineWidth = 2; g.strokeStyle = 'rgba(90,140,220,.85)'; ring(true, 0, r, zr);
      // punta de l'anell: davant del model, gira amb ell
      const d = P(r * Math.cos(t), r * Math.sin(t), zr, 0);
      g.beginPath(); g.arc(d[0], d[1], 5, 0, 2 * Math.PI); g.fillStyle = '#e8503a'; g.fill();
      g.lineWidth = 1.5; g.strokeStyle = 'white'; g.stroke();
    }
    lab.textContent = `Gir al voltant de la vertical: ${S.turn}°`;
  };
  rng.value = S.turn;
  rng.oninput = () => { S.turn = +rng.value; draw(); };
  root.querySelector('.z').onclick = () => { S.turn = 0; rng.value = 0; draw(); };
  new ResizeObserver(draw).observe(grid);
  draw();
}
"""

_CSS = """
.orient { font-family: sans-serif; color: var(--st-text-color, inherit); }
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px;
        max-width: 780px; margin: 0 auto; }
@media (min-width: 1000px) { .grid { grid-template-columns: repeat(6, minmax(0, 1fr)); max-width: 1180px; } }
.tile { position: relative; aspect-ratio: 1 / 1; padding: 0; border-radius: 14px; overflow: hidden;
        border: 1px solid rgba(128,128,128,.35); background: #f7f7f5; cursor: pointer;
        transition: transform .12s, box-shadow .12s; }
.tile canvas { position: absolute; left: 0; top: 0; width: 100%; height: 80%; }
.tile span { position: absolute; left: 0; right: 0; bottom: 0; height: 20%; display: flex;
             align-items: center; justify-content: center; font-weight: 600; font-size: .85rem;
             background: #1b1e27; color: #eee; }
.tile:hover { transform: translateY(-3px); box-shadow: 0 8px 22px rgba(0,0,0,.25); border-color: #5a8cdc; }
.bar { display: flex; gap: 14px; align-items: center; justify-content: center; margin: 22px auto 0;
       max-width: 780px; }
.bar input { flex: 1; }
.bar button { border: 1px solid #888; border-radius: 12px; background: transparent; color: inherit;
              padding: 2px 12px; cursor: pointer; }
"""

_component = None


def tria(mesh, defecte: str) -> tuple[str, float] | None:
    """Mostra les vistes; retorna (eix amunt, gir) quan se'n clica una, o None."""
    global _component
    if _component is None:
        _component = st.components.v2.component("desplegables_orientacio", js=_JS, css=_CSS)
    ss = st.session_state
    clau = ("orient_dades", len(mesh.faces), tuple(np.round(mesh.bounds.ravel(), 3)), defecte)
    if ss.get("orient_clau") != clau:
        ss["orient_clau"], ss["orient_dades"] = clau, _dades(mesh, defecte)
    res = _component(data=ss["orient_dades"], key="orientacio", on_tria_change=lambda: None)
    if res.tria:
        return res.tria["up"], float(res.tria["turn"])
    return None
