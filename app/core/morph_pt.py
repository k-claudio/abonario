"""Etiquetas gramaticais compactas, descrição em português e paradigmas.

Formato das etiquetas (campo `forms.tags`): conjuntos de códigos separados por espaço;
leituras alternativas separadas por "|". Ex.: "1 s ind mqp|3 s ind mqp".
"""
from __future__ import annotations

import re

EN_TAGS = {
    "first-person": "1", "second-person": "2", "third-person": "3",
    "singular": "s", "plural": "p",
    "indicative": "ind", "subjunctive": "sub", "imperative": "imp", "conditional": "cond",
    "present": "pres", "preterite": "pret", "imperfect": "imperf", "pluperfect": "mqp",
    "future": "fut", "infinitive": "inf", "personal": "pess", "impersonal": "impess",
    "gerund": "ger", "participle": "part", "negative": "neg", "affirmative": "afirm",
    "masculine": "m", "feminine": "f", "diminutive": "dim", "augmentative": "aum",
    "superlative": "sup", "comparative": "comp",
}
CODE_ORDER = ["1", "2", "3", "s", "p", "m", "f", "pres", "pret", "imperf", "mqp", "fut",
              "ind", "sub", "imp", "cond", "neg", "afirm", "inf", "pess", "impess", "ger",
              "part", "dim", "aum", "sup", "comp"]
_ORDER = {c: i for i, c in enumerate(CODE_ORDER)}


def norm_codes(codes) -> str:
    return " ".join(sorted(set(codes), key=lambda c: _ORDER.get(c, 99)))


def codes_from_en(tags) -> str:
    t = set(tags)
    codes = {EN_TAGS[x] for x in t if x in EN_TAGS}
    if "future" in t and "past" in t:      # futuro do pretérito (tabelas do Wikcionário-pt)
        codes -= {"fut", "ind"}
        codes.add("cond")
    elif "future" in t and "present" in t:  # futuro do presente
        codes.discard("pres")
    return norm_codes(codes)


_PT_RULES = [  # aplicadas à glosa sem acentos (o Wikcionário às vezes escreve "preterito")
    (r"\bprimeira pessoa", "1"), (r"\bsegunda pessoa", "2"), (r"\bterceira pessoa", "3"),
    (r"\bdo singular\b|\bsingular\b", "s"), (r"\bdo plural\b|\bplural\b", "p"),
    (r"\bfeminin", "f"), (r"\bmasculin", "m"),
    (r"mais-que-perfeito|mais que perfeito", "mqp"), (r"preterito imperfeito|imperfeito", "imperf"),
    (r"preterito perfeito|perfeito", "pret"), (r"futuro do preterito|condicional", "cond"),
    (r"futuro", "fut"), (r"presente", "pres"),
    (r"indicativo", "ind"), (r"subjuntivo|conjuntivo", "sub"), (r"imperativo", "imp"),
    (r"negativo", "neg"), (r"infinitivo pessoal|infinitivo flexionado", "pess"),
    (r"infinitivo", "inf"), (r"gerundio", "ger"), (r"participio", "part"),
    (r"diminutivo", "dim"), (r"aumentativo", "aum"), (r"superlativo", "sup"),
]
_PT_RULES = [(re.compile(rx), c) for rx, c in _PT_RULES]


def codes_from_pt_gloss(gloss: str) -> str:
    from .textnorm import fold
    g = fold(gloss)
    codes = set()
    for rx, c in _PT_RULES:
        if rx.search(g):
            codes.add(c)
    if "mqp" in codes or "imperf" in codes:
        codes.discard("pret")
    if "cond" in codes:
        codes.discard("fut")
        codes.discard("pret")
    if "pess" in codes:
        codes.add("inf")
    return norm_codes(codes)


_TENSES = [  # (chave, rótulo)
    (("ind", "pres"), "presente do indicativo"),
    (("ind", "pret"), "pretérito perfeito do indicativo"),
    (("ind", "imperf"), "pretérito imperfeito do indicativo"),
    (("ind", "mqp"), "pretérito mais-que-perfeito do indicativo"),
    (("ind", "fut"), "futuro do presente do indicativo"),
    (("cond",), "futuro do pretérito (condicional)"),
    (("sub", "pres"), "presente do subjuntivo (conjuntivo)"),
    (("sub", "imperf"), "pretérito imperfeito do subjuntivo"),
    (("sub", "fut"), "futuro do subjuntivo"),
    (("imp", "neg"), "imperativo negativo"),
    (("imp",), "imperativo afirmativo"),
    (("inf", "pess"), "infinitivo pessoal"),
]


