"""Tècniques de `parts`: cada una fabrica una `Part` com a peces planes (`operacions.Peca`).

El registre `TECNIQUES` associa el `tecnica` d'una Part amb la funció que la fabrica. Cada funció
rep la Part i retorna les peces; combina les operacions base d'`operacions` i no sap res de la
resta del pla. Les mides són a `part.params` (les posa l'etiqueta, vegeu `etiquetes`).
"""
from __future__ import annotations

from collections.abc import Callable

from shapely.geometry import Polygon
from shapely.ops import unary_union

import operacions as op
from parts import Part


def caixa_5_cares(part: Part) -> list[op.Peca]:
    """Caixa oberta per davant (finestra enfonsada): fons + 4 parets en creu.

    Params: amplada, alcada, profunditat (mm); solapa: alçada de les solapes d'unió entre parets
    (les de les parets laterals, que s'enganxen a la de dalt i a la de baix); brida: si és >0,
    solapa de mur a la vora oberta de cada paret (amb què s'enganxa a darrere la paret).
    """
    w, h, p = (float(part.params[k]) for k in ("amplada", "alcada", "profunditat"))
    s, brida = float(part.params.get("solapa", 6.0)), float(part.params.get("brida", 0.0))
    if min(w, h, p) <= 0:
        raise ValueError("Amplada, alçada i profunditat han de ser positives.")
    fons = Polygon([(0, 0), (w, 0), (w, h), (0, h)])
    esq = Polygon([(-p, 0), (0, 0), (0, h), (-p, h)])
    dre = Polygon([(w, 0), (w + p, 0), (w + p, h), (w, h)])
    dalt = Polygon([(0, h), (w, h), (w, h + p), (0, h + p)])
    baix = Polygon([(0, -p), (w, -p), (w, 0), (0, 0)])
    base = op.Peca(part.nom, unary_union([fons, esq, dre, dalt, baix]))
    unions = [((-p, h), (0, h)), ((-p, 0), (0, 0)), ((w, h), (w + p, h)), ((w, 0), (w + p, 0))]
    peca = op.afegeix_solapes(base, unions, s)
    if brida > 0:
        oberta = [((-p, 0), (-p, h)), ((w + p, 0), (w + p, h)), ((0, h + p), (w, h + p)), ((0, -p), (w, -p))]
        peca = op.afegeix_solapes(peca, oberta, brida)
    for a, b in [((0, 0), (w, 0)), ((w, 0), (w, h)), ((w, h), (0, h)), ((0, h), (0, 0))]:
        peca = op.plega(peca, a, b)
    peca.notes += ["Plega les 4 parets cap amunt pel perímetre del fons.",
                   "Enganxa cada solapa a la paret veïna per dins.",
                   *(["Les solapes de la vora oberta s'enganxen a darrere de la paret."] if brida > 0 else [])]
    return [peca]


TECNIQUES: dict[str, Callable[[Part], list[op.Peca]]] = {
    "caixa_5_cares": caixa_5_cares,
}


def fabrica(part: Part) -> list[op.Peca]:
    try:
        f = TECNIQUES[part.tecnica]
    except KeyError:
        raise ValueError(f"Cap tècnica «{part.tecnica}» (hi ha {', '.join(TECNIQUES)}).") from None
    return f(part)
