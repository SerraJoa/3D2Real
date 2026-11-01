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


def sortint(part: Part) -> list[op.Peca]:
    """Volum en relleu sobre el mur: la mateixa creu que la caixa, però el mur no es retalla i la
    vora oberta (brida, per defecte 4 mm) s'enganxa a la cara de davant del mur."""
    params = {"brida": 4.0, **part.params}
    peca, = caixa_5_cares(Part(part.nom, part.tecnica, params=params))
    peca.notes[:] = ["Plega les 4 parets cap amunt pel perímetre del fons (la cara de davant).",
                     "Enganxa cada solapa a la paret veïna per dins.",
                     "Enganxa les brides sobre el mur, pel davant."]
    return [peca]


def retall_frontissa(part: Part) -> list[op.Peca]:
    """Porta o finestra mòbil: la fulla (amplada × alçada) amb una tira de frontissa al costat
    esquerre, amb què s'enganxa al mur al costat de l'obertura. El plec és el de la frontissa.

    Params: amplada, alcada, frontissa (amplada de la tira, mm; 5 per defecte)."""
    w, h = float(part.params["amplada"]), float(part.params["alcada"])
    f = float(part.params.get("frontissa", 5.0))
    if min(w, h, f) <= 0:
        raise ValueError("Amplada, alçada i frontissa han de ser positives.")
    fulla = op.rectangle(part.nom, w, h)
    peca = op.afegeix_solapes(fulla, [((0, h), (0, 0))], f, angle=90.0)
    peca = op.plega(peca, (0, 0), (0, h))
    peca.notes += ["Enganxa la tira de la frontissa al mur, al costat de l'obertura.",
                   "La fulla gira pel plec."]
    return [peca]


TECNIQUES: dict[str, Callable[[Part], list[op.Peca]]] = {
    "caixa_5_cares": caixa_5_cares,
    "enfonsat": caixa_5_cares,          # mateixa xarxa; el mur es retalla igual (vegeu `talls`)
    "sortint": sortint,
    "retall_frontissa": retall_frontissa,
    "forat": lambda part: [],            # no té peces pròpies: només retalla el mur
}


def _obertura(part: Part) -> Polygon:
    """El rectangle que la part deixa obert al mur, a (x, y) en coordenades del mur."""
    forma = part.params.get("forma", "quadrada")
    if forma != "quadrada":
        raise ValueError(f"La forma «{forma}» encara no té tall (només quadrada).")
    w, h = float(part.params["amplada"]), float(part.params["alcada"])
    x, y = float(part.params.get("x", 0.0)), float(part.params.get("y", 0.0))
    return Polygon([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])


TALLS_MUR = {"forat", "enfonsat", "caixa_5_cares", "retall_frontissa"}   # tècniques que obren el mur


def talls(part: Part) -> list[Polygon]:
    """Retalls que la part fa al mur on s'ancora (en coordenades del mur). `sortint` no en fa."""
    return [_obertura(part)] if part.tecnica in TALLS_MUR else []


def fabrica(part: Part) -> list[op.Peca]:
    try:
        f = TECNIQUES[part.tecnica]
    except KeyError:
        raise ValueError(f"Cap tècnica «{part.tecnica}» (hi ha {', '.join(TECNIQUES)}).") from None
    return f(part)
