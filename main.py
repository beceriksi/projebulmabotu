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

MIN_QUALITY_SCORE = 80       # 80 altı proje gelmesin
MIN_USER_SCORE = 80          
NEW_PROJECT_DAYS = 14        # QUALITY = Son 14 gün
USER_RECENT_DAYS = 30        # HYPE = Son 30 gün
MAX_SIGNALS_PER_RUN = 3

SENT_FILE = "sent.json"

TOP_VC = [
    "binance labs","a16z","jump","coinbase","okx","okx ventures",
    "paradigm","polychain","dragonfly","framework","hashkey","multicoin"
]

# =====================================
# SENT.JSON (Tekrar göndermeyi engelle)
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
# TOKEN FİLTRESİ
# =====================================

def has_token(proto):
    t = proto.get("tokenSymbol")
    return bool(t and isinstance(t, str) and len(t) > 0)

# =====================================
# KATEGORİ
# =====================================

def detect_category(proto):
    txt = ((proto.get("category") or "") + " " +
           (proto.get("name") or "")).lower()

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

    if tvl >= 50_000_000: score += 30
    elif tvl >= 10_000_000: score += 20
    elif tvl >= 1_000_000: score += 10

    if listed:
        age = (time.time() - listed) / 86400
        if age <= NEW_PROJECT_DAYS: score += 30
        elif age <= 30: score += 10

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
# VC RADAR (ListedAt filtresi yok)
# =====================================

def vc_radar(proto_index):
    data = jget(DEFILLAMA_RAISES)
    if not data:
        return []

    raises = data.get("raises", [])
    vc_list = []

    for r in raises:
        name = (r.get("project") or "")
        slug = name.lower()

        # Protokol varsa token kontrolü yap
        proto = proto_index.get(slug)
        if proto and has_token(proto):
            continue

        # Top-tier VC kontrolü
        investors = " ".join(
            i.get("name", "").lower()
            for i in r.get("investors", [])
        )

        if not any(vc in investors for vc in TOP_VC):
            continue

        vc_list.append(r)

    return vc_list[:3]


def format_vc_signal(r):
    name = r.get("project", "?")
    amount = r.get("amount", 0)
    date = r.get("date", 0)

    try:
        dt = datetime.utcfromtimestamp(date).strftime("%Y-%m-%d")
    except:
        dt = "?"

    investors = ", ".join(
        i.get("name", "?") for i in r.get("investors", [])
    )

    return (
        f"💰 [VC SIGNAL – TOP VC]\n\n"
        f"📛 Proje: {name}\n"
        f"🏦 Yatırımcılar: {investors}\n"
        f"💰 Raise: ${amount:,.0f}\n"
        f"📆 Tarih: {dt}\n\n"
        f"⏱ {now_utc()}"
    )


# =====================================
# MESAJ
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

    # Protokol index
    proto_index = {}
    for p in protocols:
        slug = (p.get("slug") or p.get("name") or "").lower()
        proto_index[slug] = p

    active_users = jget(DEFILLAMA_ACTIVE_USERS) or {}

    quality_list = []
    hype_list = []

    now_ts = time.time()

    # QUALITY + HYPE
    for p in protocols:
        name = p.get("name")
        if not name:
            continue

        # Tekrar gönderme
        if name in sent:
            continue

        # Token varsa at
        if has_token(p):
            continue

        # Yeni proje (QUALITY için)
        listed = p.get("listedAt") or 0
        if not listed:
            continue

        age = (now_ts - listed) / 86400

        # QUALITY radarı için 14 gün sınırı
        if age <= NEW_PROJECT_DAYS:
            q = score_quality(p)
            if q >= MIN_QUALITY_SCORE:
                quality_list.append((q, p))

        # HYPE radarı için 30 gün sınırı
        if age <= USER_RECENT_DAYS:
            slug = (p.get("slug") or "").lower()
            u = active_users.get(slug)
            h = score_user(p, u)
            if h >= MIN_USER_SCORE:
                hype_list.append((h, p))

    # Skorlara göre sırala
    quality_list.sort(reverse=True)
    hype_list.sort(reverse=True)

    sent_count = 0

    # VC RADARI (önce VC sinyali)
    vc_results = vc_radar(proto_index)
    for r in vc_results:
        name = r.get("project")
        if name in sent:
            continue

        telegram(format_vc_signal(r))
        sent.add(name)
        save_sent(sent)
        sent_count += 1
        time.sleep(1)

        if sent_count >= MAX_SIGNALS_PER_RUN:
            print("[*] Limit doldu.")
            return

    # QUALITY sinyalleri
    for score, proto in quality_list:
        if sent_count >= MAX_SIGNALS_PER_RUN:
            break

        name = proto.get("name")
        telegram(msg(proto, score))
        sent.add(name)
        save_sent(sent)
        sent_count += 1
        time.sleep(1)

    # HYPE sinyalleri
    for score, proto in hype_list:
        if sent_count >= MAX_SIGNALS_PER_RUN:
            break

        name = proto.get("name")
        telegram(msg(proto, score))
        sent.add(name)
        save_sent(sent)
        sent_count += 1
        time.sleep(1)

    print("[*] Gönderim tamamlandı.")

# =====================================
if __name__ == "__main__":
    run()
