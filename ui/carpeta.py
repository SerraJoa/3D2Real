"""Carpeta per defecte: d'on es carreguen models i imatges i on es desen els resultats.

`dades/` (o la ruta de `DESPLEGABLES_DADES`) conté subcarpetes (p. ex. `demo guineu`) amb els fitxers
d'entrada; els resultats van a `dades/sortida/`. Es pot triar un fitxer de la carpeta o pujar-ne un.
"""
import os
from pathlib import Path

import streamlit as st

ARREL = Path(os.environ.get("DESPLEGABLES_DADES") or Path(__file__).resolve().parent.parent / "dades")
SORTIDA = ARREL / "sortida"


class Fitxer:
    """Fitxer de la carpeta amb la interfície d'un `st.file_uploader`."""

    def __init__(self, cami: Path):
        self.name, self._cami = cami.name, cami

    def getvalue(self) -> bytes:
        return self._cami.read_bytes()


def llista(exts: tuple) -> list:
    """Fitxers de la carpeta per defecte (sense `sortida`) amb aquestes extensions, ruta relativa."""
    if not ARREL.is_dir():
        return []
    return sorted(p.relative_to(ARREL) for p in ARREL.rglob("*")
                  if p.is_file() and p.suffix.lower() in exts and SORTIDA not in p.parents)


def tria(exts: tuple, key: str, multiple: bool = False) -> list:
    """Selector «De la carpeta» (els models porten els seus MTL i imatges de la mateixa subcarpeta)."""
    opcions = llista(exts)
    if not opcions:
        return []
    triats = st.multiselect("De la carpeta per defecte", opcions, key=key, format_func=str) if multiple else [
        p for p in [st.selectbox("De la carpeta per defecte", [None] + opcions, key=key,
                                 format_func=lambda p: "—" if p is None else str(p))] if p is not None]
    return [Fitxer(ARREL / p) for p in triats]


def germans(f: Fitxer, exts: tuple) -> list:
    """Fitxers de la mateixa subcarpeta que `f` (MTL, textures) per completar un OBJ."""
    return [Fitxer(p) for p in f._cami.parent.iterdir() if p.is_file() and p.suffix.lower() in exts and p != f._cami]


def desa(nom: str, dades: bytes) -> Path:
    """Desa un resultat a la carpeta de sortida i retorna la ruta."""
    SORTIDA.mkdir(parents=True, exist_ok=True)
    cami = SORTIDA / nom
    cami.write_bytes(dades)
    return cami
