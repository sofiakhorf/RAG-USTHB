# -*- coding: utf-8 -*-
"""Audit ciblé famille C-D sur chunks frais (état actuel du parser)."""
import json, re
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
chunks = [json.loads(l) for l in (BASE / "Chunks_family" / "chunks_family_C-D.jsonl").read_text(encoding='utf-8').splitlines() if l.strip()]
P = print

# C0
ft = Counter((c.get('metadata') or {}).get('family_type') for c in chunks)
P(f"C0 family_type: {dict(ft)}  | nb={len(chunks)}")

# C5
sizes = [len(c.get('text','') or '') for c in chunks]
small = [i+1 for i,s in enumerate(sizes) if s<150]; big=[i+1 for i,s in enumerate(sizes) if s>6000]
P(f"C5 min/max={min(sizes)}/{max(sizes)} | <150: {len(small)} | >6000: {len(big)} {big[:5]}")

# C6
seen={}; dup=[]
for i,c in enumerate(chunks):
    k=re.sub(r'\s+',' ',(c.get('text','') or '').lower())[:400]
    if k in seen: dup.append(f"L{i+1}=L{seen[k]}")
    else: seen[k]=i+1
P(f"C6 doublons: {len(dup)} {dup[:5]}")

# C7
dn = Counter((c.get('metadata') or {}).get('document_name') for c in chunks)
P(f"C7 document_name: {dict(dn)}")
an = Counter((c.get('metadata') or {}).get('annee_universitaire') for c in chunks)
P(f"C7 annee_universitaire: {dict(an)}")
P(f"C7 sheet_name top: {dict(Counter((c.get('metadata') or {}).get('sheet_name') for c in chunks).most_common(6))}")

# Spécifiques C
note = [i+1 for i,c in enumerate(chunks) if 'année passée' in (c.get('text','') or '')]
P(f"C-c note 'année passée...reconducion': {len(note)} chunks")
promo_nr = [i+1 for i,c in enumerate(chunks) if re.search(r'Promoteur:\s*non renseigné', c.get('text','') or '')]
P(f"C-c 'Promoteur: non renseigné': {len(promo_nr)} chunks {promo_nr[:8]}")
p003 = [(i+1, c['text']) for i,c in enumerate(chunks) if '003/2024' in (c.get('text','') or '')]
for i,t in p003: P(f"--- 003/2024 L{i}:\n{t}\n")
islil010 = [(i+1, c['text'][:300]) for i,c in enumerate(chunks) if 'ISIL 010' in (c.get('text','') or '')]
for i,t in islil010: P(f"--- ISIL 010 L{i}: {t!r}")
acad104 = [(i+1, c['text'][:220]) for i,c in enumerate(chunks) if 'ACAD 104' in (c.get('text','') or '')]
for i,t in acad104: P(f"--- ACAD 104 L{i}: {t!r}")
emails = [i+1 for i,c in enumerate(chunks) if 'Emails' in ((c.get('text','') or '')[:120]) or 'emails' in str((c.get('metadata') or {}).get('sheet_name') or '').lower()]
P(f"C-c feuille emails: {len(emails)} chunks {emails[:5]}")
if emails:
    i = emails[0]; P(f"--- email chunk L{i}:\n{chunks[i-1]['text'][:400]}")

# Zeon / Biopharm / Metro / ISIL 021
zeon23 = [i+1 for i,c in enumerate(chunks) if 'Zeon' in (c.get('text','') or '') and '2023/2024' in (c.get('text','') or '')]
zeon23b = [i+1 for i,c in enumerate(chunks) if 'Zeon' in (c.get('text','') or '') and '2023-2024' in (c.get('text','') or '')]
P(f"Zeon 2023/2024: {len(zeon23)} | Zeon 2023-2024: {len(zeon23b)}")
metro = [(i+1, c['text'][:200]) for i,c in enumerate(chunks) if "Metro d'Alger" in (c.get('text','') or '')]
for i,t in metro[:2]: P(f"--- Metro L{i}: {t!r}")
isil021 = [(i+1, c['text'][:200]) for i,c in enumerate(chunks) if 'ISIL 021' in (c.get('text','') or '')]
for i,t in isil021: P(f"--- ISIL 021 L{i}: {t!r}")

# Spécifiques D
iso_dates = [i+1 for i,c in enumerate(chunks) if re.search(r'\d{4}-\d{2}-\d{2}', c.get('text','') or '')]
fl0 = [i+1 for i,c in enumerate(chunks) if re.search(r'\b\d+\.0\b', c.get('text','') or '')]
P(f"D dates ISO: {len(iso_dates)} | floats .0: {len(fl0)}")
mat = [(i+1, c['text'][:200]) for i,c in enumerate(chunks) if '212131025548' in (c.get('text','') or '')]
for i,t in mat: P(f"--- matricule L{i}: {t!r}")
m2 = [c for c in chunks if 'M2 SSI' in str((c.get('metadata') or {}).get('document_name') or '')]
students = [c for c in m2 if re.search(r'Matricule:', c.get('text','') or '')]
P(f"D M2 SSI: {len(m2)} chunks dont {len(students)} étudiants")
d0206 = [i+1 for i,c in enumerate(chunks) if '02/06/2025' in (c.get('text','') or '') and re.search(r'14h', c.get('text','') or '')]
P(f"D 02/06/2025+14h: {len(d0206)} chunks {d0206[:10]}")
pres = [(i+1, c['text'][:160]) for i,c in enumerate(chunks) if re.search(r'Créneau:\s*8h30', c.get('text','') or '')]
P(f"D créneau '8h30' brut: {len(pres)} | ex: {pres[0][1] if pres else '-'}")
# échantillon planning bloc 2
b2 = [(i+1, c['text'][:300]) for i,c in enumerate(chunks) if 'Nouveau Bloc' in (c.get('text','') or '')]
P(f"D bloc 2 (Nouveau Bloc): {len(b2)} chunks")
if b2: P(f"--- ex L{b2[0][0]}: {b2[0][1]!r}")
