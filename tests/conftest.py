import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))

# banco: variável ABONARIO_DB, pasta data/ do projeto ou a instalação do usuário
_candidates = [os.environ.get("ABONARIO_DB"), ROOT / "data" / "abonario.db",
               Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Abonario" / "abonario.db"]
DB = next((Path(c) for c in _candidates if c and Path(c).exists()), ROOT / "data" / "abonario.db")
BUILD_LEX = ROOT / "cache" / "build_lexicon.db"


@pytest.fixture(scope="session")
def normalizer():
    """Normalizador com o léxico real (do banco principal ou da cópia de construção)."""
    from build_lexicon import load_normalizer
    for path in (DB, BUILD_LEX):
        if path.exists():
            con = sqlite3.connect(path)
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='lexicon_known'").fetchone():
                return load_normalizer(con)
    pytest.skip("léxico não construído")


@pytest.fixture(scope="session")
def database():
    from app.core.db import Database
    if not DB.exists():
        pytest.skip("banco não construído")
    return Database(DB)


@pytest.fixture(scope="session")
def qapp():
    """QApplication fora da tela; como no app, a coleta de lixo roda só na thread principal."""
    import gc
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    gc.disable()
    yield app
    gc.collect()
    gc.enable()


@pytest.fixture
def qt(qapp):
    """Para testes com widgets: coleta o lixo na thread principal ao fim de cada teste."""
    yield qapp
    import gc
    gc.collect()


@pytest.fixture(scope="session")
def lookup(database):
    from app.core.lookup import Lookup
    return Lookup(database)
