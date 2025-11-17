import os
import time
import json
import requests
from datetime import datetime, timezone

# =====================================
# AYARLAR
# =====================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

DEFILLAMA_PROTOCOLS = "https://api.llama.fi/protocols"
DEFILLAMA_ACTIVE_USERS = "https://api.llama.fi/activeUsers"
DEFILLAMA_RAISES = "https://api.llama.fi/raises"

MIN_QUALITY_SCORE = 80       # ✔ 80 altı proje gelmesin
MIN_USER_SCORE = 80          # ✔ Usage sinyali de 80 altı gelmesin
NEW_PROJECT_DAYS = 14
USER_RECENT_DAYS = 30
MAX_SIGNALS_PER_RUN = 3      # ✔ günde max 3 güçlü sinyal yeter

SENT_FILE = "sent.json"

# =====================================
# SENT.JSON YÖNETİMİ (Tekrar Etmesin)
# =====================================

def load_sent():
    try:
        with open(SENT_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_sent(s):
    with open(SENT_FILE, "w") as f:
        json.dump(list(s), f)

# =====================================
# YARDIMCI
# =====================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def jget(url):
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[NO TG] " + msg)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except:
        pass

# =====================================
# TOKEN FİLTRESİ – Tokeni olanı sil
# =====================================

def has_token(proto):
    t = proto.get("tokenSymbol")
    return bool(t and isinstance(t, str) and len(t) > 0)

# =====================================
# KATEGORİ
# =====================================

def detect_category(proto):
    txt = ((proto.get("category") or "") + " " + (proto.get("name") or "")).lower()

    if any(x in txt for x in ["layer1","layer 1","l1","layer2","l2","rollup","zk"]):
        return "L1/L2"
    if "perp" in txt or "futures" in txt:
        return "Perp/DEX"
    if "dex" in txt or "swap" in txt or "amm" in txt:
        return "DEX"
    if any(x in txt for x in ["defi","lending","borrow","yield"]):
        return "DeFi"
    if "ai" in txt or "data" in txt or "oracle" in txt:
        return "AI/Infra"
    return "General"

# =====================================
# SKORLAR
# =====================================

def score_quality(p):
    score = 0
    tvl = p.get("tvl") or 0
    category = detect_category(p)
    listed = p.get("listedAt") or 0

    if category in ["L1/L2","Perp/DEX","DEX","DeFi","AI/Infra"]:
        score += 30
    if tvl >= 50_000_000:
        score += 30
    elif tvl >= 10_000_000:
        score += 20
    elif tvl >= 1_000_000:
        score += 10

    if listed:
        age = (time.time() - listed) / 86400
        if age <= 14:
            score += 30
        elif age <= 30:
            score += 10

    return score

def score_user(p, u):
    if not u:
        return 0

    score = 0
    users = (u.get("users") or {}).get("value") or 0
    new_users = (u.get("newUsers") or {}).get("value") or 0

    if users > 5000: score += 30
    elif users > 1000: score += 20

    if new_users > 300: score += 30
    elif new_users > 50: score += 15

    listed = p.get("listedAt") or 0
    if listed:
        age = (time.time() - listed) / 86400
        if age <= USER_RECENT_DAYS:
            score += 20

    return score

# =====================================
# MESAJ ŞABLONLARI
# =====================================

def msg(proto, score):
    name = proto.get("name")
    category = detect_category(proto)
    tvl = proto.get("tvl") or 0

    return (
        f"🔥 Yeni Sinyal (Skor: {score})\n\n"
        f"📛 {name}\n"
        f"🏷 {category}\n"
        f"💰 TVL: ${tvl:,.0f}\n"
        f"📆 Yeni proje\n\n"
        f"⏱ {now_utc()}"
    )

# =====================================
# RADAR
# =====================================

def run():
    print("[*] Çalışıyor:", now_utc())

    sent = load_sent()

    protocols = jget(DEFILLAMA_PROTOCOLS)
    if not protocols:
        print("Protokoller alınamadı.")
        return

    active_users = jget(DEFILLAMA_ACTIVE_USERS) or {}

    quality_list = []
    hype_list = []

    for p in protocols:
        name = p.get("name")
        if not name:
            continue

        # ✔ tekrar göndermeyi engelle
        if name in sent:
            continue

        # ✔ tokeni olanı sil
        if has_token(p):
            continue

        # ✔ listedAt kontrolü
        listed = p.get("listedAt") or 0
        if not listed:
            continue

        age = (time.time() - listed) / 86400
        if age > NEW_PROJECT_DAYS:
            continue

        # Quality skor
        q = score_quality(p)
        if q >= MIN_QUALITY_SCORE:
            quality_list.append((q, p))

        # Hype skor
        slug = (p.get("slug") or "").lower()
        u = active_users.get(slug)
        h = score_user(p, u)
        if h >= MIN_USER_SCORE:
            hype_list.append((h, p))

    # Sırala
    quality_list.sort(reverse=True)
    hype_list.sort(reverse=True)

    sent_this_run = 0

    # Önce quality gönder
    for score, proto in quality_list:
        if sent_this_run >= MAX_SIGNALS_PER_RUN:
            break
        name = proto.get("name")
        telegram(msg(proto, score))
        sent.add(name)
        save_sent(sent)
        sent_this_run += 1
        time.sleep(1)

    # Sonra hype gönder (yer kaldıysa)
    for score, proto in hype_list:
        if sent_this_run >= MAX_SIGNALS_PER_RUN:
            break
        name = proto.get("name")
        telegram(msg(proto, score))
        sent.add(name)
        save_sent(sent)
        sent_this_run += 1
        time.sleep(1)

    print("[*] Gönderim tamamlandı.")

# =====================================

if __name__ == "__main__":
    run()
