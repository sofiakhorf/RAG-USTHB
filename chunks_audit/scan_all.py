# -*- coding: utf-8 -*-
"""Scan mécanique des fichiers Chunks_family (contrôles C0,C5,C6,C7 + patterns spécifiques)."""
import json, re, unicodedata
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
OUT = BASE / "audit" / "chunks_audit"
OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    "B": "chunks_family_B.jsonl",
    "C-D": "chunks_family_C-D.jsonl",
    "E": "chunks_family_E.jsonl",
    "F": "chunks_famille_F.jsonl",
    "G": "chunks_family_g.jsonl",
    "H": "chunks_family_H.jsonl",
}

ARABIC = re.compile(r'[\u0600-\u06FF]')
DOTS = re.compile(r'[._\-–—]{8,}')
PAGENUM = re.compile(r'^\s*(page\s*)?\d{1,3}\s*$', re.I)
ISODATE = re.compile(r'\d{4}-\d{2}-\d{2}')
FLOAT0 = re.compile(r'\b\d+\.0\b')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
GLUE = re.compile(r'[A-Z]\d[A-Za-z0-9]*[A-Z]{2,}[a-z]|[A-Z]{2}[a-z]+[a-z][A-Z][a-z]+')

def norm(s):
    return unicodedata.normalize('NFKD', s or '').encode('ascii','ignore').decode().lower()

