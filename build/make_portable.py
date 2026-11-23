"""Gera Abonario-portatil.zip (programa + banco + LEIA-ME) a partir da pasta instalada.

Uso:  python build/make_portable.py [pasta_instalada] [arquivo_zip]
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Abonario"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "Abonario-portatil.zip"
README = Path(__file__).resolve().parent / "LEIA-ME.txt"


def main() -> None:
    if not (SRC / "Abonario.exe").exists() or not (SRC / "abonario.db").exists():
        raise SystemExit(f"Programa instalado não encontrado em {SRC}")
    tmp = OUT.with_suffix(".part")
    files = sorted(p for p in SRC.rglob("*") if p.is_file())
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(README, "Abonario/LEIA-ME.txt")
        for i, p in enumerate(files, 1):
            z.write(p, "Abonario/" + p.relative_to(SRC).as_posix())
            if i % 200 == 0:
                print(f"  {i}/{len(files)} arquivos", flush=True)
    with zipfile.ZipFile(tmp) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit(f"Arquivo corrompido no zip: {bad}")
    tmp.replace(OUT)
    print(f"{OUT}  ({OUT.stat().st_size / 2**20:.0f} MB, {len(files) + 1} arquivos)")


if __name__ == "__main__":
    main()
