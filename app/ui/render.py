"""Geração do HTML exibido no QTextBrowser (verbete e abonações)."""
from __future__ import annotations

import html
from urllib.parse import quote

from ..core.db import Database, Sentence
from ..core.lookup import Lookup, LookupResult, Reading
from ..core.morph_pt import PERSON_ROWS, verb_paradigm
from ..core.textnorm import WORD_RE
from . import themes

SRC_DA, SRC_WIKT = 1, 2

CSS = themes.css(themes.THEMES["claro"])  # trocado por MainWindow.apply_theme

SHORT_TENSE = {
    "presente do indicativo": "Presente", "pretérito perfeito do indicativo": "Pret. perfeito",
    "pretérito imperfeito do indicativo": "Pret. imperfeito",
    "pretérito mais-que-perfeito do indicativo": "Mais-que-perfeito",
    "futuro do presente do indicativo": "Futuro do presente",
    "futuro do pretérito (condicional)": "Futuro do pretérito",
    "presente do subjuntivo (conjuntivo)": "Presente", "pretérito imperfeito do subjuntivo": "Pret. imperfeito",
    "futuro do subjuntivo": "Futuro", "imperativo afirmativo": "Afirmativo", "imperativo negativo": "Negativo",
    "infinitivo pessoal": "Infinitivo pessoal",
}
GROUPS = [
    ("Indicativo", ["presente do indicativo", "pretérito perfeito do indicativo",
                    "pretérito imperfeito do indicativo", "pretérito mais-que-perfeito do indicativo",
                    "futuro do presente do indicativo", "futuro do pretérito (condicional)"]),
    ("Subjuntivo (conjuntivo)", ["presente do subjuntivo (conjuntivo)", "pretérito imperfeito do subjuntivo",
                                 "futuro do subjuntivo"]),
    ("Imperativo e infinitivo pessoal", ["imperativo afirmativo", "imperativo negativo", "infinitivo pessoal"]),
]


def e(s: str) -> str:
    return html.escape(s or "", quote=False)


def href(kind: str, value: str) -> str:
    return f"{kind}:{quote(value, safe='')}"


