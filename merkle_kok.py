"""EcoProve AI - aylik Merkle kokleri.
reliability_scores.csv -> merkle_roots.csv  (ay, root, count)
Gereken: pip install pandas pycryptodome"""
import random
import sys
import pandas as pd
from Crypto.Hash import keccak


def k(b):
    return keccak.new(digest_bits=256, data=b).digest()


def yaprak(r):
    return k(f"{r.date}|{r.source}|{r.tmean}|{r.score}|{r.status}".encode())


def katman(L):
    s = []
    for i in range(0, len(L), 2):
        if i + 1 == len(L):
            s.append(L[i])                                   # tek kalan yukari cikar
        else:
            s.append(k(min(L[i], L[i + 1]) + max(L[i], L[i + 1])))  # siralı cift (OpenZeppelin uyumlu)
    return s


def kok(L):
    while len(L) > 1:
        L = katman(L)
    return L[0]


def kanit(L, idx):
    p = []
    while len(L) > 1:
        e = idx ^ 1
        if e < len(L):
            p.append(L[e])
        L = katman(L)
        idx //= 2
    return p


def dogrula(y, p, root):
    h = y
    for e in p:
        h = k(min(h, e) + max(h, e))
    return h == root


# kullanım: python merkle_kok.py [girdi.csv] [cikti.csv]
GIRDI = sys.argv[1] if len(sys.argv) > 1 else "reliability_scores.csv"
CIKTI = sys.argv[2] if len(sys.argv) > 2 else "merkle_roots.csv"
d = pd.read_csv(GIRDI, keep_default_na=False)
d = d.sort_values(["date", "source"]).reset_index(drop=True)
d["ay"] = d.date.str[:7]

sonuc, ornek, ok = [], [], 0
for ay, g in d.groupby("ay"):
    yap = [yaprak(r) for r in g.itertuples()]
    root = kok(yap[:])
    sonuc.append((ay, "0x" + root.hex(), len(yap)))
    ornek += [(yap, i, root) for i in range(len(yap))]

for yap, i, root in random.Random(42).sample(ornek, 200):
    ok += dogrula(yap[i], kanit(yap, i), root)

pd.DataFrame(sonuc, columns=["ay", "root", "count"]).to_csv(CIKTI, index=False)
print(f"Kendi testi: {ok}/200 kanit dogru")
print("Ilk 3 kok:")
print(pd.DataFrame(sonuc[:3], columns=["ay", "root", "count"]).to_string(index=False))
print("Toplam ay:", len(sonuc))
