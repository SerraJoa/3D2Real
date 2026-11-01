"""Desplegable per parts: una peça és una llista de `Part`, cadascuna amb la seva tècnica.

Una `Part` és un volum (cos, columna, teulada, finestra...) amb la tècnica que el fabrica i,
si no és el cos, l'ancoratge: la part on s'enganxa. El `PlaFabricacio` és la llista de parts
i és el mateix tant si l'omple l'usuari, una detecció local o un VL: cada part guarda d'on ve
(`origen`) i quanta confiança hi ha (`confianca`), que és el que després es mostra al mode desatès.

Aquest mòdul no sap fabricar res: només descriu què es fabrica i en quin ordre es munta.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ORIGENS = ("manual", "detectat", "vl")
VERSIO = 1


@dataclass
class Part:
    nom: str
    tecnica: str                                   # clau de la tècnica (cos, columna, teulada...)
    cares: list[int] | None = None                 # cares del model que cobreix; None = cap (forma pròpia)
    params: dict = field(default_factory=dict)     # mides i opcions de la tècnica
    ancoratge: str | None = None                   # nom de la part on s'enganxa; None = arrel
    origen: str = "manual"
    confianca: float = 1.0

    def __post_init__(self):
        if not self.nom:
            raise ValueError("Una part necessita nom.")
        if self.origen not in ORIGENS:
            raise ValueError(f"Origen «{self.origen}» desconegut (cal {', '.join(ORIGENS)}).")
        if not 0.0 <= self.confianca <= 1.0:
            raise ValueError("La confiança ha d'estar entre 0 i 1.")
        if self.ancoratge == self.nom:
            raise ValueError(f"La part «{self.nom}» no es pot ancorar a si mateixa.")

    def a_dict(self) -> dict:
        return dict(nom=self.nom, tecnica=self.tecnica,
                    cares=None if self.cares is None else [int(c) for c in self.cares],
                    params=self.params, ancoratge=self.ancoratge,
                    origen=self.origen, confianca=self.confianca)

    @classmethod
    def de_dict(cls, d: dict) -> "Part":
        return cls(**d)


class PlaFabricacio:
    """Parts amb nom únic i ancoratges vàlids, ordenables per al muntatge."""

    def __init__(self, parts: list[Part] | None = None):
        self.parts: list[Part] = []
        for p in parts or []:
            self.afegeix(p)

    def __len__(self) -> int:
        return len(self.parts)

    def __iter__(self):
        return iter(self.parts)

    def part(self, nom: str) -> Part:
        for p in self.parts:
            if p.nom == nom:
                return p
        raise KeyError(nom)

    def afegeix(self, p: Part) -> Part:
        if any(q.nom == p.nom for q in self.parts):
            raise ValueError(f"Ja hi ha una part «{p.nom}».")
        self.parts.append(p)
        return p

    def treu(self, nom: str) -> None:
        """Treu la part i, amb ella, tot el que hi està enganxat."""
        sortir = {nom, *(p.nom for p in self.descendents(nom))}
        self.parts = [p for p in self.parts if p.nom not in sortir]

    def fills(self, nom: str) -> list[Part]:
        return [p for p in self.parts if p.ancoratge == nom]

    def descendents(self, nom: str) -> list[Part]:
        out, pendents = [], self.fills(nom)
        while pendents:
            p = pendents.pop(0)
            out.append(p)
            pendents.extend(self.fills(p.nom))
        return out

    def arrels(self) -> list[Part]:
        return [p for p in self.parts if p.ancoratge is None]

    def comprova(self) -> None:
        """Llança ValueError si hi ha ancoratges que no existeixen o cicles."""
        noms = {p.nom for p in self.parts}
        for p in self.parts:
            if p.ancoratge is not None and p.ancoratge not in noms:
                raise ValueError(f"La part «{p.nom}» s'ancora a «{p.ancoratge}», que no existeix.")
        for p in self.parts:
            vist, a = {p.nom}, p.ancoratge
            while a is not None:
                if a in vist:
                    raise ValueError(f"Cicle d'ancoratges que passa per «{a}».")
                vist.add(a)
                a = self.part(a).ancoratge

    def ordre_muntatge(self) -> list[Part]:
        """Cada part després d'aquella on s'enganxa; entre germanes, l'ordre d'entrada."""
        self.comprova()
        out, pendents = [], self.arrels()
        while pendents:
            p = pendents.pop(0)
            out.append(p)
            pendents = self.fills(p.nom) + pendents
        return out

    def dubtoses(self, llindar: float = 0.7) -> list[Part]:
        """Parts amb poca confiança: el que el mode desatès ha de mostrar com a dubte."""
        return [p for p in self.parts if p.confianca < llindar]

    def a_dict(self) -> dict:
        return dict(versio=VERSIO, parts=[p.a_dict() for p in self.parts])

    @classmethod
    def de_dict(cls, d: dict) -> "PlaFabricacio":
        if d.get("versio") != VERSIO:
            raise ValueError(f"Versió de pla {d.get('versio')!r} no suportada.")
        pla = cls([Part.de_dict(p) for p in d["parts"]])
        pla.comprova()
        return pla