def tense_key(c: set[str]) -> str | None:
    """Tempo/modo de um conjunto de códigos. A ordem importa: algumas fontes marcam o
    condicional como "futuro + indicativo" e o futuro do presente como "futuro + presente"."""
    if "cond" in c:
        return "futuro do pretérito (condicional)"
    if "imp" in c:
        return "imperativo negativo" if "neg" in c else "imperativo afirmativo"
    if "pess" in c:
        return "infinitivo pessoal"
    if "sub" in c:
        if "fut" in c:
            return "futuro do subjuntivo"
        if "imperf" in c or "pret" in c:
            return "pretérito imperfeito do subjuntivo"
        if "pres" in c:
            return "presente do subjuntivo (conjuntivo)"
        return None
    if "fut" in c:
        return "futuro do presente do indicativo"
    if "mqp" in c:
        return "pretérito mais-que-perfeito do indicativo"
    if "imperf" in c:
        return "pretérito imperfeito do indicativo"
    if "pret" in c:
        return "pretérito perfeito do indicativo"
    if "pres" in c and ("ind" in c or {"1", "2", "3"} & c):
        return "presente do indicativo"
    return None


def _join_persons(persons: list[str]) -> str:
    labels = [f"{p}ª" for p in persons]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " e " + labels[-1]


def describe(tags: str | None) -> list[str]:
    """Descrições em português de cada leitura ("1ª e 3ª pessoa do singular do ...").

    Leituras do mesmo tempo e número são fundidas; rótulos soltos ("singular") somem
    quando há uma descrição mais completa."""
    if not tags:
        return []
    verbal: dict[tuple[str, str], set[str]] = {}
    out: list[str] = []
    for alt in tags.split("|"):
        c = set(alt.split())
        if not c:
            continue
        if "inf" in c and {"1", "2", "3"} & c:  # infinitivo com pessoa = infinitivo pessoal
            c.add("pess")
        num = "singular" if "s" in c else ("plural" if "p" in c else "")
        if "ger" in c:
            out.append("gerúndio")
            continue
        if "part" in c:
            g = " ".join(x for x in ("masculino" if "m" in c else "", "feminino" if "f" in c else "", num) if x)
            out.append("particípio" + (f" ({g})" if g else ""))
            continue
        if "inf" in c and "pess" not in c:
            out.append("infinitivo")
            continue
        t = tense_key(c)
        if t:
            key = (num, t)
            if key not in verbal:
                verbal[key] = set()
                out.append(key)  # marcador de posição, resolvido abaixo
            verbal[key].update(p for p in ("1", "2", "3") if p in c)
            continue
        parts = []
        if "dim" in c:
            parts.append("diminutivo")
        if "aum" in c:
            parts.append("aumentativo")
        if "sup" in c:
            parts.append("superlativo")
        if "comp" in c:
            parts.append("comparativo")
        if "f" in c:
            parts.append("feminino")
        if "m" in c and "f" not in c and num == "plural":
            parts.append("masculino")
        if num:
            parts.append(num)
        if parts:
            out.append(" ".join(parts))
    final: list[str] = []
    for item in out:
        if isinstance(item, tuple):
            num, t = item
            persons = sorted(verbal[item])
            pp = _join_persons(persons) if persons else ""
            head = f"{pp} pessoa do {num}" if pp and num else (f"{pp} pessoa" if pp else num)
            item = f"{head} do {t}" if head else t
        if item not in final:
            final.append(item)
    generic = {"singular", "plural"}
    if any(d not in generic for d in final):
        final = [d for d in final if d not in generic]
    if any(d.startswith("particípio (") for d in final):
        final = [d for d in final if d != "particípio"]
    return final


# --- paradigma verbal ---------------------------------------------------------
PERSON_ROWS = [("1", "s", "eu"), ("2", "s", "tu"), ("3", "s", "ele/ela"),
               ("1", "p", "nós"), ("2", "p", "vós"), ("3", "p", "eles/elas")]
TABLE_TENSES = [label for _, label in _TENSES]


def verb_paradigm(rows: list[tuple[str, str]]) -> dict:
    """rows: (forma, tags). Devolve {'nominais': {...}, 'tempos': {rótulo: {(p,n): [formas]}}}."""
    tempos: dict[str, dict[tuple[str, str], list[str]]] = {}
    nominais: dict[str, list[str]] = {}
    for form, tags in rows:
        if not tags:
            continue
        for alt in tags.split("|"):
            c = set(alt.split())
            if "inf" in c and {"1", "2", "3"} & c:
                c.add("pess")
            if "ger" in c:
                nominais.setdefault("gerúndio", []).append(form)
            elif "part" in c:
                nominais.setdefault("particípio", []).append(form)
            elif "inf" in c and "pess" not in c:
                nominais.setdefault("infinitivo", []).append(form)
            else:
                t = tense_key(c)
                if not t:
                    continue
                for p in ("1", "2", "3"):
                    if p in c:
                        for n in ("s", "p"):
                            if n in c:
                                cell = tempos.setdefault(t, {}).setdefault((p, n), [])
                                if form not in cell:
                                    cell.append(form)
    for k in nominais:
        nominais[k] = list(dict.fromkeys(nominais[k]))
    return {"nominais": nominais, "tempos": tempos}
