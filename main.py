import os
import time
import requests
from datetime import datetime, timezone

# ==========================
# AYARLAR
# ==========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

DEFILLAMA_PROTOCOLS = "https://api.llama.fi/protocols"
DEFILLAMA_ACTIVE_USERS = "https://api.llama.fi/activeUsers"
DEFILLAMA_RAISES = "https://api.llama.fi/raises"

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
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
        print(f"[WARN] {url} status {r.status_code}")
    except Exception as e:
        print(f"[ERR] {url}: {e}")
    return None

def telegram(msg: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[WARN] Telegram bilgileri yok, mesaj console’a yazıldı:")
        print(msg)
        print("-"*40)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=15
        )
    except:
        pass

# ==========================
# TOKEN FİLTRESİ (A seçeneği)
# ==========================

def has_token(proto: dict) -> bool:
    t = proto.get("tokenSymbol")
    return bool(t and isinstance(t, str) and len(t) > 0)

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
    if "nft" in txt:
        return "NFT"
    if "game" in txt:
        return "Gaming"
    if any(x in txt for x in ["ai","oracle","data","analytics"]):
        return "AI/Infra"

    return "General"

# ==========================
# LİNK ÇIKARMA + ÖNERİ SİSTEMİ
# ==========================

def extract_links(proto):
    website = ""
    app = ""
    discord = ""

    # Website
    for k in ["url","website","site","homepage"]:
        if proto.get(k):
            website = proto.get(k)
            break

    # App link
    for k in ["appUrl","app","app_url","dapp"]:
        if proto.get(k):
            app = proto.get(k)
            break

    # Discord
    for k,v in proto.items():
        if isinstance(v, str) and "discord" in v.lower():
            discord = v
            break

    # Eğer website app içeriyorsa
    if not app and website and ("app." in website or "/app" in website):
        app = website

    return website, app, discord

def suggestion_text(proto):
    tvl = proto.get("tvl") or 0
    category = detect_category(proto).lower()

    if "dex" in category or "perp" in category or "defi" in category:
        if tvl < 5_000_000:
            return (
                "📝 Öneri:\n"
                "- App açılabiliyorsa 1 küçük işlem yap (5–10$ test amaçlı).\n"
                "- Bu tip erken DeFi projelerinde küçük hacim ileride points/airdrop avantajına dönüşebilir.\n"
                "- Discord’da OG/Early roller var mı kontrol et."
            )
        else:
            return (
                "📝 Öneri:\n"
                "- Website/App incele.\n"
                "- Points / Missions / Testnet bölümü açılmış mı bak.\n"
                "- Yoksa sadece takip et."
            )

    if "nft" in category or "game" in category:
        return (
            "📝 Öneri:\n"
            "- Discord’a gir.\n"
            "- OG / WL rollerine bak.\n"
            "- Mint yoksa takip et."
        )

    if "ai" in category or "infra" in category:
        return (
            "📝 Öneri:\n"
            "- Beta/Test signup açık mı kontrol et.\n"
            "- Bu tip projelerde erken kullanıcı olmak değerlidir."
        )

    return (
        "📝 Öneri:\n"
        "- Website/App kontrol et.\n"
        "- Testnet/points izleri varsa görev yap.\n"
        "- Yoksa izleme sinyali olarak değerlendir."
    )

# ==========================
# PROTOKOL / USER / VC VERİLERİ
# ==========================

def fetch_protocols():
    data = jget(DEFILLAMA_PROTOCOLS)
    return data if isinstance(data, list) else []

def fetch_active_users():
    return jget(DEFILLAMA_ACTIVE_USERS) or {}

def fetch_raises():
    data = jget(DEFILLAMA_RAISES)
    return data.get("raises", []) if data else []

def build_proto_index(protocols):
    idx = {}
    for p in protocols:
        slug = (p.get("slug") or p.get("name") or "").lower()
        idx[slug] = p
    return idx

# ==========================
# QUALITY SKORU
# ==========================

def score_quality(proto):
    score = 0
    tvl = proto.get("tvl") or 0
    chains = proto.get("chains") or []
    category = detect_category(proto)
    listed = proto.get("listedAt") or 0

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

    if listed:
        age = (time.time() - listed) / 86400
        if age <= NEW_PROJECT_DAYS:
            score += 20
        elif age <= 30:
            score += 10

    return score

# ==========================
# USER/HYPE
# ==========================

def score_user(proto, u):
    if not u:
        return 0

    score = 0
    users = (u.get("users") or {}).get("value") or 0
    new_users = (u.get("newUsers") or {}).get("value") or 0
    txs = (u.get("txs") or {}).get("value") or 0

    listed = proto.get("listedAt") or 0
    recent_bonus = 0
    if listed:
        age = (time.time() - listed) / 86400
        if age <= USER_RECENT_DAYS:
            recent_bonus = 10

    if users > 5000: score += 25
    elif users > 1000: score += 15
    elif users > 300: score += 8

    if new_users > 500: score += 25
    elif new_users > 100: score += 15
    elif new_users > 30: score += 8

    if txs > 20000: score += 20
    elif txs > 5000: score += 10
    elif txs > 1000: score += 5

    score += recent_bonus
    return score

# ==========================
# TOP VC RADARI
# ==========================

TOP_VC = [
    "binance labs","a16z","jump","coinbase","okx","okx ventures",
    "paradigm","polychain","dragonfly","framework","hashkey","multicoin"
]

def is_top_vc_in_raise(r):
    investors = r.get("investors", [])
    txt = " ".join([i.get("name","").lower() for i in investors])
    return any(vc in txt for vc in TOP_VC)

