"""Decoració de les cares: textures del model, imatges, patrons i dibuixos, amb o sense marc.

Una "cara" és una zona plana del model (la mateixa numeració que les plaques de làser:
C1, C2…). Cada cara té un sistema de coordenades propi en mm, vist des de fora (x, y amunt).
Una decoració es descriu en aquestes coordenades i després es porta a cada sortida:

- paper: s'imprimeix dins de cada triangle de la cara (retallada al triangle i al marc);
- làser: es grava (imatge o línies) o es talla (forats dins del marc).
"""
from __future__ import annotations

import base64
import io
import math
import os
import tempfile
from dataclasses import dataclass, field

import numpy as np
import shapely
import trimesh
from PIL import Image
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box
from shapely.ops import unary_union

import papercraft as pc

KINDS = ("textura", "imatge", "patró", "dibuix")
PATTERNS = ("ratlles", "quadrícula", "punts", "hexàgons", "color", "text")
LASER_MODES = ("gravar", "tallar", "gravar i tallar")


# ---------------------------------------------------------------- cares i coordenades

@dataclass
class FaceFrame:
    """Una cara (zona plana): triangles, base local i forma en mm."""
    index: int                 # 0, 1, 2… (es mostra com C1, C2…)
    faces: np.ndarray          # triangles de la malla que la formen
    origin: np.ndarray
    u: np.ndarray
    v: np.ndarray
    normal: np.ndarray
    shape: Polygon             # en coordenades locals

    def to_local(self, p3: np.ndarray) -> np.ndarray:
        d = np.atleast_2d(p3) - self.origin
        return np.column_stack([d @ self.u, d @ self.v])


def face_frames(mesh: trimesh.Trimesh) -> list[FaceFrame]:
    """Cares del model en el mateix ordre que les plaques de la branca de cares."""
    em = pc.edge_faces(mesh.faces)
    patch = pc.flat_patches(mesh, em)
    ids = {pid: i for i, pid in enumerate(dict.fromkeys(int(x) for x in patch))}
    plate_of = np.array([ids[int(x)] for x in patch])
    out = []
    V, F = mesh.vertices, mesh.faces
    for k in range(len(ids)):
        fs = np.nonzero(plate_of == k)[0]
        n = (mesh.face_normals[fs] * mesh.area_faces[fs, None]).sum(0)
        n /= np.linalg.norm(n)
        o = V[F[fs[0]][0]]
        # "Amunt" de la cara = l'amunt del model (z) projectat; a les cares horitzontals, y.
        up = np.array([0.0, 0.0, 1.0]) - n[2] * n
        if np.linalg.norm(up) < 0.3:
            up = np.array([0.0, 1.0, 0.0]) - n[1] * n
        v = up / np.linalg.norm(up)
        u = np.cross(v, n)
        fr = FaceFrame(k, fs, o, u, v, n, Polygon())
        fr.shape = unary_union([Polygon(fr.to_local(V[F[f]])) for f in fs]).buffer(0)
        out.append(fr)
    return out


