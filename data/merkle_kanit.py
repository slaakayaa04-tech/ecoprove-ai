"""EcoProve AI - Merkle kanıt dosyası
Her kayıt için "bu kayıt şu ayın köküne aittir" kanıtını (Merkle proof) bir dosyaya yazar.
Sıla'nın backend'i ve doğrulama ekranı bu dosyayı okuyup kaydı zincirdeki kökle karşılaştırır.

Kullanım (en basit): python merkle_kanit.py
  Sadece reliability_scores_v1.csv gerekir. Kökleri kendisi hesaplar, merkle_roots_v1.csv ve
  merkle_kanitlari_v1.csv dosyalarını yazar.
İsteğe bağlı: python merkle_kanit.py reliability_scores_v1.csv [karsilastirilacak_kok_dosyasi.csv] [cikti.csv]
  İkinci dosya verilirse hesaplanan kökler onunla karşılaştırılır (uyuşmazlık uyarı olarak yazılır, program durmaz).
Gereken: pip install pandas pycryptodome

DOĞRULAMA KURALI (backend/dashboard için):
  1) yaprak  = keccak256( leaf_text'in UTF-8 baytları )       <- leaf_text dosyada hazır, yeniden üretmeyin
  2) her kanıt hash'i için: h = keccak256( min(h, e) + max(h, e) )   (iki hash bayt olarak küçükten büyüğe sıralanır)
  3) sonuç, zincirdeki o ayın köküne (getRoot) eşitse kayıt değişmemiştir.
"""
import sys
import pandas as pd
from Crypto.Hash import keccak

GIRDI = sys.argv[1] if len(sys.argv) > 1 else "reliability_scores_v1.csv"
KARSILASTIR = sys.argv[2] if len(sys.argv) > 2 else None
CIKTI = sys.argv[3] if len(sys.argv) > 3 else "merkle_kanitlari_v1.csv"
KOK_CIKTI = "merkle_roots_v1.csv"


def k(b):
    return keccak.new(digest_bits=256, data=b).digest()


def katman(L):
    s = []
    for i in range(0, len(L), 2):
        if i + 1 == len(L):
            s.append(L[i])
        else:
            s.append(k(min(L[i], L[i + 1]) + max(L[i], L[i + 1])))
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


def dogrula(leaf_text, proof_hex, root_hex):
    """Tek bir kaydı dışarıdan doğrular. proof_hex: '0x..;0x..' biçiminde metin."""
    h = k(leaf_text.encode("utf-8"))
    for e in [bytes.fromhex(x[2:]) for x in proof_hex.split(";") if x]:
        h = k(min(h, e) + max(h, e))
    return "0x" + h.hex() == root_hex


def yaprak_metni(r):
    return f"{r.date}|{r.source}|{r.tmean}|{r.score}|{r.status}"


if __name__ == "__main__":
    d = pd.read_csv(GIRDI, keep_default_na=False)
    d = d.sort_values(["date", "source"]).reset_index(drop=True)
    d["ay"] = d.date.str[:7]

    satirlar, kokler = [], []
    for ay, g in d.groupby("ay"):
        metinler = [yaprak_metni(r) for r in g.itertuples()]
        yaprak = [k(m.encode("utf-8")) for m in metinler]
        root = "0x" + kok(yaprak[:]).hex()
        kokler.append((ay, root, len(yaprak)))
        for i, r in enumerate(g.itertuples()):
            satirlar.append((r.date, r.source, ay, metinler[i], "0x" + yaprak[i].hex(),
                             ";".join("0x" + e.hex() for e in kanit(yaprak, i)), root))
    out = pd.DataFrame(satirlar, columns=["date", "source", "ay", "leaf_text", "leaf_hash", "proof", "root"])
    out.to_csv(CIKTI, index=False)
    pd.DataFrame(kokler, columns=["ay", "root", "count"]).to_csv(KOK_CIKTI, index=False)

    print(f"Girdi: {GIRDI}  |  {len(out)} kayıt, {len(kokler)} ay")
    print(f"Yazıldı: {KOK_CIKTI} ve {CIKTI}")
    print(f"2023-01 kökü: {kokler[0][1]}  (kayıt sayısı {kokler[0][2]})")

    if KARSILASTIR:
        try:
            beklenen = pd.read_csv(KARSILASTIR).set_index("ay").root.to_dict()
            uyusmayan = [ay for ay, r, _ in kokler if beklenen.get(ay) != r]
            if uyusmayan:
                print(f"\nUYARI: {KARSILASTIR} ile {len(uyusmayan)}/{len(kokler)} ayın kökü uyuşmuyor ({', '.join(uyusmayan[:3])}...).")
                print("  Bu dosya reliability_scores_v1.csv ile aynı çalıştırmadan çıkmamış olabilir (ör. eski prototip).")
                print("  Zincire yazılan köklerle karşılaştırmak için Sıla'nın yazdığı kökleri kullanın.")
            else:
                print(f"\nKök kontrolü: tüm aylar {KARSILASTIR} ile birebir aynı")
        except Exception as e:
            print(f"\nUYARI: {KARSILASTIR} okunamadı ({e}). Karşılaştırma atlandı.")

    ok = sum(dogrula(r.leaf_text, r.proof, r.root) for r in out.itertuples())
    print(f"\nDoğrulama: {ok}/{len(out)} kayıt kanıtıyla doğru")

    # bozulmuş kayıt testi: skoru elle değiştir, doğrulama başarısız olmalı
    r = out.iloc[0]
    sahte_metin = r.leaf_text.rsplit("|", 2)[0] + "|99|Trusted"
    print("\nBozulmuş kayıt testi:")
    print(f"  orijinal : {r.leaf_text}  -> {'DOĞRU' if dogrula(r.leaf_text, r.proof, r.root) else 'UYUŞMUYOR'}")
    print(f"  değişmiş : {sahte_metin}  -> {'DOĞRU' if dogrula(sahte_metin, r.proof, r.root) else 'UYUŞMUYOR (beklenen)'}")