def score_vc_raise(r):
    score = 0
    amount = r.get("amount", 0)
    if amount >= 5_000_000: score += 40
    elif amount >= 1_000_000: score += 20

    investors = " ".join([i.get("name","").lower() for i in r.get("investors",[])])
    for vc in TOP_VC:
        if vc in investors:
            score += 20
    return score

def format_vc_signal(r):
    name = r.get("project", "?")
    amount = r.get("amount", 0)
    date = r.get("date", 0)
    dt = datetime.utcfromtimestamp(date).strftime("%Y-%m-%d")
    investors = ", ".join(i.get("name","?") for i in r.get("investors",[]))
    score = score_vc_raise(r)

    return (
        f"💰 [VC SIGNAL – TOP TIER]\n\n"
        f"📛 Proje: {name}\n"
        f"🏦 Yatırımcılar: {investors}\n"
        f"💰 Raise: ${amount:,.0f}\n"
        f"📆 Tarih: {dt}\n"
        f"🧠 VC Skoru: {score}/100\n\n"
        f"⏱ {now_utc_str()}"
    )

# ==========================
# MESAJ FORMATLAYICI
# ==========================

def msg_quality(proto, score):
    name = proto.get("name","Unknown")
    category = detect_category(proto)
    tvl = proto.get("tvl") or 0
    chains = proto.get("chains") or []
    listed = proto.get("listedAt") or 0
    website, app, discord = extract_links(proto)
    advice = suggestion_text(proto)

    age_txt = "bilinmiyor"
    if listed:
        age_txt = f"{int((time.time()-listed)/86400)} gün önce eklendi"

    msg = (
        f"🔥 [EARLY QUALITY]\n\n"
        f"📛 {name}\n"
        f"🏷 {category}\n"
        f"💰 TVV: ${tvl:,.0f}\n"
        f"⛓ Zincirler: {', '.join(chains)}\n"
        f"🧠 Skor: {score}/100\n"
        f"📆 {age_txt}\n\n"
    )

    if website: msg += f"🔗 Website: {website}\n"
    if app: msg += f"🔗 App: {app}\n"
    if discord: msg += f"💬 Discord: {discord}\n"

    msg += f"\n{advice}\n"
    msg += f"⏱ {now_utc_str()}"
    return msg

def msg_user(proto, score, u):
    name = proto.get("name","Unknown")
    category = detect_category(proto)
    tvl = proto.get("tvl") or 0
    website, app, discord = extract_links(proto)
    advice = suggestion_text(proto)

    users = (u.get("users") or {}).get("value") or 0
    new_users = (u.get("newUsers") or {}).get("value") or 0
    txs = (u.get("txs") or {}).get("value") or 0

    msg = (
        f"⚡ [USAGE/HYPE]\n\n"
        f"📛 {name}\n"
        f"🏷 {category}\n"
        f"👥 Aktif kullanıcı: {users}\n"
        f"🆕 Yeni kullanıcı: {new_users}\n"
        f"📨 İşlem sayısı: {txs}\n"
        f"💰 TVL: ${tvl:,.0f}\n"
        f"🧠 Skor: {score}/100\n\n"
    )

    if website: msg += f"🔗 Website: {website}\n"
    if app: msg += f"🔗 App: {app}\n"
    if discord: msg += f"💬 Discord: {discord}\n"

    msg += f"\n{advice}\n"
    msg += f"⏱ {now_utc_str()}"
    return msg

# ==========================
# RADAR
# ==========================

def run_radar_once():
    print(f"[*] Radar çalışıyor: {now_utc_str()}")

    # --- PROTOKOLLER ---
    protocols = fetch_protocols()
    if not protocols:
        print("[ERR] Protokoller alınamadı")
        return

    proto_index = build_proto_index(protocols)
    now_ts = time.time()

    # ====================
    # VC RADARI
    # ====================
    raises = fetch_raises()
    vc_list = []

    for r in raises:
        if not is_top_vc_in_raise(r):
            continue

        # Proje adı slug'a çevrilir
        slug = (r.get("project","") or "").lower()
        proto = proto_index.get(slug)

        if proto and has_token(proto):
            continue  # tokenı varsa at

        vc_list.append(r)

    vc_list = vc_list[:3]
    for r in vc_list:
        telegram(format_vc_signal(r))
        time.sleep(1)

    # ====================
    # QUALITY RADARI
    # ====================

    q_list = []
    for p in protocols:
        if has_token(p):
            continue

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

    # ====================
    # HYPE / USER RADARI
    # ====================

    active = fetch_active_users()
    u_list = []

    for slug, u_entry in active.items():
        proto = proto_index.get(slug)
        if not proto:
            continue

        if has_token(proto):
            continue

        listed = proto.get("listedAt") or 0
        if not listed:
            continue

        age = (now_ts - listed) / 86400
        if age > USER_RECENT_DAYS:
            continue

        u_score = score_user(proto, u_entry)
        if u_score >= MIN_USER_SCORE:
            u_list.append((u_score, proto, u_entry))

    u_list.sort(reverse=True, key=lambda x:x[0])

    remain = MAX_SIGNALS_PER_RUN - signals
    if remain > 0:
        for score, proto, u in u_list[:remain]:
            telegram(msg_user(proto, score, u))
            time.sleep(1)

    if signals == 0 and len(u_list) == 0 and len(vc_list) == 0:
        print("[*] Bu tur sinyal yok.")

# ==========================
if __name__ == "__main__":
    run_radar_once()
