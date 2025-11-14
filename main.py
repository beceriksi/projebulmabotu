import os
import time
import requests
from datetime import datetime, timezone

# ==========================
# AYARLAR
# ==========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# DefiLlama free API base
DEFILLAMA_BASE = "https://pro-api.llama.fi"

# Radar parametreleri
NEW_PROJECT_DAYS = 14      # son X günde eklenen protokoller "erken"
USER_RECENT_DAYS = 30      # kullanıcı metriği için "yeni sayılan" protokoller
MIN_QUALITY_SCORE = 70     # kaliteli proje eşiği
MIN_USER_SCORE = 60        # kullanıcı/hype skoru eşiği
MAX_SIGNALS_PER_RUN = 6    # tek seferde en fazla kaç sinyal yollansın


# ==========================
# YARDIMCI FONKSİYONLAR
# ==========================

def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def jget(url: str, params: dict | None = None):
    """Basit GET + JSON wrapper."""
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"[WARN] {url} status {r.status_code}")
    except Exception as e:
        print(f"[ERROR] GET {url}: {e}")
    return None


def telegram(msg: str):
    """Telegram’a text gönder."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[WARN] TELEGRAM_TOKEN veya CHAT_ID yok. Mesaj sadece console’a yazılıyor:")
        print(msg)
        print("-" * 40)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"[ERROR] Telegram gönderim hatası: {e}")


# ==========================
# KATEGORİ TESPİTİ
# ==========================

def detect_category(proto: dict) -> str:
    """
    Protokolün metinsel bilgisine göre kaba kategori çıkar.
    Hem DefiLlama 'category' alanını hem de açıklama / isimleri kullanıyoruz.
    """
    cat_raw = (proto.get("category") or "") + " " + (proto.get("name") or "")
    cat = cat_raw.lower()

    if any(x in cat for x in ["layer1", "layer 1", "l1", "base layer", "l2", "layer2", "rollup", "zk", "modular"]):
        return "L1/L2"
    if any(x in cat for x in ["perp", "perpetual", "perps", "futures"]):
        return "Perp/DEX"
    if any(x in cat for x in ["dex", "swap", "amm"]):
        return "DEX"
    if any(x in cat for x in ["defi", "lending", "borrow", "money market", "yield"]):
        return "DeFi"
    if any(x in cat for x in ["nft", "marketplace", "collectibles"]):
        return "NFT"
    if any(x in cat for x in ["game", "gaming", "metaverse"]):
        return "Gaming"
    if any(x in cat for x in ["ai", "analytics", "oracle", "data"]):
        return "AI/Infra"

    return "General"


# ==========================
# DEFILLAMA: PROTOKOL LİSTESİ
# ==========================

def fetch_protocols() -> list[dict]:
    """
    Tüm protokolleri çeker.
    /api/protocols endpoint'i TVL, kategori, zincirler ve listedAt içerir. :contentReference[oaicite:3]{index=3}
    """
    url = f"{DEFILLAMA_BASE}/api/protocols"
    data = jget(url)
    if not data:
        return []
    if isinstance(data, list):
        return data
    # Bazı wrapper’lar { "protocols": [...] } dönebilir diye güvenli olmak için:
    return data.get("protocols", [])


def build_protocol_index(protocols: list[dict]) -> dict[str, dict]:
    """
    slug -> protokol map'i.
    """
    idx = {}
    for p in protocols:
        slug = p.get("slug") or p.get("name")
        if slug:
            idx[slug] = p
    return idx


# ==========================
# KALİTE SKORU (YATIRIM / CİDDİ PROJE BENZERİ)
# ==========================

def score_protocol_quality(proto: dict) -> int:
    """
    Basit, ama mantıklı bir kalite skoru:
    - Güçlü kategori
    - TVL büyüklüğü
    - Çoklu chain
    - Yeni eklenmiş olma (early)
    """
    score = 0

    tvl = proto.get("tvl") or 0
    category = detect_category(proto)
    chains = proto.get("chains") or []
    listed_at = proto.get("listedAt") or 0

    # temel: protokol DefiLlama'da listelenmiş = 10
    score += 10

    # kategoriye göre bonus
    if category in ["L1/L2", "Perp/DEX", "DEX", "DeFi", "AI/Infra"]:
        score += 25
    elif category in ["NFT", "Gaming"]:
        score += 15
    else:
        score += 5

    # TVL
    if tvl >= 50_000_000:
        score += 30
    elif tvl >= 10_000_000:
        score += 20
    elif tvl >= 1_000_000:
        score += 10

    # Çoklu chain
    if len(chains) >= 3:
        score += 15
    elif len(chains) == 2:
        score += 8

    # Yeni eklenmişse early bonus
    if listed_at:
        age_days = (time.time() - listed_at) / 86400
        if age_days <= NEW_PROJECT_DAYS:
            score += 20
        elif age_days <= 30:
            score += 10

    return score


# ==========================
# KULLANICI / HYPE SKORU (AIRDROP / TESTNET TADINDA)
# ==========================

def fetch_active_users() -> dict:
    """
    /api/activeUsers: tüm protokoller için aktif kullanıcı sayıları. :contentReference[oaicite:4]{index=4}
    """
    url = f"{DEFILLAMA_BASE}/api/activeUsers"
    data = jget(url)
    return data or {}


def score_user_growth(proto: dict, user_entry: dict | None) -> int:
    """
    Kullanıcı/hype skoru:
    - toplam aktif kullanıcı
    - yeni kullanıcı sayısı
    - işlem sayısı
    özellikle yeni eklenmiş protokoller için yüksekse = erken fırsat.
    """
    if not user_entry:
        return 0

    score = 0

    users_val = (user_entry.get("users") or {}).get("value") or 0
    new_users_val = (user_entry.get("newUsers") or {}).get("value") or 0
    txs_val = (user_entry.get("txs") or {}).get("value") or 0

    listed_at = proto.get("listedAt") or 0
    recent_bonus = 0
    if listed_at:
        age_days = (time.time() - listed_at) / 86400
        if age_days <= USER_RECENT_DAYS:
            recent_bonus = 10

    # aktif kullanıcı
    if users_val > 5000:
        score += 25
    elif users_val > 1000:
        score += 15
    elif users_val > 300:
        score += 8

    # yeni kullanıcı
    if new_users_val > 500:
        score += 25
    elif new_users_val > 100:
        score += 15
    elif new_users_val > 30:
        score += 8

    # tx sayısı
    try:
        txs_num = int(txs_val)
    except Exception:
        txs_num = 0

    if txs_num > 20_000:
        score += 20
    elif txs_num > 5_000:
        score += 10
    elif txs_num > 1_000:
        score += 5

    # yeni projeye ekstra
    score += recent_bonus

    return score


# ==========================
# MESAJ FORMATLAYICILAR
# ==========================

def format_quality_signal(proto: dict, quality_score: int) -> str:
    name = proto.get("name", "Unknown")
    slug = proto.get("slug", "")
    category = detect_category(proto)
    tvl = proto.get("tvl") or 0
    chains = proto.get("chains") or []
    url = proto.get("url") or ""
    logo = proto.get("logo") or ""
    listed_at = proto.get("listedAt") or 0

    age_txt = "bilinmiyor"
    if listed_at:
        age_days = int((time.time() - listed_at) / 86400)
        age_txt = f"{age_days} gün önce listeye girdi"

    msg = (
        f"🔥 [EARLY QUALITY] Yatırımcı tipi kaliteli proje sinyali\n\n"
        f"📛 Proje: {name}\n"
        f"🏷 Kategori: {category}\n"
        f"⛓ Zincirler: {', '.join(chains) if chains else 'bilinmiyor'}\n"
        f"💰 TVL (DefiLlama): ~${tvl:,.0f}\n"
        f"🧠 Kalite Skoru: {quality_score}/100\n"
        f"📆 Durum: {age_txt}\n"
    )

    if url:
        msg += f"🔗 Website: {url}\n"
    if slug:
        msg += f"🔍 DefiLlama slug: {slug}\n"
    if logo:
        msg += f"🖼 Logo: {logo}\n"

    msg += f"\n⏱ Radar zamanı: {now_utc_str()}\n"
    msg += "Not: Bu bir early-radar sinyalidir, yatırım tavsiyesi değildir."
    return msg


def format_user_signal(proto: dict, user_score: int, user_entry: dict) -> str:
    name = proto.get("name", "Unknown")
    slug = proto.get("slug", "")
    category = detect_category(proto)
    tvl = proto.get("tvl") or 0
    chains = proto.get("chains") or []
    listed_at = proto.get("listedAt") or 0

    users_val = (user_entry.get("users") or {}).get("value") or 0
    new_users_val = (user_entry.get("newUsers") or {}).get("value") or 0
    txs_val = (user_entry.get("txs") or {}).get("value") or 0

    # TVL düşük + kullanıcı artışı yüksek → muhtemel testnet / airdrop / incentives
    potential = ""
    if tvl < 5_000_000 and new_users_val and new_users_val > 100:
        potential = "🌱 Bu profil, testnet / points / airdrop vari erken kampanya olabileceğini düşündürüyor."

    age_txt = "bilinmiyor"
    if listed_at:
        age_days = int((time.time() - listed_at) / 86400)
        age_txt = f"{age_days} gün önce listeye girdi"

    msg = (
        f"⚡ [USAGE / HYPE] Kullanıcı artışı yüksek erken proje\n\n"
        f"📛 Proje: {name}\n"
        f"🏷 Kategori: {category}\n"
        f"⛓ Zincirler: {', '.join(chains) if chains else 'bilinmiyor'}\n"
        f"👥 Aktif kullanıcı: {users_val}\n"
        f"🆕 Yeni kullanıcı (son periyot): {new_users_val}\n"
        f"📨 İşlem sayısı: {txs_val}\n"
        f"💰 TVL: ~${tvl:,.0f}\n"
        f"🧠 Kullanıcı/Hype Skoru: {user_score}/100\n"
        f"📆 Durum: {age_txt}\n"
    )

    if potential:
        msg += f"\n{potential}\n"

    if slug:
        msg += f"\n🔍 DefiLlama slug: {slug}\n"

    msg += f"\n⏱ Radar zamanı: {now_utc_str()}\n"
    msg += "Not: Bu, on-chain kullanım verisine göre erken hareket sinyalidir."
    return msg


# ==========================
# ANA RADAR AKIŞI
# ==========================

def run_radar_once():
    print(f"[*] Early Radar çalışıyor: {now_utc_str()}")

    protocols = fetch_protocols()
    if not protocols:
        print("[WARN] Protokol listesi alınamadı.")
        return

    proto_index = build_protocol_index(protocols)

    # 1) Kaliteli, yeni projeler (VC / ciddi proje benzeri)
    quality_candidates: list[tuple[int, dict]] = []
    now_ts = time.time()

    for p in protocols:
        listed_at = p.get("listedAt") or 0
        if not listed_at:
            continue
        age_days = (now_ts - listed_at) / 86400
        if age_days > NEW_PROJECT_DAYS:
            continue  # çok eski, early sayma

        q_score = score_protocol_quality(p)
        if q_score >= MIN_QUALITY_SCORE:
            quality_candidates.append((q_score, p))

    quality_candidates.sort(key=lambda x: x[0], reverse=True)

    signals_sent = 0

    for score, proto in quality_candidates[: MAX_SIGNALS_PER_RUN]:
        telegram(format_quality_signal(proto, score))
        signals_sent += 1
        time.sleep(1)

    # 2) Kullanıcı / hype odaklı erken projeler (muhtemel airdrop / testnet tadında)
    active_users = fetch_active_users()
    user_candidates: list[tuple[int, dict, dict]] = []

    for slug, u_entry in active_users.items():
        proto = proto_index.get(slug)
        if not proto:
            continue

        # sadece nispeten yeni protokollere bak
        listed_at = proto.get("listedAt") or 0
        if not listed_at:
            continue
        age_days = (now_ts - listed_at) / 86400
        if age_days > USER_RECENT_DAYS:
            continue

        u_score = score_user_growth(proto, u_entry)
        if u_score >= MIN_USER_SCORE:
            user_candidates.append((u_score, proto, u_entry))

    user_candidates.sort(key=lambda x: x[0], reverse=True)

    # kalite sinyalleriyle çok spam olmasın diye toplam sınırı kullanıyoruz
    remaining_slots = MAX_SIGNALS_PER_RUN - signals_sent
    if remaining_slots > 0:
        for score, proto, u_entry in user_candidates[: remaining_slots]:
            telegram(format_user_signal(proto, score, u_entry))
            signals_sent += 1
            time.sleep(1)

    if signals_sent == 0:
        print("[*] Bu turda gönderilecek sinyal bulunamadı.")


# ==========================
# ENTRYPOINT
# ==========================

if __name__ == "__main__":
    run_radar_once()
