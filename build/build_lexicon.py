"""Léxico: forms (forma -> lema + etiquetas), alt (grafia antiga -> moderna),
lexicon_known (palavras modernas + bandeiras, para o normalizador) e formfold
(busca sem acento)."""
from __future__ import annotations

import collections
import gzip
import json
import re
import sqlite3

from common import CACHE, DATA, DB_PATH, check_disk, log
from mysqldump import iter_rows
from app.core.morph_pt import codes_from_en, codes_from_pt_gloss
from app.core.textnorm import (F_DA_ONLY, F_FUNCTION, F_MECHURA, F_VERB_FORM, F_VERB_LEMMA,
                               F_WIKT_EN, F_WIKT_PT, Normalizer, fold, skel1, skel2)

SRC_MECHURA, SRC_WIKT_PT, SRC_WIKT_EN = 1, 2, 4
VERBAL = {"ind", "sub", "imp", "cond", "ger", "part", "pess", "inf"}

PT_ALT_STRONG = re.compile(
    r"^(?:grafia antiga|grafia arcaica|antiga grafia|ortografia antiga|forma antiga|forma arcaica|"
    r"grafia anterior[^,;]*?|grafia obsoleta|forma obsoleta)\s+(?:de|do|da)\s+([\w\-]+)\s*\.?$", re.I)
PT_FORM_GLOSS = re.compile(r"^(?:(?:primeira|segunda|terceira) pessoa|ger[uú]ndio|partic[ií]pio|infinitivo)\b.*\bd[oe] verbo\s+['\x22]?([\w\-]+)['\x22]?\s*\.?$", re.I)
PT_ALT_VIDE = re.compile(r"^vide\s+([\w\-]+)\s*\.?$", re.I)
PT_VARIANT = re.compile(r"^(?:variante de|forma alternativa de|o mesmo que)\s+([\w\-]+)\s*\.?$", re.I)
EN_ALT_STRONG = re.compile(
    r"^(?:obsolete|archaic|dated|superseded|pre-reform)\b[^;]*?\b(?:spelling|form)s?\b.*?\bof ([\w\-]+)\s*$", re.I)
EN_ALT_WEAK = re.compile(
    r"^(?:alternative|nonstandard|Brazilian Portuguese standard|European Portuguese standard)\b[^;]*?"
    r"\b(?:spelling|form)s?\b.*?\bof ([\w\-]+)\s*$", re.I)
EN_SKIP_FORM_TAGS = {"table-tags", "inflection-template", "class", "romanization", "canonical"}
ALT_FORM_TAGS = {"alternative", "obsolete", "archaic", "dated", "misspelling", "pronunciation-spelling",
                 "nonstandard", "superseded"}
FORM_GLOSS = re.compile(r"(?:person|plural|singular|participle|gerund|infinitive|feminine|masculine|"
                        r"imperative|subjunctive|indicative)\b.*?\bof ([\w\-]+)\s*$", re.I)


def add_listed_form(lx, form: str, w: str, tags: list[str], src: int, flag: int) -> None:
    """Forma tirada da lista de formas de um verbete."""
    if ALT_FORM_TAGS.intersection(tags):
        if skel2(form) == skel2(w):          # mettido ~ metido: mesma palavra, grafia antiga
            lx.alt[form.lower()].add(w)
        else:                                 # variante de outra forma: só para a busca
            lx.add(form, w, codes_from_en(tags), src)
        return
    lx.add(form, w, codes_from_en(tags), src)
    lx.flags[form.lower()] |= flag

