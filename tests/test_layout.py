"""Disposição: abonações embaixo do verbete ou ao lado (escolha de quem usa)."""
from PySide6.QtCore import QSettings, Qt


def test_switch_between_layouts(qt, database):
    from app.ui.main_window import MainWindow
    saved = QSettings("Abonario", "Abonario").value("layout")
    win = MainWindow(database)
    win.persist = False
    win.resize(1280, 860)
    win.navigate("fizéramos")
    body = win._entry_body

    win.set_layout("lado", save=False)
    assert win.split.orientation() == Qt.Horizontal
    assert win.split.widget(0) is win.entry and win.split.widget(1) is win.quotes  # verbete | abonações
    assert win.quotes._compact and win.quotes.title.text() == "Abonações"
    assert win.layout_actions["lado"].isChecked()
    assert win._entry_body == body  # o verbete aberto continua na tela
    assert all(s > 0 for s in win.split.sizes())

    win.set_layout("abaixo", save=False)
    assert win.split.orientation() == Qt.Vertical
    assert not win.quotes._compact and win.quotes.title.text().startswith("Abonações —")
    assert win.layout_actions["abaixo"].isChecked()
    assert win._entry_body == body

    # com persist=False nada é gravado nas preferências do usuário
    assert QSettings("Abonario", "Abonario").value("layout") == saved


def test_invalid_layout_falls_back(qt, database):
    from app.ui.main_window import MainWindow
    win = MainWindow(database)
    win.persist = False
    win.set_layout("diagonal", save=False)
    assert win.layout_mode == "abaixo"
    assert win.split.orientation() == Qt.Vertical
