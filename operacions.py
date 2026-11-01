"""Operacions base de les tècniques de `parts`: retallar, plegar i posar solapes en una peça plana.

Les tècniques (caixa de 5 cares, finestra amb frontissa...) combinen aquestes operacions; aquí no
hi ha cap forma concreta. Una `Peca` és el contorn a tallar, els plecs (línies amb vall o muntanya)
i els talls interiors, tot en mm sobre el pla de la planxa.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

VALL, MUNTANYA = "vall", "muntanya"
TOL = 1e-6


@dataclass
class Peca:
    nom: str
    contorn: Polygon
    plecs: list[tuple[tuple[float, float], tuple[float, float], str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def rectangle(nom: str, w: float, h: float) -> Peca:
    return Peca(nom, Polygon([(0, 0), (w, 0), (w, h), (0, h)]))


def _fora(contorn: Polygon, a, b) -> np.ndarray:
    """Normal unitària de l'aresta a→b cap a fora del contorn."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    n = np.array([d[1], -d[0]]) / np.linalg.norm(d)
    mig = (a + b) / 2
    if contorn.contains(Point(mig + n * 1e-3)):
        n = -n
    return n


def solapa(contorn: Polygon, a, b, h: float, angle: float = 45.0) -> Polygon:
    """Trapezi enganxable a l'aresta a→b, cap a fora, d'alçada `h` i amb els costats inclinats `angle`°.
    S'estreny per cada banda fins a un màxim de la meitat de l'aresta."""
    if h <= 0:
        raise ValueError("L'alçada de la solapa ha de ser positiva.")
    if not contorn.boundary.buffer(TOL).contains(LineString([a, b])):
        raise ValueError("L'aresta de la solapa no és a la vora del contorn.")
    a, b = np.asarray(a, float), np.asarray(b, float)
    llarg = float(np.linalg.norm(b - a))
    u = (b - a) / llarg
    n = _fora(contorn, a, b)
    retir = min(h / math.tan(math.radians(angle)), llarg / 2 - TOL)
    return Polygon([a, a + n * h + u * retir, b + n * h - u * retir, b])


def afegeix_solapes(p: Peca, arestes: list[tuple], h: float, angle: float = 45.0) -> Peca:
    """Peça nova amb una solapa a cada aresta donada (parells de punts del contorn)."""
    unio = unary_union([p.contorn, *(solapa(p.contorn, a, b, h, angle) for a, b in arestes)])
    if not isinstance(unio, Polygon):
        raise ValueError("Les solapes han de quedar enganxades al contorn en una sola peça.")
    return Peca(p.nom, unio.simplify(0), list(p.plecs), p.notes + [f"{len(arestes)} solapes d'enganxar"])


def retalla(p: Peca, forma: Polygon) -> Peca:
    """Treu `forma` de la peça: un forat si cau a dins, una osca si toca la vora.
    Si la parteix en dues o la buida, és un error."""
    nou = p.contorn.difference(forma)
    if nou.is_empty or not isinstance(nou, Polygon):
        raise ValueError("El retall parteix la peça o la deixa buida.")
    return Peca(p.nom, nou, list(p.plecs), list(p.notes))


def plega(p: Peca, a, b, tipus: str = VALL) -> Peca:
    """Afegeix un plec de a a b, que ha de ser dins la peça."""
    if tipus not in (VALL, MUNTANYA):
        raise ValueError(f"Tipus de plec «{tipus}» desconegut (cal {VALL} o {MUNTANYA}).")
    if not p.contorn.buffer(TOL).contains(LineString([a, b])):
        raise ValueError("El plec surt de la peça.")
    return Peca(p.nom, p.contorn, [*p.plecs, (tuple(a), tuple(b), tipus)], list(p.notes))


def trasllada(p: Peca, dx: float, dy: float) -> Peca:
    return Peca(p.nom, translate(p.contorn, dx, dy),
                [((a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy), t) for a, b, t in p.plecs],
                list(p.notes))
