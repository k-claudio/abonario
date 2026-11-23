"""Resolução da busca: forma digitada -> lema(s), análise gramatical e termos de busca."""
from __future__ import annotations

from dataclasses import dataclass, field

from .db import Database
from .morph_pt import describe
from .textnorm import deaccent, fold, normalize_token

VERBAL = {"ind", "sub", "imp", "cond", "ger", "part", "pess", "inf"}


@dataclass
class Reading:
    lemma: str
    descriptions: list[str] = field(default_factory=list)
    is_headword: bool = False


@dataclass
class LookupResult:
    query: str
    form: str
    main: list[Reading] = field(default_factory=list)       # lema(s) principal(is)
    also: list[Reading] = field(default_factory=list)       # "também é forma de" / "ver também"
    via: str = ""                                           # como se chegou ao lema
    exact_terms: list[str] = field(default_factory=list)    # termos da aba "esta forma"
    suggestions: list[str] = field(default_factory=list)
    wildcard: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.main)


class Lookup:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- leituras de uma forma ---------------------------------------------------------
    def _readings(self, form: str) -> tuple[Reading | None, list[Reading]]:
        db = self.db
        head = None
        if db.is_headword(form):
            head = Reading(db.headword_lemma(form) or form, [], True)
        lemmas: dict[str, list[str]] = {}
        rows = db.lemmas_of(form)
        names = {l for l, _ in rows}
        for lemma, tags in rows:
            # lema que é só grafia antiga (far -> fazer) some quando o moderno também está presente
            moderns = db.alt_modern(lemma.lower())
            if moderns and any(m in names for m in moderns) and not db.in_mechura(lemma.lower()):
                continue
            lemmas.setdefault(lemma, []).extend(describe(tags))
        others = []
        for lemma, descs in lemmas.items():
            if head and lemma.lower() == form:
                head.descriptions.extend(descs)
                continue
            others.append(Reading(lemma, list(dict.fromkeys(descs)), db.is_headword(lemma)))
        return head, others

    def _nominal_form_of(self, a: str, b: str) -> bool:
        """`a` é flexão nominal (gênero/número) de `b`? (menina -> menino: sim; vir -> ver: não)."""
        rel = [t for l, t in self.db.lemmas_of(a.lower()) if l == b]
        if not rel:
            return False
        if any(t and VERBAL & set(t.replace("|", " ").split()) for t in rel):
            return False
        own = self.db.forms_of(a)
        return not any(t and VERBAL & set(t.replace("|", " ").split()) for _, t in own[:300])

    def _collapse(self, readings: list[Reading]) -> tuple[list[Reading], list[Reading]]:
        """meninas -> menino (principal) e menina (secundária, pois é feminino de menino)."""
        names = {r.lemma for r in readings}
        main, sec = [], []
        for r in readings:
            parent = any(self._nominal_form_of(r.lemma, other) for other in names - {r.lemma})
            (sec if parent else main).append(r)
        if not main:  # ciclo: mantém todos
            return readings, []
        main.sort(key=lambda r: (not r.is_headword, r.lemma))
        return main, sec

    def _from_form(self, form: str, res: LookupResult) -> bool:
        head, others = self._readings(form)
        if head:
            res.main = [head]
            res.also = others
            return True
        if others:
            res.main, res.also = self._collapse(others)
            return True
        return False

    # -- busca principal ------------------------------------------------------------------
    def resolve(self, query: str) -> LookupResult:
        q = query.strip()
        form = normalize_token(q)
        res = LookupResult(query=q, form=form, exact_terms=[form] if form else [])
        if not form:
            return res
        if any(c in q for c in "*?"):
            res.wildcard = self.db.headwords_glob(q.lower())
            return res
        db = self.db
        # grafia antiga registrada (pharmacia, elle, theatro): vai ao verbete moderno
        moderns = db.alt_modern(form)
        if moderns and not db.in_mechura(form):
            for cand in moderns:
                if self._from_form(cand.lower(), res):
                    res.via = f"grafia antiga de {cand}"
                    head, _ = self._readings(form)
                    if head:
                        res.also.insert(0, head)
                    return res
        if self._from_form(form, res):
            return res

        # grafia antiga / pronome átono (tabela de variantes do corpus)
        v = db.variant(form)
        if v:
            for cand in v.split(" ")[1:]:
                if cand != form and db.known_form(cand) and self._from_form(cand, res):
                    res.via = ("verbo com pronome átono: " if "-" in form else "grafia antiga de ") + cand
                    return res
        for cand in db.alt_modern(form):
            if self._from_form(cand.lower(), res):
                res.via = f"grafia antiga de {cand}"
                return res
        # pronome átono fora do corpus: fazê-lo, amá-la, dir-lhe-ia
        if "-" in form:
            parts = form.split("-")
            base = parts[0]
            cands = [deaccent(base) + "r", base + "r", base + "s", deaccent(base) + "z", base]
            if len(parts) >= 3:
                cands.insert(0, deaccent(base).rstrip("r") + "r" + parts[-1])
            for cand in cands:
                if db.known_form(cand) and self._from_form(cand, res):
                    res.via = f"verbo com pronome átono: {cand}"
                    return res
        # sem acentos: coracao -> coração
        f = fold(form)
        cands = list(dict.fromkeys(db.headwords_by_fold(f) + db.folded_forms(f)))
        if cands:
            mains, alsos = [], []
            for cand in cands:
                tmp = LookupResult(query=q, form=cand)
                if self._from_form(cand, tmp):
                    mains += tmp.main
                    alsos += tmp.also
            if mains:
                seen = set()
                mains = [r for r in mains if not (r.lemma in seen or seen.add(r.lemma))]
                # a palavra mais usual primeiro (coração antes de còração); as outras em "ver também"
                mains.sort(key=lambda r: (not db.in_mechura(r.lemma.lower()), not r.is_headword, r.lemma))
                res.main = mains[:1]
                res.also = mains[1:] + [r for r in alsos if r.lemma not in seen]
                res.via = "busca sem acentos"
                return res
        res.suggestions = db.headwords_prefix(form, 30)
        return res

    # -- formas de um lema ----------------------------------------------------------------
    def lemma_forms(self, lemma: str) -> list[tuple[str, str | None]]:
        """[(forma, etiquetas)] do lema, incluindo o próprio lema."""
        rows = list(self.db.forms_of(lemma))
        if lemma != lemma.lower():
            rows += self.db.forms_of(lemma.lower())
        seen, out = set(), []
        for f, tags in [(lemma.lower(), None)] + rows:
            if f in seen:
                if tags:
                    out = [(x, (t + "|" + tags) if t else tags) if x == f else (x, t) for x, t in out]
                continue
            seen.add(f)
            out.append((f, tags))
        return out
