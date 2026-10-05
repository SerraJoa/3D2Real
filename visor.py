"""Previsualització 3D del model muntat, per a les tres branques (component de Streamlit).

Cada peça es converteix en un sòlid al seu lloc del model: les plaques i els suports de la
branca de cares, les capes, costelles i tiges de la laminació, o les peces de paper plegades.
El visor és WebGL pur (sense biblioteques externes): girar arrossegant, ampliar amb la roda o
pessigant, separar les peces, tallar el model amb un pla i fer transparent o amagar cada
tipus de peça.
"""
from __future__ import annotations

import base64
import math
import re
from dataclasses import dataclass, field

import numpy as np
import trimesh

PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#76b7b2", "#edc948", "#9c755f",
           "#ff9da7", "#bab0ac", "#e15759"]
WOOD = ("#dcc29a", "#c9a877")       # capes alternes / plaques
SUPPORT = "#e39b3a"
RIB = "#b5523b"
ROD = "#8c8c8c"
EDGE_ANGLE = math.radians(25)       # arestes que es dibuixen (a més de les vores)


@dataclass
class Solid:
    kind: str                       # grup de la llegenda ("Plaques", "Suports"…)
    mesh: trimesh.Trimesh
    color: str
    offset: np.ndarray = field(default_factory=lambda: np.zeros(3))  # on va en separar (× radi)
    edges: str = "vives"            # arestes dibuixades: "vives" (i vores), "totes" o "cap"


def prism(shape, M: np.ndarray, z0: float, z1: float) -> trimesh.Trimesh | None:
    """Prisma de la forma 2D entre z0 i z1 (coordenades locals), portat a 3D per M."""
    from laser import solid
    return solid(shape, M, z0, z1)


def _away(m: trimesh.Trimesh, center: np.ndarray) -> np.ndarray:
    d = m.centroid - center
    n = np.linalg.norm(d)
    return d / n if n > 1e-9 else np.zeros(3)


def cares_solids(res) -> list[Solid]:
    """Plaques (un color per grup unit si n'hi ha més d'un), suports i costelles."""
    ex = res.extra
    center = ex["mesh"].centroid
    group = ex["group"]
    order = {g: i for i, g in enumerate(dict.fromkeys(group[k] for k in sorted(group)))}
    many = len(order) > 1
    out = []
    for name, shape, M, z0, z1 in ex["assembly"]:
        m = prism(shape, M, z0, z1)
        if m is None:
            continue
        if name.startswith("C"):
            k = int(name[1:]) - 1
            color = PALETTE[order[group[k]] % len(PALETTE)] if many else WOOD[0]
            out.append(Solid("Plaques", m, color, _away(m, center)))
        elif name.startswith("S"):
            out.append(Solid("Suports", m, SUPPORT))
        else:
            out.append(Solid("Costelles", m, RIB))
    return out


def layers_solids(res) -> list[Solid]:
    """Capes (s'obren cap amunt en separar), costelles (surten de costat) i tiges."""
    ex = res.extra
    layer = lambda name: int(re.match(r"L(\d+)", name).group(1)) - 1
    K = max([layer(n) + 1 for n, *_ in ex["assembly"] if n.startswith("L")] or [1])
    out = []
    for name, shape, M, z0, z1 in ex["assembly"]:
        m = prism(shape, M, z0, z1)
        if m is None:
            continue
        if name.startswith("L"):
            k = layer(name)
            out.append(Solid("Capes", m, WOOD[k % 2], np.array([0.0, 0.0, 1.5 * k / K])))
        else:
            out.append(Solid("Costelles", m, RIB, M[:3, 2] * 1.2))
    for x, y, za, zb, d in ex.get("columns", []):
        rod = trimesh.creation.cylinder(radius=d / 2, height=zb - za, sections=16)
        rod.apply_translation([x, y, (za + zb) / 2])
        out.append(Solid("Tiges", rod, ROD))
    return out


