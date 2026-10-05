"""Llenç per dibuixar a mà sobre una cara (component de Streamlit).

Es mostra la forma de la cara; els traços tornen a Python en mm locals de la cara.
"""
from __future__ import annotations

import numpy as np
import streamlit as st

_JS = r"""
export default function(component) {
  const { data, setStateValue, parentElement } = component;
  let root = parentElement.querySelector('.dibuix');
  if (!root) {
    root = document.createElement('div');
    root.className = 'dibuix';
    parentElement.appendChild(root);
  }
  root.innerHTML = '';
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('width', data.width);
  svg.setAttribute('height', data.height);
  svg.style.border = '1px solid #bbb';
  svg.style.background = 'white';
  svg.style.touchAction = 'none';
  svg.style.cursor = 'crosshair';
  root.appendChild(svg);
  const face = document.createElementNS(NS, 'path');
  face.setAttribute('d', data.outline);
  face.setAttribute('fill', '#eef3f8');
  face.setAttribute('stroke', '#5a7fa8');
  face.setAttribute('fill-rule', 'evenodd');
  svg.appendChild(face);
  let strokes = (data.strokes || []).map(s => s.slice());
  const redraw = () => {
    svg.querySelectorAll('.traç').forEach(e => e.remove());
    for (const s of strokes) {
      const pl = document.createElementNS(NS, 'polyline');
      pl.setAttribute('class', 'traç');
      pl.setAttribute('fill', 'none');
      pl.setAttribute('stroke', data.color || '#1f4e79');
      pl.setAttribute('stroke-width', data.pen || 2);
      pl.setAttribute('stroke-linecap', 'round');
      pl.setAttribute('stroke-linejoin', 'round');
      pl.setAttribute('points', s.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' '));
      svg.appendChild(pl);
    }
  };
  redraw();
  let cur = null;
  const at = e => { const r = svg.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  svg.onpointerdown = e => { cur = [at(e)]; strokes.push(cur); svg.setPointerCapture(e.pointerId); };
  svg.onpointermove = e => {
    if (!cur) return;
    const p = at(e), q = cur[cur.length - 1];
    if (Math.hypot(p[0] - q[0], p[1] - q[1]) > 1.5) { cur.push(p); redraw(); }
  };
  svg.onpointerup = () => { if (cur && cur.length < 2) strokes.pop(); cur = null; setStateValue('strokes', strokes); };
  const bar = document.createElement('div');
  bar.style.marginTop = '6px';
  const button = (label, fn) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.style.marginRight = '6px';
    b.onclick = fn;
    bar.appendChild(b);
  };
  button('↶ Desfés', () => { strokes.pop(); redraw(); setStateValue('strokes', strokes); });
  button('✕ Esborra', () => { strokes = []; redraw(); setStateValue('strokes', strokes); });
  root.appendChild(bar);
}
"""

_component = st.components.v2.component("desplegables_dibuix", js=_JS)


def draw_on_face(shape, key: str, strokes_mm=None, color: str = "#1f4e79",
                 width_px: int = 460) -> list:
    """Mostra el llenç per a la forma `shape` (mm locals) i retorna els traços en mm."""
    x0, y0, x1, y1 = shape.bounds
    pad = 10
    scale = (width_px - 2 * pad) / max(x1 - x0, 1e-6)
    height = int((y1 - y0) * scale + 2 * pad)
    if height > 420:  # cares molt altes: limita l'alçada
        scale = (420 - 2 * pad) / max(y1 - y0, 1e-6)
        height = 420
    to_px = lambda p: ((p[0] - x0) * scale + pad, (y1 - p[1]) * scale + pad)
    rings = []
    for g in getattr(shape, "geoms", [shape]):
        for r in [g.exterior, *g.interiors]:
            pts = [to_px(p) for p in r.coords]
            rings.append("M " + " L ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + " Z")
    px_strokes = [[list(to_px(p)) for p in s] for s in (strokes_mm or [])]
    res = _component(data={"width": width_px, "height": height, "outline": " ".join(rings),
                           "strokes": px_strokes, "color": color, "pen": 2},
                     on_strokes_change=lambda: None, key=key)
    raw = getattr(res, "strokes", None) if res is not None else None
    if raw is None:
        return list(strokes_mm or [])
    return [[(x0 + (px - pad) / scale, y1 - (py - pad) / scale) for px, py in s]
            for s in raw if len(s) >= 2]
