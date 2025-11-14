import os
import time
import requests
from datetime import datetime, timezone

# ==========================
# AYARLAR
# ==========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# DÜZELTİLMİŞ API URL'LERİ (404 OLMAYANLAR)
DEFILLAMA_PROTOCOLS = "https://api.llama.fi/protocols"
DEFILLAMA_ACTIVE_USERS = "https://api.llama.fi/activeUsers"

NEW_PROJECT_DAYS = 14
USER_RECENT_DAYS = 30
MIN_QUALITY_SCORE = 70
MIN_USER_SCORE = 60
MAX_SIGNALS_PER_RUN = 6

# ==========================
# YARDIMCI
# ==========================

def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def jget(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        print(f"[WARN] {url} status {r.status_code}")
    except Exception as e:
        print(f"[ERR] {url}: {e}")
    return None

def telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[WARN] Token yok, mesaj console’a yazılıyor:")
        print(msg)
        print("-"*40)
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except:
        pass

# ==========================
# KATEGORİ TESPİTİ
# ==========================

def detect_category(proto):
    txt = ((proto.get("category") or "") + " " + (proto.get("name") or "")).lower()

    if any(x in txt for x in ["layer1","layer 1","l1","layer2","l2","rollup","zk","modular"]):
        return "L1/L2"
    if "perp" in txt or "futures" in txt:
        return "Perp/DEX"
    if "dex" in txt or "swap" in txt or "amm" in txt:
        return "DEX"
    if any(x in txt for x in ["defi","lending","borrow","yield"]):
        return "DeFi"
    if "nft" in txt or "collect" in txt:
        return "NFT"
    if "game" in txt:
        return "Gaming"
    if any(x in txt for x in ["ai","oracle","data","analytics"]):
        return "AI/Infra"

    return "General"

# ==========================
# PROTOCOL LİSTE / AKTİF KULLANICI
# ==========================

def fetch_protocols():
    data = jget(DEFILLAMA_PROTOCOLS)
    if not data:
        return []
    return data if isinstance(data, list) else data.get("protocols", [])

def fetch_active_users():
    data = jget(DEFILLAMA_ACTIVE_USERS)
    return data or {}

def build_proto_index(protocols):
    idx = {}
    for p in protocols:
        slug = p.get("slug") or p.get("name")
        if slug:
            idx[slug] = p
    return idx

# ==========================
# KALİTE SKORU
# ==========================

def score_quality(proto):
    score = 0
    tvl = proto.get("tvl") or 0
    category = detect_category(proto)
    chains = proto.get("chains") or []
    listed_at = proto.get("listedAt") or 0

    score += 10

    if category in ["L1/L2","Perp/DEX","DEX","DeFi","AI/Infra"]:
        score += 25
    elif category in ["NFT","Gaming"]:
        score += 15
    else:
        score += 5

    if tvl >= 50_000_000:
        score += 30
    elif tvl >= 10_000_000:
        score += 20
    elif tvl >= 1_000_000:
        score += 10

    if len(chains) >= 3:
        score += 15
    elif len(chains) == 2:
        score += 8

    if listed_at:
        age = (time.time() - listed_at) / 86400
        if age <= NEW_PROJECT_DAYS:
            score += 20
        elif age <= 30:
            score += 10

    return score

# ==========================
# KULLANICI SKORU
# ==========================

def score_user(proto, u):
    if not u:
        return 0

    score = 0
    users = (u.get("users") or {}).get("value") or 0
    new_users = (u.get("newUsers") or {}).get("value") or 0
    txs = (u.get("txs") or {}).get("value") or 0

    listed_at = proto.get("listedAt") or 0
    recent_bonus = 0
    if listed_at:
        age = (time.time() - listed_at) / 86400
        if age <= USER_RECENT_DAYS:
            recent_bonus = 10

    if users > 5000:
        score += 25
    elif users > 1000:
        score += 15
    elif users > 300:
        score += 8

    if new_users > 500:
        score += 25
    elif new_users > 100:
        score += 15
    elif new_users > 30:
        score += 8

    if txs > 20000:
        score += 20
    elif txs > 5000:
        score += 10
    elif txs > 1000:
        score += 5

    score += recent_bonus
    return score

# ==========================
# MESAJLAR
# ==========================

def msg_quality(proto, score):
    name = proto.get("name","Unknown")
    category = detect_category(proto)
    tvl = proto.get("tvl") or 0
    chains = proto.get("chains") or []
    listed = proto.get("listedAt") or 0

    age_txt = "bilinmiyor"
    if listed:
        age_txt = f"{int((time.time()-listed)/86400)} gün önce eklendi"

    return (
        f"🔥 [EARLY QUALITY]\n\n"
        f"📛 {name}\n"
        f"🏷 {category}\n"
        f"💰 TVL: ${tvl:,.0f}\n"
        f"⛓ Zincirler: {', '.join(chains)}\n"
        f"🧠 Skor: {score}/100\n"
        f"📆 {age_txt}\n"
        f"⏱ {now_utc_str()}"
    )

def msg_user(proto, score, u):
    name = proto.get("name","Unknown")
    category = detect_category(proto)
    tvl = proto.get("tvl") or 0

    users = (u.get("users") or {}).get("value") or 0
    new_users = (u.get("newUsers") or {}).get("value") or 0
    txs = (u.get("txs") or {}).get("value") or 0

    return (
        f"⚡ [USAGE/HYPE]\n\n"
        f"📛 {name}\n"
        f"🏷 {category}\n"
        f"👥 Aktif: {users}\n"
        f"🆕 Yeni kullanıcı: {new_users}\n"
        f"📨 İşlemler: {txs}\n"
        f"💰 TVL: ${tvl:,.0f}\n"
        f"🧠 Skor: {score}/100\n"
        f"⏱ {now_utc_str()}"
    )

# ==========================
# ANA ÇALIŞMA
# ==========================

def run_radar_once():
    print(f"[*] Radar çalışıyor: {now_utc_str()}")

    protocols = fetch_protocols()
    if not protocols:
        print("[ERR] Protokoller çekilemedi")
        return

    proto_index = build_proto_index(protocols)
    now_ts = time.time()

    # --- QUALITY ---
    q_list = []
    for p in protocols:
        listed = p.get("listedAt") or 0
        if not listed:
            continue
        age = (now_ts - listed) / 86400
        if age > NEW_PROJECT_DAYS:
            continue

        q = score_quality(p)
        if q >= MIN_QUALITY_SCORE:
            q_list.append((q,p))

    q_list.sort(reverse=True, key=lambda x: x[0])

    signals = 0
    for score, proto in q_list[:MAX_SIGNALS_PER_RUN]:
        telegram(msg_quality(proto, score))
        signals += 1
        time.sleep(1)

    # --- USER/HYPE ---
    active = fetch_active_users()
    u_list = []

    for slug, u_entry in active.items():
        proto = proto_index.get(slug)
        if not proto:
            continue

        listed = proto.get("listedAt") or 0
        if not listed:
            continue

        age = (now_ts - listed) / 86400
        if age > USER_RECENT_DAYS:
            continue

        us = score_user(proto, u_entry)
        if us >= MIN_USER_SCORE:
            u_list.append((us, proto, u_entry))

    u_list.sort(reverse=True, key=lambda x: x[0])

    remain = MAX_SIGNALS_PER_RUN - signals
    if remain > 0:
        for score, proto, u in u_list[:remain]:
            telegram(msg_user(proto, score, u))
            time.sleep(1)

    if signals == 0 and len(u_list) == 0:
        print("[*] Bu tur sinyal yok.")

# ==========================
if __name__ == "__main__":
    run_radar_once()
