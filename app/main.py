"""Ponto de entrada do Abonário.

Uso:  python -m app.main [--smoke "fizéramos;coubesse" --screenshot pasta/prefixo]
"""
from __future__ import annotations

import argparse
import gc
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .core.db import Database, find_db
from .ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--smoke", default="")
    ap.add_argument("--screenshot", default="")
    ap.add_argument("--theme", default="")
    ap.add_argument("--layout", default="")
    args, qt_args = ap.parse_known_args(argv if argv is not None else sys.argv[1:])

    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName("Abonário")
    app.setOrganizationName("Abonario")
    icon = Path(__file__).resolve().parent / "ui" / "abonario.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    if args.smoke:  # capturas de teste fora da tela: fixa a fonte padrão do Windows
        app.setFont(QFont("Segoe UI", 9))
    path = find_db()
    if path is None:
        QMessageBox.critical(None, "Abonário", "Banco de dados abonario.db não encontrado.\n"
                             "Ele deve ficar na mesma pasta do programa.")
        return 1
    db = Database(path)
    win = MainWindow(db)
    if args.smoke:
        win.persist = False
        win.resize(1280, 860)
    if args.theme:
        win.apply_theme(args.theme, save=False)
    if args.layout:
        win.set_layout(args.layout, save=False)
    win.show()

    # O coletor de lixo do Python pode rodar numa thread de contagem e destruir ali objetos
    # do Qt (o que derruba o programa). Ele passa a rodar só na thread principal, a cada 5 s;
    # os objetos permanentes (léxico, lista de verbetes) são congelados para a coleta ser rápida.
    gc.freeze()
    gc.disable()
    gc_timer = QTimer()
    gc_timer.timeout.connect(gc.collect)
    gc_timer.start(5000)

    if args.smoke:
        queries = [q for q in args.smoke.split(";") if q.strip()]
        state = {"i": 0}

        def step() -> None:
            i = state["i"]
            if i > 0 and args.screenshot:
                app.processEvents()
                win.grab().save(f"{args.screenshot}_{i}.png")
            if i < len(queries):
                win.search.setText(queries[i])
                win.navigate(queries[i])
                state["i"] = i + 1
                QTimer.singleShot(1500, step)
            else:
                app.quit()

        QTimer.singleShot(500, step)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
