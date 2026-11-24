"""Painel de abonações: expressões com várias palavras e troca de busca."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_phrase_search_finds_exact_sequence(database):
    from app.ui import render
    words = ["de", "repente"]
    sents, _ = database.sentences(words, 0, 10, op="AND",
                                  accept=lambda t: render.contains_phrase(t, words, database.terms_for))
    assert sents, "deveria haver trechos com 'de repente'"
    for s in sents:
        assert render.phrase_spans(s.text, words, database.terms_for)
        assert '<span class="hl">' in render.highlight_phrase(s.text, words, database.terms_for)


def test_bad_match_expression_does_not_raise(database):
    # termo com espaço viraria "frase" no FTS5 (não suportado): deve só retornar vazio
    assert database.count_sentences(["macaco não"]) == 0
    assert database.sentences(["macaco não"], 0, 5) == ([], 0)


def test_expression_after_word_replaces_quotes(qt, database):
    """Bug relatado: buscar 'âmbar' e depois 'macaco não olha pro rabo' mantinha os trechos de âmbar."""
    from PySide6.QtCore import QThreadPool
    from app.ui.main_window import QuotesPanel
    panel = QuotesPanel(database)
    panel.set_queries("âmbar", "âmbar", ["âmbar", "âmbares"], "âmbar")
    QThreadPool.globalInstance().waitForDone()
    assert panel.exact.sents and panel.all.sents
    expr = "macaco não olha pro rabo"
    panel.set_queries(expr, expr, [expr], expr)
    QThreadPool.globalInstance().waitForDone()
    qt.processEvents()
    for lst in (panel.exact, panel.all):
        assert all("mbar" not in s.text for s in lst.sents.values())
        assert "mbar" not in lst.view.toPlainText()
    assert panel.exact.phrase == ["macaco", "não", "olha", "pro", "rabo"]
    assert not panel.tabs.isTabEnabled(1)
    assert "-1" not in panel.tabs.tabText(0)


def test_expression_with_quotes(qt, database):
    from PySide6.QtCore import QThreadPool
    from app.ui.main_window import QuotesPanel
    panel = QuotesPanel(database)
    panel.set_queries("de repente", "de repente", [], "de repente")
    QThreadPool.globalInstance().waitForDone()
    qt.processEvents()
    assert panel.exact.sents
    assert (panel.exact.total or 0) >= len(panel.exact.sents)
    assert panel.tabs.tabText(0).startswith("Esta expressão: de repente")
