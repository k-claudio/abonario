"""Temas visuais: claro, sépia e escuro."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

# cores do conteúdo (verbetes e trechos); usadas para gerar o CSS do QTextBrowser
_CSS_CLARO = dict(
    text="#1f1d1a", heading="#5a2d0c", rule="#d8cbb8", h3="#6b4a2b", link="#8a3b12",
    analysis="#3b3a36", via="#6d6a63", panel="#f3ede2", gram="#2f5d50", usg="#7a5c2e",
    pron="#6d6a63", etym="#6d6a63", cit="#3b3a36", ex="#44423d", ref="#7d7a72", src="#8d877c",
    num="#9a948a", zero="#b5afa5", amb="#a0522d", hl_bg="#ffe39a", hl_text="#1f1d1a", muted="#8d877c",
)
_CSS_SEPIA = dict(
    text="#3a2e1f", heading="#6b3510", rule="#cdb98c", h3="#7a5530", link="#8a3b12",
    analysis="#4a3b28", via="#7a6a50", panel="#eadcb4", gram="#3d5f4c", usg="#835f2a",
    pron="#7a6a50", etym="#7a6a50", cit="#4a3b28", ex="#4f412d", ref="#857358", src="#927f5e",
    num="#9a8866", zero="#bba98a", amb="#9a4a22", hl_bg="#e8c766", hl_text="#2e2416", muted="#8c7a5b",
)
_CSS_ESCURO = dict(
    text="#e4dfd6", heading="#e7b07a", rule="#4a4038", h3="#d9a877", link="#f0a868",
    analysis="#d6d0c6", via="#a59f95", panel="#2c2823", gram="#86c7aa", usg="#d6b27c",
    pron="#a59f95", etym="#a59f95", cit="#d6d0c6", ex="#cfc9bf", ref="#9d978d", src="#9d978d",
    num="#8f897f", zero="#6b665e", amb="#e08a5a", hl_bg="#7a5a12", hl_text="#fff3c4", muted="#9d978d",
)

THEMES: dict[str, dict] = {
    "claro": dict(label="Claro", style=None, palette=None, css=_CSS_CLARO),
    "sepia": dict(
        label="Sépia", style="Fusion", css=_CSS_SEPIA,
        palette=dict(window="#e9dcb8", base="#f4e9cc", alt="#efe2bf", text="#3a2e1f", button="#e3d4ab",
                     highlight="#b98b4e", highlighted_text="#fffaf0", tooltip="#fff6dc", link="#8a3b12",
                     placeholder="#8c7a5b"),
    ),
    "escuro": dict(
        label="Escuro", style="Fusion", css=_CSS_ESCURO,
        palette=dict(window="#25262a", base="#1b1c1f", alt="#232428", text="#e4dfd6", button="#2f3136",
                     highlight="#8a5a2b", highlighted_text="#ffffff", tooltip="#2f3136", link="#f0a868",
                     placeholder="#8f897f"),
    ),
}


def palette(theme: dict) -> QPalette:
    c = {k: QColor(v) for k, v in theme["palette"].items()}
    p = QPalette()
    roles = {
        QPalette.Window: c["window"], QPalette.WindowText: c["text"], QPalette.Base: c["base"],
        QPalette.AlternateBase: c["alt"], QPalette.Text: c["text"], QPalette.Button: c["button"],
        QPalette.ButtonText: c["text"], QPalette.BrightText: QColor("#ff5c5c"),
        QPalette.Highlight: c["highlight"], QPalette.HighlightedText: c["highlighted_text"],
        QPalette.ToolTipBase: c["tooltip"], QPalette.ToolTipText: c["text"], QPalette.Link: c["link"],
        QPalette.PlaceholderText: c["placeholder"],
        QPalette.Light: c["button"].lighter(125), QPalette.Midlight: c["button"].lighter(110),
        QPalette.Mid: c["button"].darker(130), QPalette.Dark: c["button"].darker(160),
        QPalette.Shadow: c["button"].darker(220),
    }
    for role, color in roles.items():
        p.setColor(role, color)
    dim = c["placeholder"]
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, dim)
    return p


def css(theme: dict) -> str:
    k = theme["css"]
    return f"""
body {{ color: {k['text']}; }}
h1 {{ color: {k['heading']}; margin-bottom: 2px; }}
h2 {{ color: {k['heading']}; margin-top: 18px; margin-bottom: 4px; border-bottom: 1px solid {k['rule']}; }}
h3 {{ color: {k['h3']}; margin-top: 10px; margin-bottom: 2px; }}
a {{ color: {k['link']}; text-decoration: none; }}
.analysis {{ color: {k['analysis']}; margin-top: 2px; }}
.via {{ color: {k['via']}; font-style: italic; }}
.also {{ color: {k['analysis']}; background-color: {k['panel']}; padding: 4px; }}
.choose {{ background-color: {k['panel']}; padding: 6px; }}
.gram {{ color: {k['gram']}; font-weight: bold; }}
.usg {{ color: {k['usg']}; font-style: italic; }}
.pron {{ color: {k['pron']}; }}
.etym {{ color: {k['etym']}; }}
.cit {{ font-style: italic; color: {k['cit']}; }}
.ex {{ color: {k['ex']}; margin-left: 12px; font-style: italic; }}
.ref {{ color: {k['ref']}; font-style: normal; }}
.rel {{ color: {k['analysis']}; }}
.src {{ color: {k['src']}; }}
.num {{ color: {k['num']}; }}
.zero {{ color: {k['zero']}; }}
.amb {{ color: {k['amb']}; }}
.hl {{ background-color: {k['hl_bg']}; color: {k['hl_text']}; font-weight: bold; }}
.qcit {{ color: {k['via']}; }}
.qtext {{ color: {k['text']}; }}
.muted {{ color: {k['muted']}; }}
"""
