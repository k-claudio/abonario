"""Tokenização e normalização de palavras portuguesas.

Usado na construção do índice (build/) e no aplicativo. Para cada palavra do texto
original, `Normalizer.analyze()` devolve os "termos de índice":

* a própria palavra em minúsculas;
* com pronome átono, o verbo restaurado e os pronomes (fazê-lo -> fazer + o;
  dir-lhe-ia -> diria + lhe; separal-os, da grafia antiga, -> separar + os);
* em grafia antiga, a(s) forma(s) moderna(s) (mettido -> metido, elles -> eles,
  fizeramos -> fizéramos, quasi -> quase).

O aplicativo não precisa do Normalizer completo: a construção grava numa tabela
(`variants`) o resultado de toda palavra do corpus cuja análise não é trivial.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable, Iterable

# ---------------------------------------------------------------------------
# Tokenização
# ---------------------------------------------------------------------------
_L = r"[^\W\d_]"
WORD_RE = re.compile(rf"{_L}+(?:['’]{_L}+|-{_L}+)*")
APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "´": "'"})


def tokenize(text: str) -> list[tuple[int, int, str]]:
    """Lista de (início, fim, palavra) do texto."""
    return [(m.start(), m.end(), m.group()) for m in WORD_RE.finditer(text)]


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def normalize_token(token: str) -> str:
    return token.lower().translate(APOSTROPHES).strip("-'")


# ---------------------------------------------------------------------------
# Dobra de acentos e "esqueletos" ortográficos
# ---------------------------------------------------------------------------
def _build_fold_table() -> dict[int, str]:
    tbl: dict[int, str] = {}
    for cp in range(0xC0, 0x250):
        ch = chr(cp)
        base = "".join(c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c))
        if base != ch and len(base) == 1:
            tbl[cp] = base.lower()
    tbl[0x17F] = "s"  # s longo (ſ) das edições antigas
    return tbl


_FOLD = _build_fold_table()


def fold(s: str) -> str:
    """Minúsculas sem acentos nem cedilha: 'Coração' -> 'coracao'."""
    return s.lower().translate(_FOLD)


def deaccent(s: str) -> str:
    return s.translate(_FOLD)


_SKEL1 = [
    (re.compile(r"ph"), "f"),
    (re.compile(r"th"), "t"),
    (re.compile(r"rh"), "r"),
    (re.compile(r"y"), "i"),
    (re.compile(r"(?<![cln])h"), ""),      # h mudo: hontem, sahir, comprehender
    (re.compile(r"sc(?=[ei])"), "c"),      # sciencia, scena
    (re.compile(r"c(?=[ct])"), ""),        # acto, acção (cç), accento
    (re.compile(r"p(?=[tc])"), ""),        # baptismo, escripto, excepção
    (re.compile(r"mn"), "n"),              # damno, somno
    (re.compile(r"gm"), "m"),              # augmento
    (re.compile(r"m(?=[^aeiou]|$)"), "n"), # prompto, emfim, comtudo
    (re.compile(r"z$"), "s"),              # portuguez, paiz, mez
    (re.compile(r"([a-z])\1+"), r"\1"),    # letras dobradas: elle, annos, mettido
]

_SKEL2 = [
    (re.compile(r"ch"), "k"),              # chimica/química, architecto/arquiteto
    (re.compile(r"qu(?=[ei])"), "k"),
    (re.compile(r"c(?=[aoulr])"), "k"),
    (re.compile(r"gn"), "n"),              # assignar, signal
    (re.compile(r"^ex(?=[^aeiou])"), "es"),# extranho, extrangeiro
    (re.compile(r"z"), "s"),               # cazamento
    (re.compile(r"ae"), "ai"),             # pae, sae, taes
    (re.compile(r"oe"), "oi"),             # heroe
    (re.compile(r"eo"), "eu"),             # chapeo, céo
    (re.compile(r"io$"), "iu"),            # partio, sentio
    (re.compile(r"ao$"), "an"),            # fizerão, amavão (o m final já virou n)
    (re.compile(r"^e(?=[^aeiou])"), "i"),  # edade, egreja, egual
    (re.compile(r"ea"), "ia"),             # creança
    (re.compile(r"i$"), "e"),              # quasi
    (re.compile(r"ou"), "oi"),             # dous, cousa
    (re.compile(r"([a-z])\1+"), r"\1"),
]


def skel1(word: str) -> str:
    s = fold(word)
    for rx, rep in _SKEL1:
        s = rx.sub(rep, s)
    return s


def skel2_from1(s1: str) -> str:
    s = s1
    for rx, rep in _SKEL2:
        s = rx.sub(rep, s)
    return s


def skel2(word: str) -> str:
    return skel2_from1(skel1(word))


# ---------------------------------------------------------------------------
# Pronomes átonos e grafias antigas frequentes
# ---------------------------------------------------------------------------
PRONOUNS = frozenset(
    "me te se lhe lhes nos vos o a os as lo la los las no na nas "
    "mo ma mos mas to ta tos tas lho lha lhos lhas vo".split()
)
L_PRONOUNS = frozenset("lo la los las".split())
OLD_L_TARGET = frozenset("o a os as".split())     # separal-os, fazel-o
PRONOUN_NORM = {"lo": "o", "la": "a", "los": "os", "las": "as"}
MESO_ENDINGS = {  # chave: terminação sem acento e sem h inicial (dir-lhe-hia)
    "ei": "ei", "as": "ás", "a": "á", "emos": "emos", "eis": "eis", "ao": "ão",
    "ia": "ia", "ias": "ias", "iamos": "íamos", "ieis": "íeis", "iam": "iam",
}
ELISIONS = {"d": "de", "n": "em", "m": "me", "t": "te", "s": "se", "l": "lhe", "qu": "que", "c": "com"}
VOWELS = set("aeiouáéíóúâêôãõàü")

# Grafias antigas muito frequentes que coincidem com outras palavras do léxico
# (o índice guarda as duas leituras).
OLD_EXTRA = {
    "ha": ["há"], "quiz": ["quis"], "quizer": ["quiser"], "cousa": ["coisa"],
    "cousas": ["coisas"], "dous": ["dois"], "quasi": ["quase"], "sae": ["sai"],
    "pae": ["pai"], "paes": ["pais"], "mae": ["mãe"], "maes": ["mães"],
    "á": ["à"], "ás": ["às"], "áquelle": ["àquele"], "áquella": ["àquela"],
}

SKIP_SKELETON_BELOW = 3  # palavras curtas demais: só dobra de acento

# bandeiras do léxico (lexicon_known.flags)
F_MECHURA, F_WIKT_PT, F_WIKT_EN, F_FUNCTION, F_DA_ONLY, F_VERB_FORM, F_VERB_LEMMA = 1, 2, 4, 8, 16, 32, 64
_SOURCES = F_MECHURA | F_WIKT_PT | F_WIKT_EN | F_FUNCTION


def attestation(flags: int) -> int:
    """Nº de fontes que atestam a palavra (o Dicionário Aberto sozinho conta 0)."""
    return bin(flags & _SOURCES).count("1") + (2 if flags & F_FUNCTION else 0)


def _syllables(w: str) -> int:
    return len(re.findall(r"[aeiou]+", deaccent(w)))


class Normalizer:
    """Analisador completo; exige o léxico moderno em memória (só na construção).

    `lex`: palavra moderna -> bandeiras (F_*).  `alt`: grafia antiga -> modernas.
    """

    def __init__(self, lex: dict[str, int], alt: dict[str, list[str]] | None = None) -> None:
        self.lex = lex
        self.alt: dict[str, list[str]] = {}
        for k, v in (alt or {}).items():
            self.alt[k.lower()] = list(dict.fromkeys(m.lower() for m in v if m.lower() != k.lower()))
        for k, v in OLD_EXTRA.items():
            cur = self.alt.setdefault(k, [])
            for m in v:
                if m not in cur:
                    cur.append(m)
        self.fold_idx, self.s1_idx, self.s2_idx = self.build_indexes(lex)
        self.memo: dict[str, list[str]] = {}

    # -- índices ------------------------------------------------------------
    @staticmethod
    def build_indexes(forms: Iterable[str]):
        fi: dict[str, object] = {}
        s1i: dict[str, object] = {}
        s2i: dict[str, object] = {}

        def add(d, k, f):
            cur = d.get(k)
            if cur is None:
                d[k] = f
            elif isinstance(cur, str):
                if cur != f:
                    d[k] = (cur, f)
            elif f not in cur and len(cur) < 16:
                d[k] = cur + (f,)

        for f in forms:
            if "-" in f or " " in f or "'" in f:
                continue
            add(fi, fold(f), f)
            k1 = skel1(f)
            add(s1i, k1, f)
            add(s2i, skel2_from1(k1), f)
        return fi, s1i, s2i

    @staticmethod
    def _get(d, k) -> tuple[str, ...]:
        v = d.get(k)
        if v is None:
            return ()
        return (v,) if isinstance(v, str) else v

    def fold_matches(self, w: str) -> tuple[str, ...]:
        return self._get(self.fold_idx, fold(w))

    # -- modernização ---------------------------------------------------------
    def _best(self, cands, max_cands: int) -> list[str] | None:
        """Prefere as formas atestadas por mais fontes; None se nenhuma é atestada."""
        cands = list(dict.fromkeys(cands))
        scored = [(attestation(self.lex.get(c, 0)), c) for c in cands]
        for threshold in (2, 1):
            top = [c for sc, c in scored if sc >= threshold]
            if top:
                return top[:max_cands] if len(top) <= max_cands else []
        return None

    def modernize(self, w: str, max_cands: int = 4) -> list[str]:
        """Formas modernas para uma palavra desconhecida (sem hífen/apóstrofo)."""
        tiers = [[f for f in self.fold_matches(w) if f != w]]
        if len(w) >= SKIP_SKELETON_BELOW:
            k1 = skel1(w)
            t1 = list(self._get(self.s1_idx, k1))
            t2 = list(self._get(self.s2_idx, skel2_from1(k1)))
            if w.endswith("io"):  # pretérito antigo: partio, sahio -> partiu, saiu
                k1b = skel1(w[:-1] + "u")
                t1 += [f for f in self._get(self.s1_idx, k1b) if f not in t1]
                t2 += [f for f in self._get(self.s2_idx, skel2_from1(k1b)) if f not in t2]
            tiers += [t1, t2]
        weak: list[str] | None = None
        for cands in tiers:
            if not cands:
                continue
            best = self._best(cands, max_cands)
            if best is not None:
                return best
            if weak is None:
                weak = cands
        return weak[:max_cands] if weak and len(weak) <= max_cands else []

    def analyze_simple(self, w: str) -> list[str]:
        f = self.lex.get(w)
        if f is not None:
            out = [w] + [m for m in self.alt.get(w, ()) if m != w]
            if attestation(f) <= 1:  # palavra pouco atestada (póde): junta as variantes de acento
                for c in self.fold_matches(w):
                    if c not in out and attestation(self.lex.get(c, 0)) >= 2:
                        out.append(c)
            return out
        out = [w] + self.alt.get(w, [])
        for m in self.modernize(w):
            if m not in out:
                out.append(m)
        return out

    # -- pronomes átonos --------------------------------------------------------
    def _verb_from_truncated(self, base: str) -> list[str]:
        """fazê -> fazer; amá -> amar; pô -> pôr; fê -> fez; fi -> fiz; fizemo -> fizemos."""
        fb = deaccent(base)
        mono = _syllables(fb) <= 1
        if fb.endswith("mo"):
            order = ("s", "r", "z")
        elif mono and fb.endswith("i"):
            order = ("z", "s", "r")
        elif mono and base[-1] in "áêô":
            order = ("r", "z", "s")
        else:
            order = ("r", "s", "z")
        for suf in order:
            want = F_VERB_LEMMA if suf == "r" else F_VERB_FORM
            exact = [c for c in dict.fromkeys((base + suf, fb + suf)) if self.lex.get(c, 0) & want]
            if exact:
                return exact[:1]
            near = [c for c in self.fold_matches(fb + suf) if self.lex.get(c, 0) & want]
            if near:
                return near
        return []

    def _clitic(self, t: str, parts: list[str]) -> list[str] | None:
        fparts = [fold(p) for p in parts]
        verb = parts[0]
        # mesóclise: dir-lhe-ia, far-se-á, amá-lo-ei, fal-o-ha (grafia antiga)
        if len(parts) >= 3:
            end = fparts[-1][1:] if fparts[-1].startswith("h") else fparts[-1]
            if end in MESO_ENDINGS and all(p in PRONOUNS for p in fparts[1:-1]):
                base = verb
                if base.endswith("l") and fparts[1] in OLD_L_TARGET:
                    base = base[:-1]
                stem = deaccent(base)
                if not stem.endswith("r"):
                    stem += "r"
                built = stem + MESO_ENDINGS[end]
                cands = [built] if self.lex.get(built, 0) & F_VERB_FORM else [
                    c for c in self.fold_matches(built) if self.lex.get(c, 0) & F_VERB_FORM]
                if cands:
                    return [t] + cands + [PRONOUN_NORM.get(p, p) for p in fparts[1:-1]]
        # ênclise: disse-lhe, fazê-lo, separal-os (grafia antiga)
        if len(parts) >= 2 and all(p in PRONOUNS for p in fparts[1:]):
            first = fparts[1]
            cands: list[str] = []
            if first in L_PRONOUNS and verb[-1] in VOWELS:
                cands = self._verb_from_truncated(verb)
            elif first in OLD_L_TARGET and verb.endswith("l") and len(verb) > 2 and verb[-2] in VOWELS:
                cands = self._verb_from_truncated(verb[:-1])
            if not cands:
                if verb in self.lex:
                    cands = [verb]
                else:
                    m = self.modernize(verb)
                    if m:
                        cands = [verb] + m
            if cands:
                return [t] + cands + [PRONOUN_NORM.get(p, p) for p in fparts[1:]]
        return None

    def analyze(self, token: str) -> list[str]:
        """Termos de índice para uma palavra do texto (com memória)."""
        t = normalize_token(token)
        r = self.memo.get(t)
        if r is not None:
            return r
        if not t:
            r = []
        elif "-" not in t and "'" not in t:
            r = self.analyze_simple(t)
        elif "'" in t:  # d'elle, n'uma, d'água, mãe-d'água
            r = [t] if t in self.lex else []
            r += self.alt.get(t, [])
            joined = t.replace("'", "")
            if "-" not in joined and (joined in self.lex or joined in self.alt or self.modernize(joined)):
                r += self.analyze_simple(joined)
            for piece in t.split("-"):
                if "'" in piece:
                    head, _, rest = piece.partition("'")
                    r.append(ELISIONS.get(head, head))
                    if rest:
                        r += self.analyze(rest)
                elif piece:
                    r += self.analyze(piece)
            if not r:
                r = [t]
        elif t in self.lex:
            r = [t] + self.alt.get(t, [])
            parts = t.split("-")
            if len(parts) == 2 and parts[1] == "de":  # há-de, hei-de, hão-de
                r += self.analyze(parts[0]) + ["de"]
        else:
            parts = [p for p in t.split("-") if p]
            r = self._clitic(t, parts) if len(parts) >= 2 else None
            if r is None:
                r = [t] + self.alt.get(t, [])
                for p in parts:
                    r += self.analyze(p)
        seen: set[str] = set()
        r = [x for x in r if not (x in seen or seen.add(x))]
        self.memo[t] = r
        return r

    def terms_for_text(self, text: str) -> list[str]:
        out: list[str] = []
        for w in WORD_RE.findall(text):
            out.extend(self.analyze(w))
        return out


def make_terms_lookup(variants_get: Callable[[str], str | None]) -> Callable[[str], list[str]]:
    """Versão leve para o aplicativo: usa a tabela `variants` gravada na construção."""

    cache: dict[str, list[str]] = {}

    def terms(token: str) -> list[str]:
        t = normalize_token(token)
        r = cache.get(t)
        if r is None:
            v = variants_get(t)
            r = v.split(" ") if v else [t]
            cache[t] = r
        return r

    return terms
