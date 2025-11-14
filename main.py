import os, time, requests
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# === API kaynakları ===
DEFILLAMA_RAISES = "https://api.llama.fi/raises"
COINGECKO_NEW = "https://api.coinmarketcap.com/dexer/v1/coins/recent-listings"  # alternatif
NFT_ENDPOINT = "https://api.nftscan.com/api/v2/assets/new"  # basit örnek

# ==========================
# Yardımcı fonksiyonlar
# ==========================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def telegram(msg: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[WARN] TELEGRAM_TOKEN / CHAT_ID yok. Mesaj:")
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    try:
        requests.post(url, data=data, timeout=10)
    except:
        pass

def jget(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

# ==========================
# Kategori analiz fonksiyonu
# ==========================

def detect_category(text: str):
    t = text.lower()

    if any(x in t for x in ["layer1", "layer2", "l1", "l2", "modular", "rollup", "zk", "da"]):
        return "L1/L2"
    if any(x in t for x in ["dex", "perp", "perpetual", "swap", "trading"]):
        return "Perp/DEX"
    if any(x in t for x in ["defi", "amm", "lending", "yield", "staking"]):
        return "DeFi"
    if any(x in t for x in ["nft", "collection", "mint"]):
        return "NFT"
    if any(x in t for x in ["game", "gaming", "metaverse"]):
        return "Gaming"
    if any(x in t for x in ["ai", "ml", "data", "analytics"]):
        return "AI/Infra"

    return "General"

# ==========================
# VC Raises tarayıcı
# ==========================

def fetch_defillama_raises(days=7):
    data = jget(DEFILLAMA_RAISES)
    if not data:
        return []
    res = []
    now_ts = time.time()
    limit = days * 86400

    for r in data.get("raises", []):
        ts = r.get("date", 0)
        if ts and (now_ts - ts <= limit):
            res.append(r)
    return res

def score_raise(r):
    score = 0
    category = r.get("category", "") or ""
    amount = r.get("amount", 0) or 0
    investors = r.get("investors", []) or []

    # yatırım almış olmak
    score += 20

    if amount >= 5_000_000:
        score += 20
    elif amount >= 1_000_000:
        score += 10

    # yatırımcı kalitesi
    BIG_VC = ["binance", "okx", "jump", "a16z", "coinbase", "paradigm", "multicoin"]
    inames = " ".join([i.get("name","").lower() for i in investors])

    if any(vc in inames for vc in BIG_VC):
        score += 25

    strong = ["infrastructure", "layer", "defi", "perp", "dex", "nft", "game", "ai"]
    if any(x in category.lower() for x in strong):
        score += 15

    return score

# ==========================
# Token yeni liste tarama
# ==========================

def fetch_new_tokens():
    """
    Hem CMC hem CG varyantı gibi düşün – dummy örnek.
    """
    return []  # İstersen buraya gerçek CG/CEX API'leri bağlarız.

# ==========================
# NFT yeni proje tarama
# ==========================

def fetch_new_nft():
    data = jget(NFT_ENDPOINT)
    if not data:
        return []
    return data.get("data", [])[:10]  # ilk 10 yeterli

# ==========================
# Mesaj formatı
# ==========================

def format_raise_message(r, score):
    name = r.get("name", "Unknown")
    category_raw = r.get("category", "N/A")
    cat2 = detect_category(category_raw)
    amount = r.get("amount", 0)
    chain = r.get("chain", "N/A")
    investors = ", ".join([i.get("name","?") for i in (r.get("investors") or [])])

    return (
        f"🔥 [{cat2}] Early Radar Sinyali\n\n"
        f"📛 Proje: {name}\n"
        f"🏷 Kategori: {category_raw} ({cat2})\n"
        f"⛓ Ağ: {chain}\n"
        f"💰 Raise: ${amount:,.0f}\n"
        f"🤝 Yatırımcılar: {investors or 'Belirtilmemiş'}\n"
        f"🧠 Skor: {score}/100\n"
        f"⏱ {now_utc()}\n"
    )

# ==========================
# Ana radar fonksiyonu
# ==========================

def run_radar():
    found = False

    # 1) Raise analiz
    raises = fetch_defillama_raises(days=7)
    high = []
    for r in raises:
        s = score_raise(r)
        if s >= 70:
            high.append((s, r))

    high.sort(reverse=True, key=lambda x: x[0])

    for score, item in high[:5]:  # en iyi 5 proje
        telegram(format_raise_message(item, score))
        found = True
        time.sleep(1)

    # 2) NFT erken projeler (dummy)
    nfts = fetch_new_nft()
    for n in nfts:
        msg = f"🖼 [NFT] Yeni NFT Projesi Tespit Edildi\n\n📛 {n.get('asset_name')}\n⏱ {now_utc()}"
        telegram(msg)
        found = True
        break  # bir tane yeterli

    if not found:
        print("Bu turda sinyal yok.")

# ==========================
# Çalıştır
# ==========================

if __name__ == "__main__":
    print("[*] EARLY RADAR ÇALIŞTI:", now_utc())
    run_radar()