def affine_from(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Matriu 2×3 que porta 3 punts `src` sobre `dst`."""
    A = np.column_stack([src, np.ones(3)])
    return np.linalg.solve(A, dst).T  # [[a, c, e], [b, d, f]]


def apply_affine(M: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.atleast_2d(pts)
    return pts @ M[:, :2].T + M[:, 2]


def svg_matrix(M: np.ndarray) -> str:
    (a, c, e), (b, d, f) = M
    return f"matrix({a:.6f} {b:.6f} {c:.6f} {d:.6f} {e:.4f} {f:.4f})"


# ---------------------------------------------------------------- textures del model

@dataclass
class Texture:
    image: Image.Image
    face_uv: np.ndarray        # (F, 3, 2) coordenades UV de cada cantonada de cada triangle


def load_textured(files: dict[str, bytes]):
    """Carrega un model amb textura (OBJ + MTL + imatge, o GLB). Retorna (malla, Texture o None).

    `files`: nom de fitxer → contingut. La malla retornada no té els vèrtexs fusionats
    (les costures de la textura hi són); `pc.clean` els fusiona després.
    """
    main = next((n for n in files if n.lower().endswith((".obj", ".glb", ".gltf"))), None)
    if main is None:
        main = next(n for n in files if n.lower().endswith(".stl"))
    with tempfile.TemporaryDirectory() as tmp:
        for name, data in files.items():
            with open(os.path.join(tmp, os.path.basename(name)), "wb") as f:
                f.write(data)
        obj = trimesh.load(os.path.join(tmp, os.path.basename(main)), process=False)
        meshes = list(obj.geometry.values()) if isinstance(obj, trimesh.Scene) else [obj]
        meshes = [g for g in meshes if isinstance(g, trimesh.Trimesh)]
        if not meshes:
            raise ValueError("No s'ha trobat cap malla.")
        mesh = meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)
        tex = None
        vis = getattr(mesh, "visual", None)
        uv = getattr(vis, "uv", None)
        mat = getattr(vis, "material", None)
        img = getattr(mat, "image", None) or getattr(mat, "baseColorTexture", None)
        if uv is not None and img is not None and len(uv) == len(mesh.vertices):
            tex = Texture(img.convert("RGB"), np.asarray(uv)[mesh.faces].astype(float))
        mesh = trimesh.Trimesh(mesh.vertices.copy(), mesh.faces.copy(), process=False)
    return mesh, tex


def transfer_uv(src: trimesh.Trimesh, src_uv: np.ndarray, dst: trimesh.Trimesh) -> np.ndarray:
    """UV per als triangles de `dst` (simplificada) a partir de la malla original `src`.

    Cada triangle nou pren el triangle original més proper al seu centre i hi projecta les
    seves cantonades (estenent-ne la correspondència UV): així un triangle no barreja mai
    dues illes de la textura.
    """
    tri = src.triangles
    cen = src.triangles_center
    out = np.zeros((len(dst.faces), 3, 2))
    k = min(24, len(tri))
    for i, c in enumerate(dst.triangles_center):
        near = np.argpartition(np.linalg.norm(cen - c, axis=1), k - 1)[:k]
        cp = trimesh.triangles.closest_point(tri[near], np.repeat(c[None], len(near), 0))
        j = near[int(np.argmin(np.linalg.norm(cp - c, axis=1)))]
        a, b, cc = tri[j]
        e1, e2 = b - a, cc - a
        G = np.array([[e1 @ e1, e1 @ e2], [e1 @ e2, e2 @ e2]])
        for corner in range(3):
            p = dst.vertices[dst.faces[i][corner]] - a
            s, t = np.linalg.solve(G, [p @ e1, p @ e2])
            out[i, corner] = src_uv[j, 0] + s * (src_uv[j, 1] - src_uv[j, 0]) + \
                t * (src_uv[j, 2] - src_uv[j, 0])
    return out


def prepare(mesh: trimesh.Trimesh, target_faces: int, size_mm: float,
            texture: Texture | None = None):
    """Simplifica i escala com fan les branques; si hi ha textura, la porta a la malla nova."""
    cleaned = pc.clean(mesh)
    m = pc.scale_to(pc.simplify(cleaned, target_faces), size_mm)
    if texture is None:
        return m, None
    src = mesh.copy()
    src.apply_scale(size_mm / float(max(cleaned.extents)))
    return m, Texture(texture.image, transfer_uv(src, texture.face_uv, m))


# ---------------------------------------------------------------- decoracions

@dataclass
class DecorSpec:
    kind: str = "patró"                  # textura | imatge | patró | dibuix
    frame: float = 0.0                   # mm de marc (0 = sense)
    laser: str = "gravar"                # gravar | tallar | gravar i tallar
    image: bytes | None = None           # imatge (PNG/JPG) per a "imatge"
    fit: str = "omplir"                  # omplir (retalla) | encabir (sencera)
    pattern: str = "ratlles"
    spacing: float = 6.0                 # mm entre línies/punts/cel·les
    width: float = 1.5                   # mm de gruix de línia (i de pont en tallar)
    angle: float = 45.0                  # graus
    color: str = "#1f4e79"
    text: str = ""
    strokes: list = field(default_factory=list)   # dibuix: polilínies en mm locals
    threshold: int = 128                 # tallar imatges: més fosc que això és forat


@dataclass
class Source:
    """Una decoració a punt en coordenades locals d'una cara."""
    clip: Polygon                                   # on es pot dibuixar (cara menys marc)
    svg: str = ""                                   # fragment SVG (vectors) en mm locals
    images: list = field(default_factory=list)      # (clau, png, ample, alt, matriu px→local)
    engrave: list = field(default_factory=list)     # polilínies per gravar (làser)
    holes: object = None                            # polígons per tallar (làser)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _image_fit(img: Image.Image, clip: Polygon, fit: str) -> np.ndarray:
    """Matriu píxel → local que encaixa la imatge a la capsa de la cara."""
    x0, y0, x1, y1 = clip.bounds
    w, h = img.size
    sx, sy = (x1 - x0) / w, (y1 - y0) / h
    s = max(sx, sy) if fit == "omplir" else min(sx, sy)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    # Els píxels van amb y cap avall; les coordenades locals, amb y amunt.
    return np.array([[s, 0, cx - s * w / 2], [0, -s, cy + s * h / 2]])


def _lines_in(clip: Polygon, spacing: float, angle: float) -> list[LineString]:
    c = np.array(clip.centroid.coords[0])
    R = max(clip.bounds[2] - clip.bounds[0], clip.bounds[3] - clip.bounds[1])
    a = math.radians(angle)
    d, n = np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])
    out = []
    for i in range(-int(R / spacing) - 1, int(R / spacing) + 2):
        p = c + n * i * spacing
        out.append(LineString([p - d * R, p + d * R]))
    return out


