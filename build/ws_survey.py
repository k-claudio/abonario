"""Levantamento exploratório do dump do Wikisource (predefinições, categorias, nacionalidades)."""
import bz2
import collections
import re
import sys
import xml.etree.ElementTree as ET

from common import CACHE

TPL = re.compile(r"\{\{\s*([^|}\n<]+?)\s*(?=[|}])")
CAT = re.compile(r"\[\[\s*Categoria\s*:\s*([^\]|]+)")
tpl_main, tpl_page, cats, nat, galeria_keys, navegar_keys = (collections.Counter() for _ in range(6))
samples_gal = []
f = bz2.open(CACHE / "ptwikisource.xml.bz2", "rb")
for ev, el in ET.iterparse(f, events=("end",)):
    if not el.tag.endswith("}page"):
        continue
    ns = title = text = ""
    for sub in el:
        t = sub.tag.rsplit("}", 1)[-1]
        if t == "ns":
            ns = sub.text
        elif t == "title":
            title = sub.text or ""
        elif t == "revision":
            for r in sub:
                if r.tag.endswith("}text"):
                    text = r.text or ""
    if ns == "0":
        tpl_main.update(m.lower() for m in TPL.findall(text))
        cats.update(c.strip() for c in CAT.findall(text))
        m = re.search(r"\{\{\s*navegar(.*?)\}\}", text, re.S | re.I)
        if m:
            navegar_keys.update(k.strip().lower() for k in re.findall(r"\|\s*([^=|]+?)\s*=", m.group(1)))
    elif ns == "106":
        tpl_page.update(m.lower() for m in TPL.findall(text))
    elif ns == "102":
        m = re.search(r"nacionalidade\s*=\s*([^\n|]*)", text)
        if m:
            nat[m.group(1).strip()[:30]] += 1
    elif ns == "104":
        galeria_keys.update(k.strip() for k in re.findall(r"\n\|\s*([^=|\n]+?)\s*=", text))
        if len(samples_gal) < 2 and len(text) > 300:
            samples_gal.append((title, text[:1200]))
    el.clear()

out = sys.stdout
print("TEMPLATES MAIN", tpl_main.most_common(120), file=out)
print("TEMPLATES PAGE", tpl_page.most_common(160), file=out)
print("NAVEGAR KEYS", navegar_keys.most_common(30), file=out)
print("NACIONALIDADE", nat.most_common(40), file=out)
print("GALERIA KEYS", galeria_keys.most_common(40), file=out)
for t, x in samples_gal:
    print("=== GALERIA", t, "\n", x, file=out)
print("CATEGORIES", cats.most_common(400), file=out)