def paper_solids(res) -> list[Solid]:
    """Les peces de paper plegades al seu lloc, cadascuna d'un color."""
    m = res.mesh
    center = m.centroid
    out = []
    for i, piece in enumerate(res.pieces):
        fs = sorted(piece.tris)
        if not fs:
            continue
        sub = m.submesh([fs], append=True)
        out.append(Solid("Peces", sub, PALETTE[i % len(PALETTE)], 0.6 * _away(sub, center)))
    return out


def model_solids(mesh: trimesh.Trimesh, kind: str, color: str, edges: str = "vives",
                 max_faces: int = 60000) -> list[Solid]:
    """La malla tal qual (el model carregat o el simplificat). Si és molt gran, per veure-la
    se'n fa una còpia amb `max_faces` cares (el visor aniria lent)."""
    m = mesh
    if len(m.faces) > max_faces:
        import papercraft as pc
        m = pc.simplify(m, max_faces)
    m = trimesh.Trimesh(m.vertices, m.faces, process=False)  # sense textura ni colors
    return [Solid(kind, m, color, edges=edges)]


def _edges(m: trimesh.Trimesh, mode: str = "vives") -> np.ndarray:
    """Segments a dibuixar: vores i arestes vives (no les diagonals de les cares planes),
    totes les arestes (per veure els triangles) o cap."""
    if mode == "cap":
        return np.zeros((0, 3))
    if mode == "totes":
        return m.vertices[m.edges_unique].reshape(-1, 3)
    keep = [m.face_adjacency_edges[m.face_adjacency_angles > EDGE_ANGLE]]
    lone = trimesh.grouping.group_rows(m.edges_sorted, require_count=1)
    if len(lone):
        keep.append(m.edges_sorted[lone])
    e = np.vstack(keep) if keep else np.zeros((0, 2), int)
    return m.vertices[e].reshape(-1, 3)


def _b64(a: np.ndarray, dtype) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode()


def _rgb(hex_: str) -> list[int]:
    h = hex_.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def pack(solids: list[Solid]) -> dict:
    """Dades per al visor: triangles, normals, colors, desplaçaments i arestes, en base64."""
    kinds = list(dict.fromkeys(s.kind for s in solids))
    pos, nrm, col, off, lpos, loff, lkind = [], [], [], [], [], [], []
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for s in solids:
        m = s.mesh
        n = len(m.faces)
        k = kinds.index(s.kind)
        pos.append(m.triangles.reshape(-1, 3))
        nrm.append(np.repeat(m.face_normals, 3, axis=0))
        col.append(np.tile(_rgb(s.color) + [k], (3 * n, 1)))
        off.append(np.tile(s.offset, (3 * n, 1)))
        e = _edges(m, s.edges)
        lpos.append(e)
        loff.append(np.tile(s.offset, (len(e), 1)))
        lkind.append(np.full(len(e), k))
        lo, hi = np.minimum(lo, m.bounds[0]), np.maximum(hi, m.bounds[1])
    cat = lambda xs, w: np.vstack(xs) if xs else np.zeros((0, w))
    center = (lo + hi) / 2 if solids else np.zeros(3)
    radius = float(np.linalg.norm(hi - lo) / 2) if solids else 1.0
    return dict(
        kinds=kinds, center=center.tolist(), radius=radius,
        explode=bool(any(np.any(s.offset) for s in solids)),  # si no, no cal el control
        lo=lo.tolist() if solids else [0, 0, 0], hi=hi.tolist() if solids else [0, 0, 0],
        pos=_b64(cat(pos, 3), np.float32), nrm=_b64(cat(nrm, 3), np.float32),
        col=_b64(cat(col, 4), np.uint8), off=_b64(cat(off, 3), np.float32),
        lpos=_b64(cat(lpos, 3), np.float32), loff=_b64(cat(loff, 3), np.float32),
        lkind=_b64(np.concatenate(lkind) if lkind else np.zeros(0), np.uint8),
        triangles=int(sum(len(s.mesh.faces) for s in solids)))


