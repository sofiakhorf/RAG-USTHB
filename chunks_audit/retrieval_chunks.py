# -*- coding: utf-8 -*-
"""Tests retrieval (Étape 3) : recherche des réponses attendues de la banque dans les chunks."""
import json, re
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
OUT = BASE / "audit" / "chunks_audit"

def load(fname):
    return [json.loads(l) for l in (BASE / "Chunks_family" / fname).read_text(encoding='utf-8').splitlines() if l.strip()]

def show(chunks, label, pattern, flags=re.I, maxn=12, ctx=140):
    rx = re.compile(pattern, flags)
    out = []
    for i, c in enumerate(chunks):
        t = c.get('text','') or ''
        m = rx.search(t)
        if m:
            s = max(0, m.start()-20)
            out.append(f"  L{i+1}: {t[s:s+ctx]!r}")
    print(f"[{label}] {len(out)} chunk(s)")
    for o in out[:maxn]: print(o)
    return out

R = [] ; P = print

# ---------------- FAMILLE B ----------------
B = load("chunks_family_B.jsonl")
P("========== FAMILLE B ==========")
show(B, "B-P1 ALGO3", r'ALGO3')
show(B, "B-P1bis algo3 crédits", r'ALGO3[^|]{0,200}')
show(B, "B-P2 A-NUM", r'A-NUM|Analyse [Nn]um')
show(B, "B-F anglais ISIL", r'Anglais')
show(B, "B-Piège Algorithmique (24 chunks déjà vus)", r'Algorithmique et structures')
show(B, "B-A semestre 4 TC", r'S4')
show(B, "B-SR Théorie des Graphes", r'Théorie des Graphes|GRAPHE?S? ?THEORIE', maxn=6)
P()

# ---------------- FAMILLE C ----------------
CD = load("chunks_family_C-D.jsonl")
P("========== FAMILLE C (dans C-D) ==========")
show(CD, "C-P1 promoteur 003/2024", r'003/2024', maxn=3)
show(CD, "C-P2 Biopharm", r'Biopharm', maxn=20)
show(CD, "C-P3 Zeon-soft", r'Zeon', maxn=20)
show(CD, "C-P4 Metro Alger", r'Metro', maxn=5)
show(CD, "C-P5 ISIL 021", r'ISIL 021', maxn=8)
show(CD, "C: promoteur vide", r'Promoteur\s*:\s*(\||$|\n)', maxn=6)
P()

# ---------------- FAMILLE D ----------------
P("========== FAMILLE D (dans C-D) ==========")
show(CD, "D-P1 ISIL 010", r'ISIL 010', maxn=8)
show(CD, "D-P3 02/06/2025 14:00", r'02/06/2025[^\n]{0,60}14', maxn=15)
show(CD, "D-P4 matricule", r'212131025548', maxn=3)
m2 = [i+1 for i,c in enumerate(CD) if 'M2 SSI' in ((c.get('metadata') or {}).get('document_name') or '')]
P(f"D-P5 M2 SSI chunks: {len(m2)}")
show(CD, "D: présence semaine", r'[Ss]emaine 3|[Ss]em 3|PR[EÉ]SENCE', maxn=5)
show(CD, "D-P7 ACAD", r'ACAD', maxn=8)
P()

# ---------------- FAMILLE E ----------------
E = load("chunks_family_E.jsonl")
P("========== FAMILLE E ==========")
for i,c in enumerate(E):
    t = (c.get('text','') or '')
    P(f"--- L{i+1} ({len(t)}c) ---")
    P(t[:2600])
P()

# ---------------- FAMILLE G ----------------
G = load("chunks_family_g.jsonl")
P("========== FAMILLE G ==========")
show(G, "G-P1 BOUDHAR", r'BOUDHAR', maxn=4)
show(G, "G-P2 BENAMAR", r'BENAMAR', maxn=4)
# moyennes >= 10 dans PV dette
det = [i+1 for i,c in enumerate(G) if 'dette' in ((c.get('metadata') or {}).get('document_name') or '').lower()]
P(f"G: chunks PV dette: {len(det)}")
cnt10 = []
for i,c in enumerate(G):
    if (i+1) in det:
        t = c.get('text','')
        ms = re.findall(r'moyenne de semestre\s*:?\s*([\d.]+)', t, re.I)
        if ms and any(float(x) >= 10 for x in ms): cnt10.append(f"L{i+1}({'/'.join(ms)})")
P(f"G-F1 moyenne sem >=10 (PV dette): {len(cnt10)} -> {cnt10}")
rr = [f"L{i+1}" for i,c in enumerate(G) if 'session rattrapage' in (c.get('text','') or '') and 'global' in ((c.get('metadata') or {}).get('document_name') or '')]
P(f"G-F2 admis session rattrapage (global): {len(rr)}")
show(G, "G-A1 GHOULA", r'GHOULA', maxn=3)
show(G, "G-A1 SAIDANI", r'SAIDANI', maxn=3)
show(G, "G-A2 totaux", r'total des étudiants|378|220', maxn=4)
show(G, "G-SR1 GUERGUADJ", r'GUERGUADJ', maxn=3)
show(G, "G: moyenne UE C00F0001S", r'C00F0001S|10\.28', maxn=4)
# échantillon chunk étudiant global
for i in (60, 200):
    P(f"--- G échantillon L{i+1} ---"); P(G[i]['text'][:500])
P()

# ---------------- FAMILLE H ----------------
H = load("chunks_family_H.jsonl")
P("========== FAMILLE H ==========")
P(H[0]['text'])
P()

# ---------------- FAMILLE F (échantillon) ----------------
F = load("chunks_famille_F.jsonl")
P("========== FAMILLE F échantillons ==========")
for i in (0, 1, 62, 74):
    P(f"--- L{i+1} ({len(F[i]['text'])}c) ---"); P(F[i]['text'][:400])