for fam, fname in FILES.items():
    lines = (BASE / "Chunks_family" / fname).read_text(encoding='utf-8').splitlines()
    chunks = [json.loads(l) for l in lines if l.strip()]
    rep = []
    A = rep.append
    A(f"FICHIER {fname}  —  {len(chunks)} chunks")

    # C0 family_type
    ft = Counter((c.get('metadata') or {}).get('family_type') for c in chunks)
    A(f"C0 family_type: {dict(ft)}")

    # C5 tailles
    sizes = [len(c.get('text','') or '') for c in chunks]
    small = [f"L{i+1}({s})" for i,s in enumerate(sizes) if s < 150]
    big = [f"L{i+1}({s})" for i,s in enumerate(sizes) if s > 6000]
    A(f"C5 tailles: min={min(sizes)} max={max(sizes)} moy={sum(sizes)//len(sizes)} | <150: {len(small)} {small[:8]} | >6000: {len(big)} {big[:8]}")

    # C6 bruit
    seen, dup = {}, []
    empty, dots_l, pagen, arab = [], Counter(), Counter(), []
    for i,c in enumerate(chunks):
        t = c.get('text','') or ''
        if not t.strip(): empty.append(f"L{i+1}")
        k = norm(t)[:400]
        if k in seen: dup.append(f"L{i+1}=L{seen[k]}")
        else: seen[k] = i+1
        if DOTS.search(t): dots_l[i+1] = len(DOTS.findall(t))
        for ln in t.splitlines():
            if PAGENUM.match(ln): pagen[i+1] += 1
        if ARABIC.search(t): arab.append(f"L{i+1}")
    A(f"C6 vides: {empty[:10]} | doublons norm: {len(dup)} {dup[:10]} | points/underscores>8: {len(dots_l)} chunks {dict(list(dots_l.items())[:6])} | lignes 'page N': {sum(pagen.values())} dans {len(pagen)} chunks | arabe: {len(arab)} {arab[:10]}")

    # C7 métadonnées
    keys = ["document_name","formation","niveau","semestre","ue","matiere","annee_universitaire","page","sheet_name","block_range","block_title","chapter","article_title","is_fallback"]
    fill = {}
    for k in keys:
        n = sum(1 for c in chunks if (c.get('metadata') or {}).get(k) not in (None,'',-1))
        fill[k] = f"{n}/{len(chunks)}"
    A(f"C7 remplissage: {fill}")
    dn = Counter((c.get('metadata') or {}).get('document_name') for c in chunks)
    A(f"C7 document_name ({len(dn)}): {dict(list(dn.items())[:12])}")
    fb = sum(1 for c in chunks if (c.get('metadata') or {}).get('is_fallback'))
    A(f"C7 is_fallback: {fb}/{len(chunks)}")

    # C1/C8 : premières lignes (fil d'Ariane)
    firsts = Counter((c.get('text','') or '').strip().splitlines()[0][:80] if (c.get('text','') or '').strip() else '' for c in chunks)
    A("C1/C8 premières lignes top12:")
    for l,n in firsts.most_common(12): A(f"    {n:4d}x | {l!r}")

    # patterns spécifiques
    pat = {
        "B": [r'Page \d', r'S OMMA', r'Algorithmique', r'Anglais', r'Théorie des Graphes', r'crédit', r'coefficient', r'coefficient'],
        "C-D": [r'Liste des Jurys', r'20232024', r'2023/2024', r'reconfirmer|reconduction', r'TekkoLab', r'Sujets Master', r'Sujets Licence', r'non renseign', r'Présences Sem', r'ADM\b', r'ADC\b', r'Version 01/10/2025', r'TP12[689]|ACAD', r'ISIL \d+', r'003/2024'],
        "E": [r'Semestre \d', r'[Ss]ession', r'[Rr]attrapage', r'AUDITORIUM', r'TMB\+DM1', r'ALGEBR', r'ISE1'],
        "F": [r'Arrêté n°', r'[Aa]rticle', r'[Cc]hapitre', r'\bVu\b'],
        "G": [r'Moyenne UE', r'Admis\(e\)', r'ajourn', r'Bilan', r'matricule'],
        "H": [r'Sat|Sun|Mon|Tue|Wed|Thu', r'PW|--', r'course', r'TP\.C', r'EL ?NAGGER', r'GUERROUMI', r'BOUALI', r'LAIDOUI', r'zeraoulia', r'ABDESSELAM'],
    }.get(fam, [])
    hits = {}
    for p in pat:
        rx = re.compile(p, re.I)
        ids = [i+1 for i,c in enumerate(chunks) if rx.search(c.get('text','') or '')]
        hits[p] = f"{len(ids)} {'L'+',L'.join(map(str,ids[:8])) if ids else '-'}"
    A(f"Patterns: {hits}")

    # spéciaux ciblés
    if fam == "C-D":
        iso = [i+1 for i,c in enumerate(chunks) if ISODATE.search(c.get('text','') or '')]
        fl = [i+1 for i,c in enumerate(chunks) if FLOAT0.search(c.get('text','') or '')]
        em = [i+1 for i,c in enumerate(chunks) if EMAIL.search(c.get('text','') or '')]
        A(f"Dates ISO (2025-06-01): {len(iso)} {iso[:10]} | floats '.0': {len(fl)} {fl[:10]} | emails: {len(em)} {em[:6]}")
        emex = [f"L{i+1}: {EMAIL.search(chunks[i]['text']).group(0)[:40]}" for i in (em[:3] and [em[0]-1]) or []]
        A(f"  email ex: {emex}")
        mk = [i+1 for i,c in enumerate(chunks) if re.search(r'[A-Z], ?[A-Z]{3,}', c.get('text','') or '')]
        A(f"Noms 'X,NOM' tronqués: {len(mk)} {mk[:8]}")
    if fam == "H":
        for i,c in enumerate(chunks):
            for m in set(GLUE.findall(c.get('text','') or '')):
                A(f"H glue L{i+1}: {m!r}")
    if fam == "G":
        dec = Counter()
        for c in chunks:
            for m in re.findall(r'Admis\(e\)[^,\n"]{0,30}', c.get('text','') or ''): dec[m.strip()[:40]] += 1
        A(f"G décisions: {dict(dec.most_common(8))}")

    (OUT / f"digest_{fam.replace('-','_')}.txt").write_text('\n'.join(rep), encoding='utf-8')
    print(f"OK {fam}: {len(chunks)} chunks -> digest_{fam}.txt")
