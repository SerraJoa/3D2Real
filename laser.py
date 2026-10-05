"""Peces planes per a tall làser i planxes SVG, comunes a les branques de cares i laminació.

Convenció de colors: vermell = tallar, blau = gravar. Les coordenades de cada peça són
amb l'eix y cap amunt, vistes des de la cara que queda amunt a la màquina.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Polygon

import papercraft as pc

SHEETS = {"600×400": (600.0, 400.0), "800×500": (800.0, 500.0), "300×200": (300.0, 200.0),
          "A4": pc.PAGES["A4"], "A3": pc.PAGES["A3"]}
SHEET_MARGIN = 5.0  # mm
PART_GAP = 2.0      # mm entre peces a la planxa
LASER_TURNS = 8     # girs repartits que es proven (n'hi ha moltes més peces que al paper)

CUT = "#ff0000"
ENGRAVE = "#0000ff"
GUIDE = "#00a000"   # només de referència: no es talla ni es grava


@dataclass
class Part:
    """Peça plana: forma a tallar (amb forats) i marques a gravar."""
    name: str
    shape: Polygon | MultiPolygon
    engraves: list[np.ndarray] = field(default_factory=list)          # polilínies
    labels: list[tuple[np.ndarray, str, float]] = field(default_factory=list)
    decor: list = field(default_factory=list)                         # decor.DecorOp (gravat)
    guides: list[np.ndarray] = field(default_factory=list)            # referència (verd)
    guide_labels: list[tuple[np.ndarray, str, float]] = field(default_factory=list)

    def outline(self):
        return self.shape

    def points(self) -> np.ndarray:
        polys = getattr(self.shape, "geoms", [self.shape])
        return np.vstack([np.array(g.exterior.coords) for g in polys])

    def transform(self, fn) -> None:
        self.shape = shapely.transform(self.shape, fn)
        self.engraves = [fn(e) for e in self.engraves]
        self.labels = [(fn(np.asarray(p, float)[None])[0], t, z) for p, t, z in self.labels]
        self.guides = [fn(e) for e in self.guides]
        self.guide_labels = [(fn(np.asarray(p, float)[None])[0], t, z) for p, t, z in self.guide_labels]
        for op in self.decor:
            op.transform(fn)

    def to_guides(self) -> None:
        """Les marques de muntatge passen a referència: la peça es talla amb la cara de fora amunt."""
        self.guides += self.engraves
        self.guide_labels += self.labels
        self.engraves, self.labels = [], []


def _path(ring) -> str:
    c = np.array(ring.coords)
    return "M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in c[:-1]) + " Z"


def sheet_svg(parts: list[Part], size: tuple[float, float], number: int, total: int,
              title: str, images: dict | None = None) -> str:
    W, H = size
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
           f'viewBox="0 0 {W} {H}">']
    if images and any(p.decor for p in parts):
        import decor as dc
        out.append(f'<defs>{dc.image_defs(images)}</defs>')
    for pi, p in enumerate(parts):
        out.append(f'<g id="{p.name}">')
        if p.decor:
            import decor as dc
            out.append(dc.ops_svg(p.decor, f"s{number}_{pi}_"))
        for g in getattr(p.shape, "geoms", [p.shape]):
            d = " ".join(_path(r) for r in [g.exterior, *g.interiors])
            out.append(f'<path d="{d}" fill="none" stroke="{CUT}" stroke-width="0.1" '
                       f'fill-rule="evenodd"/>')
        for e in p.engraves:
            pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in e)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{ENGRAVE}" '
                       f'stroke-width="0.2"/>')
        for q, t, z in p.labels:
            out.append(f'<text x="{q[0]:.2f}" y="{q[1]:.2f}" font-family="sans-serif" '
                       f'font-size="{z:.2f}" fill="{ENGRAVE}" text-anchor="middle" '
                       f'dominant-baseline="central">{t}</text>')
        for e in p.guides:
            pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in e)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{GUIDE}" '
                       f'stroke-width="0.15" stroke-dasharray="1,1"/>')
        for q, t, z in p.guide_labels:
            out.append(f'<text x="{q[0]:.2f}" y="{q[1]:.2f}" font-family="sans-serif" '
                       f'font-size="{z:.2f}" fill="{GUIDE}" text-anchor="middle" '
                       f'dominant-baseline="central">{t}</text>')
        out.append('</g>')
    out.append(f'<text x="{SHEET_MARGIN}" y="{H - 1.5}" font-family="sans-serif" font-size="2.5" '
               f'fill="#888">{title} · planxa {number}/{total} · vermell = tallar · '
               f'blau = gravar</text>')
    out.append('</svg>')
    return "\n".join(out)


@dataclass
class LaserResult:
    sheets: list[str]
    parts: list[Part]
    stats: dict
    notes: list[str] = field(default_factory=list)   # llistes (tiges…) per a qui munta
    groups: list[list[Part]] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def zip_bytes(self, prefix: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i, svg in enumerate(self.sheets, 1):
                z.writestr(f"{prefix}_planxa{i:02d}.svg", svg)
            if self.notes:
                z.writestr(f"{prefix}_muntatge.txt", "\n".join(self.notes) + "\n")
        return buf.getvalue()


def nest(parts: list[Part], sheet: tuple[float, float], title: str, images: dict | None = None
         ) -> tuple[list[str], list[list[Part]], int]:
    """Col·loca les peces a planxes amb l'encaix per forma i en fa l'SVG."""
    res = max(pc.NEST_RES, (sheet[0] * sheet[1] / 240000) ** 0.5)  # graella ≤ ~240.000 quadres
    pages, oversize = pc.layout(parts, sheet, margin=SHEET_MARGIN, gap=PART_GAP, res=res,
                                turns=LASER_TURNS)
    svgs = [sheet_svg(pg.pieces, sheet, i, len(pages), title, images)
            for i, pg in enumerate(pages, 1)]
    return svgs, [pg.pieces for pg in pages], oversize
