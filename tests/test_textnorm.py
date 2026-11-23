"""Normalizador: tokenização, pronomes átonos e grafia antiga."""
import pytest

from app.core.textnorm import (F_MECHURA, F_VERB_FORM, F_VERB_LEMMA, F_WIKT_EN, Normalizer, fold,
                               skel1, skel2, tokenize)


def test_fold_and_skeletons():
    assert fold("Coração") == "coracao"
    assert skel1("mettido") == skel1("metido")
    assert skel1("pharmacia") == skel1("farmácia")
    assert skel2("quasi") == skel2("quase")
    assert skel2("pae") == skel2("pai")
    assert skel2("amavão") == skel2("amavam")


def test_tokenize_keeps_clitics_and_apostrophes():
    toks = [t for _, _, t in tokenize("Disse-lhe d'elle: fazê-lo-ia _já_!")]
    assert toks == ["Disse-lhe", "d'elle", "fazê-lo-ia", "já"]


def test_small_lexicon_clitics():
    v = F_MECHURA | F_WIKT_EN | F_VERB_FORM
    lex = {"fazer": v | F_VERB_LEMMA, "faz": v, "fez": v, "fiz": v, "diria": v, "dizer": v | F_VERB_LEMMA,
           "lhe": F_MECHURA | F_WIKT_EN, "o": F_MECHURA | F_WIKT_EN, "por": F_MECHURA | F_WIKT_EN,
           "pôr": v | F_VERB_LEMMA, "separar": v | F_VERB_LEMMA, "os": F_MECHURA | F_WIKT_EN}
    n = Normalizer(lex, {})
    assert "fazer" in n.analyze("fazê-lo")
    assert "fez" in n.analyze("fê-lo")
    assert "fiz" in n.analyze("fil-o")
    assert "pôr" in n.analyze("pol-o") and "por" not in n.analyze("pol-o")
    assert "diria" in n.analyze("dir-lhe-ia")
    assert "separar" in n.analyze("separal-os")


REAL_CASES = {
    "fizeramos": "fizéramos", "fazê-lo": "fazer", "dir-lhe-ia": "diria", "far-se-á": "fará",
    "amá-lo-ei": "amarei", "separal-os": "separar", "fil-o": "fiz", "fê-lo": "fez", "pol-o": "pôr",
    "mettido": "metido", "quasi": "quase", "pae": "pai", "elles": "eles", "annos": "anos",
    "difficuldade": "dificuldade", "hontem": "ontem", "sahir": "sair", "partio": "partiu",
    "amavão": "amavam", "fizerão": "fizeram", "pharmacia": "farmácia", "theatro": "teatro",
    "portuguez": "português", "sciencia": "ciência", "acção": "ação", "chimica": "química",
    "architecto": "arquiteto", "extranho": "estranho", "hymno": "hino", "d'elle": "dele",
    "n'uma": "numa", "ha": "há", "á": "à", "quiz": "quis", "tambem": "também",
}


@pytest.mark.parametrize("old,modern", sorted(REAL_CASES.items()))
def test_real_lexicon(normalizer, old, modern):
    assert modern in normalizer.analyze(old)


def test_known_words_untouched(normalizer):
    for w in ("casa", "fazer", "coração", "menino", "também"):
        assert normalizer.analyze(w)[0] == w