def _hexagons(clip: Polygon, spacing: float, inner: float) -> list[Polygon]:
    x0, y0, x1, y1 = clip.bounds
    r = spacing / math.sqrt(3)
    out = []
    for j, y in enumerate(np.arange(y0 - spacing, y1 + spacing, spacing * math.sqrt(3) / 2)):
        off = (spacing / 2) if j % 2 else 0
        for x in np.arange(x0 - spacing + off, x1 + spacing, spacing):
            out.append(Polygon([(x + inner * math.cos(math.radians(30 + 60 * k)),
                                 y + inner * math.sin(math.radians(30 + 60 * k))) for k in range(6)]))
    return out


def _poly_svg(geom, fill: str) -> str:
    parts = []
    for g in getattr(geom, "geoms", [geom]):
        if g.geom_type != "Polygon" or g.is_empty:
            continue
        rings = [g.exterior, *g.interiors]
        d = " ".join("M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in np.array(r.coords)[:-1]) + " Z"
                     for r in rings)
        parts.append(f'<path d="{d}" fill="{fill}" fill-rule="evenodd" stroke="none"/>')
    return "".join(parts)


def _lines_svg(lines, color: str, width: float) -> str:
    out = []
    for g in lines:
        for ln in getattr(g, "geoms", [g]):
            if ln.geom_type in ("LineString", "LinearRing") and ln.length > 0:
                pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in ln.coords)
                out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                           f'stroke-width="{width:.3f}" stroke-linecap="round"/>')
    return "".join(out)


