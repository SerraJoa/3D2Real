"""Pintura de les cares: compon les capes del disseny (pell UV, grup, cara) en una imatge per cara.

Les capes es dibuixen en aquest ordre — pell, grup, cara — i dins de cada nivell per ordre de
creació. El resultat és una imatge per cara que les branques ja saben posar (paper) o gravar i
tallar (làser: es passa a gris, el negre és tall i la resta, potència).
"""
import io

import numpy as np
from PIL import Image, ImageColor, ImageDraw

import decor as dc

NIVELLS = ("uv", "grup", "cara")
PX_MM = 8          # píxels per mm
MAX_PX = 1400      # costat màxim d'una imatge


def _clip(frame, marc: float):
    return frame.shape.buffer(-marc) if marc > 0 else frame.shape


def _mascara(clip, P, W: int, H: int) -> Image.Image:
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    for g in getattr(clip, "geoms", [clip]):
        if g.geom_type != "Polygon":
            continue
        d.polygon([tuple(p) for p in P(np.array(g.exterior.coords))], fill=255)
        for r in g.interiors:
            d.polygon([tuple(p) for p in P(np.array(r.coords))], fill=0)
    return m


def _pell(frame, mesh, tex, P, W: int, H: int) -> Image.Image:
    """Textura del model sobre els triangles de la cara (mostreig per baricèntriques)."""
    out = np.zeros((H, W, 4), np.uint8)
    arr = np.asarray(tex.image.convert("RGB"))
    th, tw = arr.shape[:2]
    for f in frame.faces:
        p = P(frame.to_local(mesh.vertices[mesh.faces[f]]))
        x0, y0 = np.floor(p.min(0)).astype(int).clip(0, [W - 1, H - 1])
        x1, y1 = np.ceil(p.max(0)).astype(int).clip(0, [W - 1, H - 1])
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        a, b, c = p
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-9:
            continue
        l1 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / d
        l2 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / d
        l3 = 1 - l1 - l2
        dins = (l1 >= -0.02) & (l2 >= -0.02) & (l3 >= -0.02)
        uv = tex.face_uv[f]
        u = l1 * uv[0, 0] + l2 * uv[1, 0] + l3 * uv[2, 0]
        v = l1 * uv[0, 1] + l2 * uv[1, 1] + l3 * uv[2, 1]
        ix = np.clip((u * tw).astype(int), 0, tw - 1)
        iy = np.clip(((1 - v) * th).astype(int), 0, th - 1)
        zone = out[y0:y1 + 1, x0:x1 + 1]
        zone[dins, :3] = arr[iy, ix][dins]
        zone[dins, 3] = 255
    return Image.fromarray(out, "RGBA")


def _imatge(raw: bytes, fit: str, W: int, H: int) -> Image.Image:
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    s = (max if fit == "omplir" else min)(W / img.width, H / img.height)
    img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
    return out


def _composa(frame, mesh, tex, ops: list[dict], marc: float):
    """(imatge RGB, funció local → píxel) d'una cara amb les capes en l'ordre pell → grup → cara."""
    clip = _clip(frame, marc)
    if clip.is_empty or not ops:
        return None
    x0, y0, x1, y1 = clip.bounds
    res = min(PX_MM, MAX_PX / max(x1 - x0, y1 - y0, 1e-6))
    W, H = max(4, round((x1 - x0) * res)), max(4, round((y1 - y0) * res))
    P = lambda q: np.column_stack([(q[:, 0] - x0) * res, (y1 - q[:, 1]) * res])
    mask = _mascara(clip, P, W, H)
    canvas = Image.new("RGB", (W, H), "white")
    for op in sorted(ops, key=lambda o: NIVELLS.index(o["nivell"])):
        if op["tipus"] == "uv":
            if tex is None:
                continue
            lay = _pell(frame, mesh, tex, P, W, H)
        elif op["tipus"] == "imatge":
            lay = _imatge(op["imatge"], op["ajust"], W, H)
        elif op["tipus"] == "color":
            lay = Image.new("RGBA", (W, H), ImageColor.getrgb(op["color"]) + (255,))
        elif op["tipus"] == "dibuix":
            lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            for s in op["traços"]:
                if len(s) >= 2:
                    d.line([tuple(p) for p in P(np.array(s, float))],
                           fill=ImageColor.getrgb(op["color"]) + (255,), width=max(1, round(res)))
        else:
            continue
        alpha = np.minimum(np.asarray(lay.getchannel("A")), np.asarray(mask))
        canvas.paste(lay.convert("RGB"), mask=Image.fromarray(alpha))
    return canvas, P


def cara(frame, mesh, tex, ops: list[dict], marc: float) -> bytes | None:
    """Imatge PNG d'una cara amb les seves capes, o None si no n'hi ha."""
    res = _composa(frame, mesh, tex, ops, marc)
    if res is None:
        return None
    buf = io.BytesIO()
    res[0].save(buf, "PNG")
    return buf.getvalue()


def colors(frames, mesh, tex, ops: list[dict], base=(220, 194, 154)) -> np.ndarray:
    """Color (F, 3) de cada triangle de la malla amb totes les capes: per al render texturitzat."""
    out = np.tile(np.array(base, np.uint8), (len(mesh.faces), 1))
    for fr in frames:
        res = _composa(fr, mesh, tex, [o for o in ops if fr.index in o["cares"]], 0.0)
        if res is None:
            continue
        img, P = res
        arr = np.asarray(img)
        for f in fr.faces:
            c = P(fr.to_local(mesh.vertices[mesh.faces[f]]).mean(0, keepdims=True))[0]
            x, y = int(np.clip(c[0], 0, arr.shape[1] - 1)), int(np.clip(c[1], 0, arr.shape[0] - 1))
            out[f] = arr[y, x]
    return out


def decoracio(frames, mesh, tex, ops: list[dict], marc: float, laser: bool, llindar: int) -> dict:
    """{índex de cara: DecorSpec} amb una imatge per cara. Al làser, grava en gris i talla el
    negre, i el marc mínim és el que es deixa en tallar."""
    out = {}
    m = max(marc, dc.CUT_MIN_FRAME) if laser else marc
    for fr in frames:
        mine = [o for o in ops if fr.index in o["cares"]]
        png = cara(fr, mesh, tex, mine, m)
        if png is None:
            continue
        spec = dc.DecorSpec(kind="imatge", frame=m, fit="omplir", image=png, threshold=llindar)
        if laser:
            spec.laser = "gravar i tallar"
        out[fr.index] = spec
    return out
