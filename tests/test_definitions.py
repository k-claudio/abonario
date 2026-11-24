"""Busca nas definições (busca reversa), inclusive com a grafia antiga do Dicionário Aberto."""


def test_modern_query_finds_old_spelling_definitions(database):
    c = database.conn
    old_only = [k for (k,) in c.execute(
        "SELECT DISTINCT key FROM entries WHERE source=1 AND html LIKE '%cavallo%' AND html NOT LIKE '%cavalo%'")]
    assert old_only, "o Dicionário Aberto deveria ter definições com 'cavallo'"
    found = set(database.search_definitions("cavalo", limit=100000))
    assert "rifar" in found  # «...o cavallo... rifando...»
    assert sum(k in found for k in old_only) >= 5


def test_inflected_query_uses_base_form(database):
    assert "potro" in database.search_definitions("cavalos novos")
    assert "rifar" in database.search_definitions("rinchar")


def test_old_spelling_typed_by_user(database):
    modern = set(database.search_definitions("farmácia"))
    old = set(database.search_definitions("pharmacia"))
    assert old and modern <= old


def test_hyphen_query_and_truncation_notice(database):
    from app.ui import render
    assert database.search_definitions("guarda-chuva")
    keys = database.search_definitions("de", limit=300)
    assert len(keys) == 301
    assert "Mais de 300 verbetes" in render.definitions_html("de", keys)
