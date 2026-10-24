"""Botó que obre un contingut HTML en una pestanya nova (via Blob, sense servidor)."""
import streamlit as st

_JS = r"""
export default function({ data, parentElement }) {
  let b = parentElement.querySelector('button');
  if (!b) { b = document.createElement('button'); parentElement.appendChild(b); }
  b.textContent = data.text;
  b.onclick = () => {
    const url = URL.createObjectURL(new Blob([data.html], { type: 'text/html' }));
    window.open(url, '_blank');
  };
}
"""

_CSS = """
button { width: 100%; padding: .55rem 1rem; border-radius: 10px; cursor: pointer; font-size: 1rem;
         border: 1px solid rgba(128,128,128,.5); background: transparent; color: inherit; }
button:hover { border-color: #5a8cdc; }
"""

_component = None


def obre(text: str, html: str, key: str) -> None:
    global _component
    if _component is None:
        _component = st.components.v2.component("desplegables_obre", js=_JS, css=_CSS)
    _component(data=dict(text=text, html=html), key=key)


def pagina_html(titol: str, pagines: list[str]) -> str:
    """Document HTML amb les pàgines SVG una sota l'altra."""
    cos = "".join(f"<section><h3>{titol} {i + 1}</h3>{svg}</section>" for i, svg in enumerate(pagines))
    return ("<!doctype html><meta charset='utf-8'><title>" + titol + "</title>"
            "<style>body{font-family:sans-serif;background:#eee;margin:0;padding:1rem}"
            "section{background:#fff;margin:0 auto 1.5rem;max-width:1000px;padding:1rem;"
            "box-shadow:0 2px 8px rgba(0,0,0,.2)}svg{width:100%;height:auto}h3{margin:.2rem 0 .6rem}</style>"
            + cos)