def fmt_n(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _reading_line(r: Reading) -> str:
    d = "; ".join(r.descriptions)
    return f'<a href="{href("l", r.lemma)}">{e(r.lemma)}</a>' + (f" — {e(d)}" if d else "")


def form_link(form: str, freq: dict[str, int], amb: dict[str, int] | None = None) -> str:
    n = freq.get(form, 0)
    cls = "" if n else ' class="zero"'
    mark = '<span class="amb">*</span>' if amb and amb.get(form, 0) > 1 else ""
    num = f' <span class="num">{fmt_n(n)}</span>' if n else ""
    return f'<a href="{href("f", form)}"{cls}>{e(form)}</a>{mark}{num}'


def entry_html(db: Database, lk: Lookup, res: LookupResult, lemma: str) -> tuple[str, list[str], dict[str, int]]:
    """HTML do verbete; devolve também as formas do lema (para as abonações) e suas frequências."""
    out = [f"<h1>{e(lemma)}</h1>"]
    q = f"<b>{e(res.query)}</b>"
    if res.via.startswith("grafia antiga"):
        out.append(f'<p class="analysis">{q}: grafia antiga de <b>{e(lemma)}</b></p>')
    elif res.form and res.form != lemma.lower():
        sel = next((r for r in res.main + res.also if r.lemma == lemma), None)
        desc = "; ".join(sel.descriptions) if sel and sel.descriptions else ""
        via = f' <span class="via">({e(res.via.split(":")[0])})</span>' if res.via else ""
        if desc:
            out.append(f'<p class="analysis">{q}: {e(desc)} de <b>{e(lemma)}</b>{via}</p>')
        else:
            out.append(f'<p class="analysis">{q} → <b>{e(lemma)}</b>{via}</p>')
    if len(res.main) > 1:
        items = "".join(f"<li>{_reading_line(r)}</li>" for r in res.main)
        out.append(f'<div class="choose">A forma {q} pertence a mais de um lema:<ul>{items}</ul></div>')
    if res.also:
        # "também é forma de" só quando a palavra pesquisada é o próprio verbete (fora -> ser, ir)
        same = res.main and res.main[0].is_headword and not res.via and res.form == lemma.lower()
        lab = "Também é forma de" if same else "Ver também"
        out.append(f'<p class="also">{lab}: ' + "; ".join(_reading_line(r) for r in res.also) + "</p>")

    entries = db.entries(lemma)
    da = [x for x in entries if x[1] == SRC_DA]
    wk = [x for x in entries if x[1] == SRC_WIKT]
    if not entries:
        out.append('<p class="muted">Sem definição nas fontes do dicionário; '
                   "veja abaixo as formas e as abonações.</p>")
    if da:
        out.append('<h2>Dicionário Aberto <span class="src">(Cândido de Figueiredo, 1913)</span></h2>')
        for i, (lem, _, hom, pos, body) in enumerate(da, 1):
            if len(da) > 1:
                out.append(f"<h3>{e(lem)} <sup>{i}</sup></h3>")
            out.append(body)
    if wk:
        out.append('<h2>Wikcionário</h2>')
        for lem, _, hom, pos, body in wk:
            if lem != lemma and lem.lower() == lemma.lower():
                out.append(f"<h3>{e(lem)}</h3>")
            out.append(body)

    forms = lk.lemma_forms(lemma)
    names = [f for f, _ in forms]
    freq = db.freq(names)
    amb = db.lemma_count(names)
    para = verb_paradigm(forms)
    if para["tempos"]:
        out.append("<h2>Conjugação</h2>")
        nom = para["nominais"]
        inf = nom.setdefault("infinitivo", [])
        if lemma.lower() not in inf:
            inf.insert(0, lemma.lower())
        if nom:
            bits = []
            for k in ("infinitivo", "gerúndio", "particípio"):
                if k in nom:
                    bits.append(f"<b>{k}:</b> " + ", ".join(form_link(f, freq, amb) for f in nom[k]))
            out.append("<p>" + " &nbsp; ".join(bits) + "</p>")
        for gname, tenses in GROUPS:
            present = [t for t in tenses if t in para["tempos"]]
            if not present:
                continue
            out.append(f"<h3>{e(gname)}</h3>")
            rows = ['<table border="0" cellspacing="0" cellpadding="3">', "<tr><td></td>"]
            rows += [f'<td><b>{e(SHORT_TENSE.get(t, t))}</b></td>' for t in present]
            rows.append("</tr>")
            for p, n, pron in PERSON_ROWS:
                rows.append(f'<tr><td class="muted">{pron}</td>')
                for t in present:
                    cell = para["tempos"][t].get((p, n), [])
                    rows.append("<td>" + ", ".join(form_link(f, freq, amb) for f in cell) + "</td>")
                rows.append("</tr>")
            rows.append("</table>")
            out.append("".join(rows))
    attested = sorted((f for f in names if freq.get(f)), key=lambda f: -freq[f])
    if attested:
        out.append(f"<h2>Formas encontradas nos textos <span class=\"src\">({len(attested)})</span></h2>")
        out.append("<p>" + " · ".join(form_link(f, freq, amb) for f in attested) + "</p>")
        if any(amb.get(f, 0) > 1 for f in attested):
            out.append('<p class="muted"><span class="amb">*</span> forma que também pertence a outro lema '
                       "(os trechos podem ser do outro sentido).</p>")
    return "\n".join(out), names, freq


def not_found_html(res: LookupResult) -> str:
    out = [f"<h1>{e(res.query)}</h1>"]
    if res.wildcard:
        out.append(f"<p>{len(res.wildcard)} verbetes para o padrão <b>{e(res.query)}</b>:</p><p>")
        out.append(" · ".join(f'<a href="{href("w", w)}">{e(w)}</a>' for w in res.wildcard))
        out.append("</p>")
        return "".join(out)
    out.append('<p class="muted">Palavra não encontrada no dicionário nem no léxico de formas.</p>')
    if res.suggestions:
        out.append("<p>Verbetes próximos: " + " · ".join(
            f'<a href="{href("w", w)}">{e(w)}</a>' for w in res.suggestions) + "</p>")
    out.append('<p class="muted">Os trechos abaixo mostram a forma exata, se ela aparecer nos textos.</p>')
    return "".join(out)


def definitions_html(query: str, keys: list[str], limit: int = 300) -> str:
    out = [f"<h1>“{e(query)}” nas definições</h1>"]
    if not keys:
        out.append('<p class="muted">Nenhum verbete contém esses termos.</p>')
    else:
        if len(keys) > limit:
            keys = keys[:limit]
            out.append(f'<p class="muted">Mais de {limit} verbetes contêm esses termos; mostrando os {limit} '
                       "primeiros em ordem alfabética. Acrescente palavras para refinar a busca.</p><p>")
        else:
            out.append(f"<p>{len(keys)} verbetes:</p><p>")
        out.append(" · ".join(f'<a href="{href("w", k)}">{e(k)}</a>' for k in keys))
        out.append("</p>")
    return "".join(out)


_SENT_START = (".", "!", "?", ":", "…", ";")


def has_common_match(text: str, termset: set[str], terms_for) -> bool:
    """Há ao menos uma ocorrência que não parece nome próprio (maiúscula no meio da frase)?"""
    for m in WORD_RE.finditer(text):
        tok = m.group()
        if not termset.intersection(terms_for(tok)):
            continue
        if not tok[:1].isupper():
            return True
        before = text[:m.start()].rstrip(" \t\n—–-«\"“'(¡¿")
        if not before or before.endswith(_SENT_START):
            return True  # início de frase: maiúscula normal
    return False


def phrase_spans(text: str, words: list[str], terms_for) -> list[tuple[int, int]]:
    """Posições em que as palavras da expressão aparecem em sequência (aceita grafia antiga)."""
    toks = list(WORD_RE.finditer(text))
    n = len(words)
    if not n or len(toks) < n:
        return []
    sets: list[set[str] | None] = [None] * len(toks)

    def terms_at(i: int) -> set[str]:
        if sets[i] is None:
            sets[i] = set(terms_for(toks[i].group()))
        return sets[i]

    spans, i = [], 0
    while i <= len(toks) - n:
        if all(words[j] in terms_at(i + j) for j in range(n)):
            spans.append((toks[i].start(), toks[i + n - 1].end()))
            i += n
        else:
            i += 1
    return spans


def contains_phrase(text: str, words: list[str], terms_for) -> bool:
    return bool(phrase_spans(text, words, terms_for))


def highlight_phrase(text: str, words: list[str], terms_for) -> str:
    out, last = [], 0
    for a, b in phrase_spans(text, words, terms_for):
        out.append(e(text[last:a]))
        out.append(f'<span class="hl">{e(text[a:b])}</span>')
        last = b
    out.append(e(text[last:]))
    return "".join(out).replace("\n", "<br/>")


def highlight(text: str, termset: set[str], terms_for) -> str:
    out, last = [], 0
    for m in WORD_RE.finditer(text):
        out.append(e(text[last:m.start()]))
        tok = m.group()
        if termset.intersection(terms_for(tok)):
            out.append(f'<span class="hl">{e(tok)}</span>')
        else:
            out.append(e(tok))
        last = m.end()
    out.append(e(text[last:]))
    return "".join(out).replace("\n", "<br/>")


def quote_html(s: Sentence, termset: set[str], terms_for, phrase: list[str] | None = None) -> str:
    flag = {"BR": "Brasil", "PT": "Portugal"}.get(s.work.country, s.work.country)
    flag = f" · {flag}" if flag else ""
    body = highlight_phrase(s.text, phrase, terms_for) if phrase else highlight(s.text, termset, terms_for)
    return (f'<p class="qtext" style="margin-bottom:0px">{body}</p>'
            f'<p class="qcit" style="margin-top:1px; margin-bottom:12px">— {e(s.work.citation())}{e(flag)}'
            f' &nbsp;<a href="ctx:{s.id}">contexto</a> · <a href="cp:{s.id}">copiar</a></p>')
