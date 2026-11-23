# Abonário

Dicionário da língua portuguesa para desktop (Windows), 100% offline, com abonações
de escritores brasileiros e portugueses e lematização de qualquer forma flexionada.

## Uso

Abra **Abonário** pelo Menu Iniciar ou pela Área de Trabalho e digite uma palavra ou forma:
`fizéramos`, `coubesse`, `meninas`, `dir-lhe-ia`, `pharmacia`, `coracao`, `*ção`.

- O verbete mostra a análise da forma (ex.: "1ª pessoa do plural do pretérito
  mais-que-perfeito do indicativo de **fazer**"), as definições do Dicionário Aberto e do
  Wikcionário, a conjugação e todas as formas encontradas nos textos.
- O painel de abonações tem duas abas: trechos com a forma pesquisada e trechos com
  todas as formas do lema. Filtros: Brasil/Portugal, autor, excluir formas ambíguas.
  "contexto" mostra as frases vizinhas; "copiar" copia o trecho com a referência.

## Reconstruir os dados (requer internet só nesta etapa)

```
py -3.12 -m venv .venv
.venv\Scripts\pip install PySide6-Essentials pyinstaller mwparserfromhell pytest
cd build
..\.venv\Scripts\python fetch.py            # baixa as fontes para cache/
..\.venv\Scripts\python build_lexicon.py    # formas -> lemas, grafias antigas
..\.venv\Scripts\python build_corpus.py     # Wikisource + Gutenberg -> trechos e índice
..\.venv\Scripts\python build_dictionary.py # Dicionário Aberto + Wikcionário
..\.venv\Scripts\python finalize.py         # VACUUM e relatório
cd ..
.venv\Scripts\python -m pytest -q
.venv\Scripts\pyinstaller --workpath cache\pyinstaller abonario.spec
powershell -ExecutionPolicy Bypass -File build\install.ps1
```

O `install.ps1` **move** o banco (`data\abonario.db`) para a pasta instalada
(`%LOCALAPPDATA%\Programs\Abonario`). Os testes encontram o banco lá automaticamente.
Para liberar espaço depois de instalar, podem ser apagadas as pastas `cache\` (fontes baixadas,
~300 MB) e `.venv\`; elas só são necessárias para reconstruir os dados.

## Estrutura

- `app/core/textnorm.py`: tokenização, pronomes átonos (fazê-lo, dir-lhe-ia, separal-os) e
  modernização da grafia antiga (mettido → metido, quasi → quase). É usado na construção do índice.
- `app/core/lookup.py`: resolve a busca (forma → lema, grafia antiga, sem acento, coringas).
- `app/core/db.py`: consultas somente leitura ao `abonario.db` (SQLite + FTS5).
- `app/ui/`: interface Qt Widgets (sem navegador embutido).
- `build/`: scripts de construção dos dados.

## Licença

O código do Abonário é software livre, distribuído sob a **GNU General Public License v3.0**
(arquivo [LICENSE](LICENSE)). Os dados embutidos no programa seguem as licenças de suas fontes,
listadas abaixo.

## Fontes e licenças

- Dicionário Aberto (Cândido de Figueiredo, 1913; ed. digital de Alberto Simões) — CC BY-SA 2.5 PT
- Wikcionário (pt) e Wiktionary (en), extrações de kaikki.org — CC BY-SA 4.0
- Lista de lematização do português, Michal Měchura — ODbL
- Projeto Gutenberg e Wikisource em português — textos em domínio público

O Aulete Digital não está incluído: é obra protegida, sem distribuição livre.
