"""Biblioteca d'etiquetes: elements (finestra, columna, teulada...) descrits com a dades.

Una `Etiqueta` és un element amb tres eixos: la *forma* (quadrada, arc...), l'*espai* on existeix
(superfície, maqueta o planta; `segona_paret` diu si a la planta es té en compte el mur de darrere)
i el *tipus* d'execució (forat, enfonsat, sortint, retall amb frontissa, caixa de 5 cares...).
Declara les mides que cal ajustar a cada cas i, per a cada tipus de desplegable (paper, cnc, 3d),
un `ModelAplicacio`: paràmetres per defecte i estructura de muntatge. El model `*` serveix de
base per als desplegables que no en tenen de propi.

Afegir un element nou és afegir un fitxer JSON a la biblioteca; l'editor extern els produirà.
Aquest mòdul només les carrega, les valida i en fa `Part`s; no fabrica res.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from parts import Part

VERSIO = 1
ESPAIS = ("superficie", "maqueta", "planta")
BASE = "*"   # model d'aplicació que valen tots els desplegables sense el seu


@dataclass
class Mida:
    defecte: float
    min: float | None = None
    max: float | None = None
    unitat: str = "mm"

    def __post_init__(self):
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("La mida té el mínim per sobre del màxim.")
        self.comprova(self.defecte)

    def comprova(self, v: float) -> float:
        if (self.min is not None and v < self.min) or (self.max is not None and v > self.max):
            raise ValueError(f"{v:g} {self.unitat} fora del rang [{self.min}, {self.max}].")
        return float(v)


@dataclass
class ModelAplicacio:
    """Com es fa una etiqueta en un tipus de desplegable."""
    params: dict = field(default_factory=dict)       # valors per defecte propis d'aquest desplegable
    muntatge: list[str] = field(default_factory=list)  # passos d'instruccions, en ordre


@dataclass
class Etiqueta:
    id: str
    element: str                    # finestra, columna, teulada...
    forma: str                      # quadrada, arc...
    espai: str
    tipus: str
    segona_paret: bool = False
    mides: dict[str, Mida] = field(default_factory=dict)
    models: dict[str, ModelAplicacio] = field(default_factory=dict)

    def __post_init__(self):
        for c in ("id", "element", "forma", "tipus"):
            if not getattr(self, c):
                raise ValueError(f"L'etiqueta necessita «{c}».")
        if self.espai not in ESPAIS:
            raise ValueError(f"Espai «{self.espai}» desconegut (cal {', '.join(ESPAIS)}).")
        if self.segona_paret and self.espai != "planta":
            raise ValueError("Només una planta pot tenir en compte una segona paret.")

    def model(self, desplegable: str) -> ModelAplicacio:
        """El model del desplegable; si no en té, el base; si tampoc, un de buit."""
        return self.models.get(desplegable) or self.models.get(BASE) or ModelAplicacio()

    def resol(self, mides: dict[str, float] | None = None, desplegable: str = BASE) -> dict:
        """Paràmetres finals: defecte de cada mida < model del desplegable < mides donades.
        Una mida donada que no és de l'etiqueta o surt del rang és un error."""
        mides = mides or {}
        for k in mides:
            if k not in self.mides:
                raise ValueError(f"«{self.id}» no té la mida «{k}» (té {', '.join(self.mides)}).")
        out = {k: m.defecte for k, m in self.mides.items()}
        for k, v in self.model(desplegable).params.items():
            out[k] = self.mides[k].comprova(v) if k in self.mides else v
        for k, v in mides.items():
            out[k] = self.mides[k].comprova(v)
        return out

    def crea_part(self, nom: str, desplegable: str = BASE, mides: dict[str, float] | None = None,
                  ancoratge: str | None = None, origen: str = "manual",
                  confianca: float = 1.0) -> Part:
        params = self.resol(mides, desplegable)
        params.update(etiqueta=self.id, forma=self.forma, espai=self.espai,
                      segona_paret=self.segona_paret, muntatge=list(self.model(desplegable).muntatge))
        return Part(nom, self.tipus, params=params, ancoratge=ancoratge,
                    origen=origen, confianca=confianca)

    @classmethod
    def de_dict(cls, d: dict) -> "Etiqueta":
        if d.get("versio") != VERSIO:
            raise ValueError(f"Versió d'etiqueta {d.get('versio')!r} no suportada.")
        return cls(id=d.get("id", ""), element=d.get("element", ""), forma=d.get("forma", ""),
                   espai=d.get("espai", ""), tipus=d.get("tipus", ""),
                   segona_paret=d.get("segona_paret", False),
                   mides={k: Mida(**v) for k, v in d.get("mides", {}).items()},
                   models={k: ModelAplicacio(**v) for k, v in d.get("models", {}).items()})


class Biblioteca:
    def __init__(self, etiquetes: list[Etiqueta] | None = None):
        self.etiquetes: dict[str, Etiqueta] = {}
        for e in etiquetes or []:
            self.afegeix(e)

    def __len__(self) -> int:
        return len(self.etiquetes)

    def __iter__(self):
        return iter(self.etiquetes.values())

    def afegeix(self, e: Etiqueta) -> Etiqueta:
        if e.id in self.etiquetes:
            raise ValueError(f"Ja hi ha una etiqueta «{e.id}».")
        self.etiquetes[e.id] = e
        return e

    def get(self, id: str) -> Etiqueta:
        try:
            return self.etiquetes[id]
        except KeyError:
            raise KeyError(f"No hi ha cap etiqueta «{id}» a la biblioteca.") from None

    def cerca(self, **eixos) -> list[Etiqueta]:
        """Etiquetes que compleixen tots els eixos donats: element, forma, espai, tipus."""
        mal = set(eixos) - {"element", "forma", "espai", "tipus"}
        if mal:
            raise ValueError(f"Eix desconegut: {', '.join(sorted(mal))}.")
        return [e for e in self if all(getattr(e, k) == v for k, v in eixos.items())]

    @classmethod
    def carrega(cls, carpeta: str | Path) -> "Biblioteca":
        """Totes les etiquetes `*.json` de la carpeta. Un error diu quin fitxer el causa."""
        bib = cls()
        for f in sorted(Path(carpeta).glob("*.json")):
            try:
                bib.afegeix(Etiqueta.de_dict(json.loads(f.read_text(encoding="utf-8"))))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"{f.name}: {exc}") from exc
        return bib