FUNCTION_WORDS = """
a à às ao aos o os as de do da dos das em no na nos nas num numa nuns numas dum duma duns dumas
pelo pela pelos pelas por para pra pro com sem sob sobre entre até desde contra perante após ante
trás e ou mas nem que se porque pois porém todavia contudo logo como quando onde aonde donde quem
qual quais cujo cuja cujos cujas dele dela deles delas deste desta destes destas disto desse dessa
desses dessas disso daquele daquela daqueles daquelas daquilo neste nesta nestes nestas nisto nesse
nessa nesses nessas nisso naquele naquela naqueles naquelas naquilo àquele àquela àqueles àquelas
àquilo daqui dali daí aqui ali aí lá cá acolá não sim já ainda também muito pouco mais menos
ninguém alguém nada tudo algo outrem cada todo toda todos todas mesmo mesma mesmos mesmas eu tu ele
ela nós vós eles elas me te lhe lhes vos mim ti si comigo contigo consigo conosco connosco convosco
meu minha meus minhas teu tua teus tuas seu sua seus suas nosso nossa nossos nossas vosso vossa
vossos vossas isto isso aquilo este esta estes estas esse essa esses essas aquele aquela aqueles
aquelas um uma uns umas outro outra outros outras algum alguma alguns algumas nenhum nenhuma
nenhuns nenhumas tal tais tanto tanta tantos tantas quanto quanta quantos quantas certo certa
""".split()


class Lexicon:
    def __init__(self) -> None:
        self.pairs: dict[tuple[str, str], list] = {}   # (forma, lema) -> [set(tags), src]
        self.flags: dict[str, int] = collections.defaultdict(int)  # palavras modernas
        self.alt: dict[str, set[str]] = collections.defaultdict(set)
        self.obsolete_word: set[str] = set()
        self.verb_words: set[str] = set()

    def add(self, form: str, lemma: str, tags: str, src: int) -> None:
        form = form.strip().lower()
        lemma = lemma.strip()
        if not form or not lemma or " " in form or len(form) > 60:
            return
        p = self.pairs.get((form, lemma))
        if p is None:
            p = self.pairs[(form, lemma)] = [set(), 0]
        if tags:
            p[0].add(tags)
        p[1] |= src


def load_mechura(lx: Lexicon) -> None:
    n = 0
    with open(CACHE / "mechura_pt.txt", encoding="utf-8-sig") as fh:
        for line in fh:
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) != 2:
                continue
            lemma, form = parts
            lx.add(form, lemma, "", SRC_MECHURA)
            lx.flags[form.lower()] |= F_MECHURA
            lx.flags[lemma.lower()] |= F_MECHURA
            n += 1
    log(f"Měchura: {n} pares")


def _last_gloss(s: dict) -> str:
    g = s.get("glosses") or [""]
    return g[-1] if g else ""