def _dark_regions(img: Image.Image, M: np.ndarray, threshold: int):
    """Zones més fosques que el llindar, com a polígons en coordenades locals."""
    g = img.convert("L")
    scale = 200 / max(g.size)
    if scale < 1:
        g = g.resize((max(1, int(g.size[0] * scale)), max(1, int(g.size[1] * scale))))
        M = M @ np.array([[1 / scale, 0, 0], [0, 1 / scale, 0], [0, 0, 1]])
    a = np.asarray(g) < threshold
    rects = []
    for yy, row in enumerate(a):
        x = 0
        while x < len(row):
            if row[x]:
                x0 = x
                while x < len(row) and row[x]:
                    x += 1
                rects.append(box(x0, yy, x, yy + 1))
            else:
                x += 1
    if not rects:
        return Polygon()
    px = unary_union(rects).simplify(0.6)
    return shapely.transform(px, lambda p: apply_affine(M, p))


def build_source(frame: FaceFrame, spec: DecorSpec) -> Source:
    """Fragment SVG, imatges i geometria (per al làser) d'una decoració en una cara."""
    clip = frame.shape.buffer(-spec.frame) if spec.frame > 0 else frame.shape
    src = Source(clip)
    if clip.is_empty:
        return src
    holes = []
    if spec.kind == "imatge" and spec.image:
        img = Image.open(io.BytesIO(spec.image)).convert("RGB")
        M = _image_fit(img, clip, spec.fit)
        key = f"img{abs(hash(spec.image)) % 10 ** 10}"
        src.images.append((key, _png(img), img.size[0], img.size[1], M))
        holes.append(_dark_regions(img, M, spec.threshold))
    elif spec.kind == "patró":
        p, s, w = spec.pattern, max(spec.spacing, 0.5), max(spec.width, 0.1)
        if p == "ratlles":
            lines = _lines_in(clip, s, spec.angle)
            src.svg = _lines_svg(lines, spec.color, w)
            src.engrave += lines
            holes += [ln.buffer(w / 2, cap_style=2) for ln in lines]
        elif p == "quadrícula":
            lines = _lines_in(clip, s, spec.angle) + _lines_in(clip, s, spec.angle + 90)
            src.svg = _lines_svg(lines, spec.color, w)
            src.engrave += lines
            # Tallar: els forats són les cel·les, i les línies queden com a ponts.
            holes.append(clip.difference(unary_union([ln.buffer(w / 2, cap_style=2) for ln in lines])))
        elif p == "punts":
            x0, y0, x1, y1 = clip.bounds
            dots = [Point(x, y).buffer(w, 16) for x in np.arange(x0, x1 + s, s)
                    for y in np.arange(y0, y1 + s, s)]
            src.svg = _poly_svg(unary_union(dots), spec.color)
            src.engrave += [d.exterior for d in dots]
            holes += dots
        elif p == "hexàgons":
            cells = _hexagons(clip, s, s / math.sqrt(3) - w / 2)
            src.svg = "".join(_lines_svg([c.exterior], spec.color, w * 0.6) for c in cells)
            src.engrave += [c.exterior for c in cells]
            holes += cells
        elif p == "color":
            src.svg = _poly_svg(clip, spec.color)
        elif p == "text" and spec.text:
            x0, y0, x1, y1 = clip.bounds
            size = min((x1 - x0) / max(1, 0.6 * len(spec.text)), (y1 - y0) * 0.6)
            cx, cy = clip.centroid.coords[0]
            # El text va en un grup amb y invertida perquè es llegeixi bé (local: y amunt).
            src.svg = (f'<g transform="translate({cx:.3f} {cy:.3f}) scale(1 -1)">'
                       f'<text x="0" y="0" font-family="sans-serif" font-size="{size:.2f}" '
                       f'fill="{spec.color}" text-anchor="middle" dominant-baseline="central">'
                       f'{_escape(spec.text)}</text></g>')
    elif spec.kind == "dibuix" and spec.strokes:
        lines = [LineString(s) for s in spec.strokes if len(s) >= 2]
        src.svg = _lines_svg(lines, spec.color, spec.width)
        src.engrave += lines
        holes += [ln.buffer(spec.width / 2) for ln in lines]
    if holes:
        src.holes = unary_union([h for h in holes if not h.is_empty]).intersection(clip)
    return src