_JS = r"""
const VS = `
attribute vec3 aPos; attribute vec3 aNrm; attribute vec3 aOff; attribute vec4 aCol;
uniform mat4 uMVP; uniform float uExplode; uniform float uAlpha[8];
varying vec3 vNrm; varying vec3 vCol; varying float vA; varying vec3 vW;
void main() {
  int k = int(aCol.a * 255.0 + 0.5);
  float a = 1.0;
  for (int i = 0; i < 8; i++) if (i == k) a = uAlpha[i];
  vec3 p = aPos + aOff * uExplode;
  vW = p; vNrm = aNrm; vCol = aCol.rgb; vA = a;
  gl_Position = uMVP * vec4(p, 1.0);
}`;
const FS = `
precision mediump float;
uniform vec3 uLight; uniform vec4 uClip; uniform float uPass; uniform float uLine;
varying vec3 vNrm; varying vec3 vCol; varying float vA; varying vec3 vW;
void main() {
  if (vA < 0.01 || dot(vW, uClip.xyz) > uClip.w) discard;
  if (uPass < 0.5 && vA < 0.99) discard;
  if (uPass > 0.5 && vA >= 0.99) discard;
  if (uLine > 0.5) { gl_FragColor = vec4(0.12, 0.12, 0.14, 0.55 * vA); return; }
  vec3 n = normalize(vNrm); vec3 c = vCol;
  if (!gl_FrontFacing) { n = -n; c *= 0.55; }  // per dins (es veu en tallar)
  float l = 0.42 + 0.58 * max(dot(n, uLight), 0.0) + 0.12 * max(dot(n, -uLight), 0.0);
  gl_FragColor = vec4(c * l, vA);
}`;

function m4mul(a, b) {
  const o = new Float32Array(16);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
    let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k]; o[i * 4 + j] = s;
  }
  return o;
}
function lookAt(e, c, u) {
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const nrm = a => { const l = Math.hypot(...a) || 1; return a.map(x => x / l); };
  const crs = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const z = nrm(sub(e, c)), x = nrm(crs(u, z)), y = crs(z, x);
  return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
                           -dot(x, e), -dot(y, e), -dot(z, e), 1]);
}
function persp(fov, asp, n, f) {
  const t = 1 / Math.tan(fov / 2);
  return new Float32Array([t / asp, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1, 0, 0, 2 * f * n / (n - f), 0]);
}
const bytes = b => Uint8Array.from(atob(b), c => c.charCodeAt(0));
const f32 = b => new Float32Array(bytes(b).buffer);

export default function(component) {
  const { data, parentElement } = component;
  let root = parentElement.querySelector('.visor3d');
  if (!root) {
    root = document.createElement('div');
    root.className = 'visor3d';
    root.style.fontFamily = 'sans-serif';
    root.style.fontSize = '13px';
    parentElement.appendChild(root);
  }
  const S = root.__s || (root.__s = { yaw: -35, pitch: 22, zoom: 1, explode: 0, cut: 'cap',
                                      at: 1, modes: {} });
  if (root.__stop) root.__stop();
  root.innerHTML = '';
  const canvas = document.createElement('canvas');
  canvas.style.width = '100%';
  canvas.style.height = data.height + 'px';
  canvas.style.border = '1px solid #ccc';
  canvas.style.borderRadius = '6px';
  canvas.style.background = '#f7f7f5';
  canvas.style.touchAction = 'none';
  canvas.style.cursor = 'grab';
  root.appendChild(canvas);
  const gl = canvas.getContext('webgl', { antialias: true, premultipliedAlpha: false });
  if (!gl) { root.append('El navegador no admet WebGL.'); return; }

  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw gl.getShaderInfoLog(s); return s; };
  const prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(prog);
  gl.useProgram(prog);
  const U = n => gl.getUniformLocation(prog, n);
  const buf = arr => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW); return b; };
  const attr = (name, b, size, type, norm) => { const l = gl.getAttribLocation(prog, name); if (l < 0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, size, type, norm, 0, 0); };
  const tri = { pos: buf(f32(data.pos)), nrm: buf(f32(data.nrm)), off: buf(f32(data.off)),
                col: buf(bytes(data.col)), n: f32(data.pos).length / 3 };
  const lk = bytes(data.lkind), lcol = new Uint8Array(lk.length * 4);
  lk.forEach((k, i) => { lcol[4 * i + 3] = k; });
  const lin = { pos: buf(f32(data.lpos)), off: buf(f32(data.loff)), col: buf(lcol),
                nrm: buf(new Float32Array(lk.length * 3)), n: lk.length };

  const C = data.center, R = data.radius || 1;
  const draw = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight, dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0.97, 0.97, 0.96, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const y = S.yaw * Math.PI / 180, p = S.pitch * Math.PI / 180;
    const dir = [Math.cos(p) * Math.sin(y), -Math.cos(p) * Math.cos(y), Math.sin(p)];
    const reach = R * (1 + 1.5 * S.explode);
    const dist = reach * 3.2 / S.zoom;
    const eye = [C[0] + dir[0] * dist, C[1] + dir[1] * dist, C[2] + dir[2] * dist];
    const mvp = m4mul(persp(0.62, w / Math.max(h, 1), dist * 0.05, dist + reach * 4), lookAt(eye, C, [0, 0, 1]));
    gl.uniformMatrix4fv(U('uMVP'), false, mvp);
    const side = [Math.cos(y), Math.sin(y), 0];
    const L = [dir[0] * 0.75 + side[0] * -0.35, dir[1] * 0.75 + side[1] * -0.35, dir[2] * 0.75 + 0.45];
    const ll = Math.hypot(...L); gl.uniform3f(U('uLight'), L[0] / ll, L[1] / ll, L[2] / ll);
    gl.uniform1f(U('uExplode'), S.explode * R);
    const alpha = data.kinds.map(k => ({ sòlid: 1, transparent: 0.22, amagat: 0 })[S.modes[k] || 'sòlid']);
    while (alpha.length < 8) alpha.push(1);
    gl.uniform1fv(U('uAlpha[0]'), new Float32Array(alpha));
    // Pla de tall perpendicular a l'eix triat: es treu la banda que mira a la càmera, fins
    // a `at` (1 = res, 0 = la meitat, −1 = tot), i es veu l'interior.
    const ax = { x: 0, y: 1, z: 2 }[S.cut];
    if (ax === undefined) gl.uniform4f(U('uClip'), 0, 0, 0, 1);
    else {
      const sg = dir[ax] >= 0 ? 1 : -1, n = [0, 0, 0]; n[ax] = sg;
      const mid = (data.lo[ax] + data.hi[ax]) / 2, half = (data.hi[ax] - data.lo[ax]) / 2 + 1e-6;
      gl.uniform4f(U('uClip'), n[0], n[1], n[2], sg * mid + half * S.at);
    }
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    const run = (o, mode, pass) => {
      attr('aPos', o.pos, 3, gl.FLOAT, false); attr('aNrm', o.nrm, 3, gl.FLOAT, false);
      attr('aOff', o.off, 3, gl.FLOAT, false); attr('aCol', o.col, 4, gl.UNSIGNED_BYTE, true);
      gl.uniform1f(U('uPass'), pass); gl.drawArrays(mode, 0, o.n);
    };
    gl.depthMask(true);
    gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(1, 1);
    gl.uniform1f(U('uLine'), 0); run(tri, gl.TRIANGLES, 0);
    gl.disable(gl.POLYGON_OFFSET_FILL);
    gl.uniform1f(U('uLine'), 1); run(lin, gl.LINES, 0);
    gl.depthMask(false);
    gl.uniform1f(U('uLine'), 0); run(tri, gl.TRIANGLES, 1);
    gl.uniform1f(U('uLine'), 1); run(lin, gl.LINES, 1);
    gl.depthMask(true);
  };
  let queued = false;
  const redraw = () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; draw(); }); } };

  // Gir (un dit / ratolí), zoom (roda / pessic), doble clic = vista inicial.
  const ptrs = new Map(); let pinch = 0;
  canvas.onpointerdown = e => { ptrs.set(e.pointerId, [e.clientX, e.clientY]); canvas.setPointerCapture(e.pointerId); canvas.style.cursor = 'grabbing'; };
  canvas.onpointermove = e => {
    if (!ptrs.has(e.pointerId)) return;
    const [x0, y0] = ptrs.get(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]);
    if (ptrs.size === 1) {
      S.yaw -= (e.clientX - x0) * 0.5;
      S.pitch = Math.max(-89, Math.min(89, S.pitch + (e.clientY - y0) * 0.5));
    } else if (ptrs.size === 2) {
      const [a, b] = [...ptrs.values()]; const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (pinch) S.zoom = Math.max(0.3, Math.min(8, S.zoom * d / pinch)); pinch = d;
    }
    redraw();
  };
  const up = e => { ptrs.delete(e.pointerId); pinch = 0; canvas.style.cursor = 'grab'; };
  canvas.onpointerup = up; canvas.onpointercancel = up;
  canvas.onwheel = e => { e.preventDefault(); S.zoom = Math.max(0.3, Math.min(8, S.zoom * Math.exp(-e.deltaY * 0.0015))); redraw(); };
  canvas.ondblclick = () => { S.yaw = -35; S.pitch = 22; S.zoom = 1; redraw(); };

  const bar = document.createElement('div');
  bar.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin-top:6px';
  const label = t => { const s = document.createElement('span'); s.textContent = t; return s; };
  const range = (min, max, step, val, fn) => { const r = document.createElement('input');
    Object.assign(r, { type: 'range', min, max, step, value: val }); r.style.width = '110px';
    r.oninput = () => { fn(+r.value); redraw(); }; return r; };
  const group = (...els) => { const g = document.createElement('span');
    g.style.cssText = 'display:inline-flex;gap:6px;align-items:center'; g.append(...els); return g; };
  if (data.explode !== false) bar.append(group(label('Separa'), range(0, 1, 0.01, S.explode, v => { S.explode = v; })));
  else S.explode = 0;
  const sel = document.createElement('select');
  for (const [v, t] of [['cap', 'sense tall'], ['x', 'tall x'], ['y', 'tall y'], ['z', 'tall z']]) {
    const o = document.createElement('option'); o.value = v; o.textContent = t; sel.append(o);
  }
  sel.value = S.cut;
  const at = range(-1, 1, 0.01, S.at >= 1 ? 0 : S.at, v => { S.at = v; });
  sel.onchange = () => { S.cut = sel.value; S.at = S.cut === 'cap' ? 1 : +at.value; at.disabled = S.cut === 'cap'; redraw(); };
  at.disabled = S.cut === 'cap';
  bar.append(group(sel, at));
  const ICON = { sòlid: '●', transparent: '◌', amagat: '○' };
  for (const k of data.kinds) {
    const b = document.createElement('button');
    const show = () => { const m = S.modes[k] || 'sòlid'; b.textContent = `${ICON[m]} ${k}`; b.title = m; b.style.opacity = m === 'amagat' ? 0.5 : 1; };
    b.onclick = () => { const order = ['sòlid', 'transparent', 'amagat'];
      S.modes[k] = order[(order.indexOf(S.modes[k] || 'sòlid') + 1) % 3]; show(); redraw(); };
    b.style.cssText = 'border:1px solid #bbb;border-radius:12px;background:white;padding:2px 10px;cursor:pointer';
    show(); bar.append(b);
  }
  const hint = label('arrossega per girar · roda o pessic per ampliar · doble clic: vista inicial');
  hint.style.color = '#777'; hint.style.fontSize = '12px';
  bar.append(hint);
  root.append(bar);
  const ro = new ResizeObserver(redraw); ro.observe(canvas);
  root.__stop = () => ro.disconnect();
  draw();
}
"""

_component = None


def show(solids: list[Solid], key: str, height: int = 460, data: dict | None = None) -> None:
    """Mostra el visor. `data` (de `pack`) evita tornar a empaquetar si ja es té."""
    global _component
    import streamlit as st
    if _component is None:
        _component = st.components.v2.component("desplegables_visor", js=_JS)
    data = dict(data or pack(solids), height=height)
    _component(data=data, key=key)
