"""Busca: forma flexionada -> lema, e trechos no corpus."""
import pytest


def lemmas(res):
    return [r.lemma for r in res.main]


@pytest.mark.parametrize("form,lemma", [
    ("fizéramos", "fazer"), ("coubesse", "caber"), ("meninas", "menino"), ("trouxeram", "trazer"),
    ("pudéssemos", "poder"), ("cães", "cão"), ("fazê-lo", "fazer"), ("dir-lhe-ia", "dizer"),
    ("pharmacia", "farmácia"), ("coracao", "coração"), ("elle", "ele"),
])
def test_form_to_lemma(lookup, form, lemma):
    res = lookup.resolve(form)
    assert lemma in lemmas(res), (form, lemmas(res), res.via)


def test_meninas_keeps_menina_as_secondary(lookup):
    res = lookup.resolve("meninas")
    assert lemmas(res)[0] == "menino"
    assert "menina" in [r.lemma for r in res.also]


def test_ambiguous_form(lookup):
    res = lookup.resolve("vimos")
    assert {"ver", "vir"} <= set(lemmas(res))


def test_analysis_text(lookup):
    res = lookup.resolve("fizéramos")
    d = " ".join(res.main[0].descriptions)
    assert "mais-que-perfeito" in d and "plural" in d


def test_headword_also_form(lookup):
    res = lookup.resolve("fora")
    assert res.main[0].is_headword
    assert {"ser", "ir"} <= {r.lemma for r in res.also}


def test_quotes_for_form_and_lemma(database, lookup):
    res = lookup.resolve("fizéramos")
    forms = [f for f, _ in lookup.lemma_forms("fazer")]
    sents, _ = database.sentences(forms, 0, 10)
    assert len(sents) == 10
    assert database.count_sentences(forms) > 1000
    exact, _ = database.sentences([res.form], 0, 5)
    assert exact, "deveria haver trechos com 'fizéramos' (ou 'fizeramos' em grafia antiga)"
    hl = database.terms_for
    assert any("fizéramos" in hl(w) for s in exact for w in s.text.replace(",", " ").split())


def test_country_filter(database, lookup):
    forms = [f for f, _ in lookup.lemma_forms("caber")]
    br, _ = database.sentences(forms, 0, 5, country="BR")
    pt, _ = database.sentences(forms, 0, 5, country="PT")
    assert br and all(s.work.country == "BR" for s in br)
    assert pt and all(s.work.country == "PT" for s in pt)