def _escape(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def texture_ops(frame: FaceFrame, mesh: trimesh.Trimesh, tex: Texture, spec: DecorSpec):
    """Per a cada triangle de la cara: (triangle, matriu píxel → local) per pintar-hi la textura."""
    w, h = tex.image.size
    out = []
    for f in frame.faces:
        local = frame.to_local(mesh.vertices[mesh.faces[f]])
        px = np.column_stack([tex.face_uv[f][:, 0] * w, (1 - tex.face_uv[f][:, 1]) * h])
        e1, e2 = px[1] - px[0], px[2] - px[0]
        if abs(e1[0] * e2[1] - e1[1] * e2[0]) < 1e-9:
            continue
        out.append((int(f), affine_from(px, local)))
    return out


def image_href(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


# ---------------------------------------------------------------- operacions a les peces

@dataclass
class DecorOp:
    """Decoració portada a una peça: contingut en coordenades `src`, matriu src → peça i retall."""
    content: str               # fragment SVG en coordenades src (pot fer servir <use href="#clau">)
    matrix: np.ndarray         # 2×3, src → peça
    clip: Polygon              # en coordenades de la peça

    def transform(self, fn) -> None:
        basis = apply_affine(self.matrix, np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]))
        moved = fn(basis)
        self.matrix = affine_from(np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]), moved)
        self.clip = shapely.transform(self.clip, fn)


def ops_svg(ops: list[DecorOp], prefix: str) -> str:
    out = []
    for i, op in enumerate(ops):
        if op.clip.is_empty:
            continue
        cid = f"{prefix}c{i}"
        d = " ".join("M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in np.array(r.coords)[:-1]) + " Z"
                     for g in getattr(op.clip, "geoms", [op.clip]) if g.geom_type == "Polygon"
                     for r in [g.exterior, *g.interiors])
        out.append(f'<clipPath id="{cid}"><path d="{d}" clip-rule="evenodd"/></clipPath>'
                   f'<g clip-path="url(#{cid})"><g transform="{svg_matrix(op.matrix)}">'
                   f'{op.content}</g></g>')
    return "".join(out)


def image_defs(images: dict[str, tuple[bytes, int, int]]) -> str:
    return "".join(f'<image id="{k}" width="{w}" height="{h}" href="{image_href(png)}"/>'
                   for k, (png, w, h) in images.items())


def source_content(src: Source) -> str:
    """Contingut SVG d'una font (imatges per referència + vectors), en coordenades locals."""
    parts = [f'<use href="#{k}" transform="{svg_matrix(M)}"/>' for k, _, _, _, M in src.images]
    return "".join(parts) + src.svg


# ---------------------------------------------------------------- làser

def engrave_content(src: Source, spec: DecorSpec, color: str = "#0000ff") -> str:
    """Contingut per gravar: imatges (ràster), text, línies i zones de color, tot en blau."""
    parts = [f'<use href="#{k}" transform="{svg_matrix(M)}"/>' for k, _, _, _, M in src.images]
    if spec.kind == "patró" and spec.pattern == "color":
        parts.append(_poly_svg(src.clip, color))
    elif spec.kind == "patró" and spec.pattern == "text":
        parts.append(src.svg.replace(f'fill="{spec.color}"', f'fill="{color}"'))
    elif spec.kind == "patró" and spec.pattern == "punts":
        parts.append(_poly_svg(src.holes, color) if src.holes is not None else "")
    else:
        parts.append(_lines_svg(src.engrave, color, max(spec.width, 0.2)))
    return "".join(parts)


CUT_MIN_FRAME = 3.0  # mm: en tallar, sempre queda un marc perquè la placa no es desfaci