def load_wikt_pt(lx: Lexicon) -> None:
    n = alt_n = 0
    entries = collections.defaultdict(lambda: [False, False])  # palavra -> [sentido moderno, remissão antiga]
    with gzip.open(CACHE / "wikt_pt.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("lang_code") != "pt":
                continue
            w = d.get("word", "").strip()
            if not w or " " in w:
                continue
            n += 1
            flags = entries[w.lower()]
            for s in d.get("senses", []):
                g = _last_gloss(s)
                fo = s.get("form_of")
                if not fo:
                    m = PT_FORM_GLOSS.search(g)
                    if m:
                        fo = [{"word": m.group(1)}]
                if fo:
                    lx.add(w, fo[0]["word"], codes_from_pt_gloss(g), SRC_WIKT_PT)
                    flags[0] = True
                    continue
                target = None
                m = PT_ALT_STRONG.match(g)
                if m:
                    target = m.group(1)
                else:
                    m = PT_ALT_VIDE.match(g) or PT_VARIANT.match(g)
                    if m and skel2(m.group(1)) == skel2(w):
                        target = m.group(1)
                if target and target.lower() != w.lower():
                    lx.alt[w.lower()].add(target)
                    flags[1] = True
                    alt_n += 1
                else:
                    flags[0] = True
                    if d.get("pos") == "verb":
                        lx.verb_words.add(w)
            for f in d.get("forms", []) or []:
                tags = f.get("tags") or []
                form = f.get("form", "")
                if form and form != w and " " not in form and not EN_SKIP_FORM_TAGS.intersection(tags):
                    add_listed_form(lx, form, w, tags, SRC_WIKT_PT, F_WIKT_PT)
    for w, (modern, old) in entries.items():
        if modern:
            lx.flags[w] |= F_WIKT_PT
        elif old:
            lx.obsolete_word.add(w)
    log(f"Wikcionário-pt: {n} entradas, {alt_n} remissões de grafia")


def load_wikt_en(lx: Lexicon) -> None:
    path = CACHE / "wikt_en_pt.jsonl.gz"
    if not path.exists():
        log("Wikcionário-en ausente: seguindo sem ele")
        return
    n = alt_n = 0
    entries = collections.defaultdict(lambda: [False, False])
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            w = d.get("word", "").strip()
            if not w or " " in w:
                continue
            n += 1
            flags = entries[w.lower()]
            for s in d.get("senses", []):
                g = _last_gloss(s)
                tags = s.get("tags") or []
                target = None
                if {"obsolete", "archaic", "dated"} & set(tags) and s.get("alt_of"):
                    target = s["alt_of"][0]["word"]
                else:
                    m = EN_ALT_STRONG.match(g)
                    if m:
                        target = m.group(1)
                    else:
                        m = EN_ALT_WEAK.match(g)
                        if m and skel2(m.group(1)) == skel2(w):
                            target = m.group(1)
                if target and target.lower() != w.lower():
                    lx.alt[w.lower()].add(target)
                    flags[1] = True
                    alt_n += 1
                    continue
                fo = s.get("form_of")
                if not fo:
                    m = FORM_GLOSS.search(g)
                    if m and "of" in g:
                        fo = [{"word": m.group(1)}]
                        tags = list(tags) + [t for t in re.split(r"[\s/-]+", g.lower()) if t]
                        tags = [("first-person" if t == "first" else "second-person" if t == "second"
                                 else "third-person" if t == "third" else t) for t in tags]
                if fo:
                    lx.add(w, fo[0]["word"], codes_from_en(tags), SRC_WIKT_EN)
                elif d.get("pos") == "verb":
                    lx.verb_words.add(w)
                flags[0] = True
            for f in d.get("forms", []) or []:
                ftags = f.get("tags") or []
                form = (f.get("form") or "").strip()
                if not form or EN_SKIP_FORM_TAGS.intersection(ftags):
                    continue
                if "negative" in ftags and form.startswith("não "):
                    form = form[4:]
                if " " in form or ("-" in form and "-" not in w):
                    continue
                if form.lower() != w.lower():
                    add_listed_form(lx, form, w, ftags, SRC_WIKT_EN, F_WIKT_EN)
    for w, (modern, old) in entries.items():
        if modern:
            lx.flags[w] |= F_WIKT_EN
        elif old:
            lx.obsolete_word.add(w)
    log(f"Wikcionário-en: {n} entradas, {alt_n} remissões de grafia")


def da_headwords() -> set[str]:
    out = set()
    for _, row in iter_rows(CACHE / "da_data.sql.xz", {"word"}):
        if row[4] == 0:
            out.add(row[1].lower())
    return out


def mark_verbs(lx: Lexicon) -> None:
    """Bandeiras de verbo: infinitivos (lemas verbais) e formas verbais."""
    forms_per_lemma = collections.Counter()
    verbal_lemmas = set(w.lower() for w in lx.verb_words)
    for (form, lemma), (tags, src) in lx.pairs.items():
        forms_per_lemma[lemma] += 1
        if any(VERBAL & set(t.split()) for t in tags):
            verbal_lemmas.add(lemma.lower())
    for lemma, n in forms_per_lemma.items():
        if n >= 25 and re.search(r"(?:ar|er|ir|or|ôr)$", lemma):
            verbal_lemmas.add(lemma.lower())
    for (form, lemma) in lx.pairs:
        if lemma.lower() in verbal_lemmas:
            lx.flags[form] |= F_VERB_FORM
    for lemma in verbal_lemmas:
        lx.flags[lemma] |= F_VERB_LEMMA | F_VERB_FORM
    log(f"verbos: {len(verbal_lemmas)} lemas")


def build() -> None:
    check_disk()
    DATA.mkdir(exist_ok=True)
    lx = Lexicon()
    load_mechura(lx)
    load_wikt_pt(lx)
    load_wikt_en(lx)
    for w in FUNCTION_WORDS:
        lx.flags[w] |= F_FUNCTION
    mark_verbs(lx)

    # palavras só antigas saem do léxico moderno (o normalizador as moderniza)
    modern_attested = {w for w, f in lx.flags.items() if f & (F_MECHURA | F_WIKT_PT | F_WIKT_EN | F_FUNCTION)}
    obsolete_lemmas = {w for w in lx.obsolete_word if w not in modern_attested or w in lx.alt}
    obsolete_lemmas -= set(FUNCTION_WORDS)
    lemmas_of = collections.defaultdict(set)
    for (form, lemma) in lx.pairs:
        lemmas_of[form].add(lemma.lower())
    obsolete = set(obsolete_lemmas)
    strong = F_MECHURA | F_FUNCTION
    changed = True
    while changed:  # accusada -> accusado -> accusar (antigo): propaga até estabilizar
        changed = False
        for form, lemmas in lemmas_of.items():
            if form not in obsolete and lemmas <= obsolete and not (lx.flags.get(form, 0) & strong):
                obsolete.add(form)
                changed = True
    lex = {w: f for w, f in lx.flags.items() if w not in obsolete and " " not in w and f}
    log(f"léxico moderno: {len(lex)} palavras; grafias antigas: {len(obsolete)}")

    # verbetes do Dicionário Aberto sem "irmão" moderno de mesmo esqueleto entram no léxico
    _, s1i, _ = Normalizer.build_indexes(lex)
    added = 0
    for w in da_headwords():
        if w in lex or " " in w or w in lx.alt:
            continue
        if "-" not in w and s1i.get(skel1(w)) is not None:
            continue  # ex.: abacellar (já existe abacelar)
        lex[w] = F_DA_ONLY
        added += 1
    log(f"verbetes do Dicionário Aberto acrescentados ao léxico: {added}")

    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        DROP TABLE IF EXISTS forms; DROP TABLE IF EXISTS alt;
        DROP TABLE IF EXISTS lexicon_known; DROP TABLE IF EXISTS formfold;
        CREATE TABLE forms(form TEXT NOT NULL, lemma TEXT NOT NULL, tags TEXT, src INTEGER NOT NULL,
                           PRIMARY KEY(form, lemma)) WITHOUT ROWID;
        CREATE TABLE alt(old TEXT NOT NULL, modern TEXT NOT NULL, PRIMARY KEY(old, modern)) WITHOUT ROWID;
        CREATE TABLE lexicon_known(word TEXT PRIMARY KEY, flags INTEGER NOT NULL) WITHOUT ROWID;
        CREATE TABLE formfold(fold TEXT NOT NULL, form TEXT NOT NULL, PRIMARY KEY(fold, form)) WITHOUT ROWID;
        """
    )
    db.executemany(
        "INSERT INTO forms VALUES (?,?,?,?)",
        ((f, l, "|".join(sorted(t for t in tags if t)) or None, src) for (f, l), (tags, src) in lx.pairs.items()),
    )
    db.executemany("INSERT OR IGNORE INTO alt VALUES (?,?)",
                   ((o, m) for o, ms in lx.alt.items() for m in ms))
    db.executemany("INSERT INTO lexicon_known VALUES (?,?)", sorted(lex.items()))
    allforms = set(lex) | {f for f, _ in lx.pairs} | set(lx.alt)
    db.executemany("INSERT OR IGNORE INTO formfold VALUES (?,?)",
                   ((fold(w), w) for w in allforms if fold(w) != w))
    db.execute("CREATE INDEX forms_by_lemma ON forms(lemma)")
    db.commit()
    for t in ("forms", "alt", "lexicon_known", "formfold"):
        log(f"  {t}: {db.execute(f'SELECT count(*) FROM {t}').fetchone()[0]}")
    db.close()


def load_normalizer(db: sqlite3.Connection) -> Normalizer:
    lex = dict(db.execute("SELECT word, flags FROM lexicon_known"))
    alt = collections.defaultdict(list)
    for o, m in db.execute("SELECT old, modern FROM alt"):
        alt[o].append(m)
    return Normalizer(lex, alt)


if __name__ == "__main__":
    build()
