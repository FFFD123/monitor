#!/usr/bin/env python3
"""
PuntoAhorro Product Monitor
Versión para Render.com Background Worker — bucle infinito cada 3 minutos.
"""

import os
import json
import time
import hashlib
import logging
import requests
import feedparser
from datetime import datetime
from pathlib import Path

# ─── Configuración ────────────────────────────────────────────────────────────
RSS_URL        = "https://puntoahorro.com/feed/?post_type=product"
STATE_FILE     = Path("/tmp/seen_products.json")   # /tmp es persistente en el proceso
CHECK_INTERVAL = 180  # segundos (3 minutos)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK    = os.environ.get("DISCORD_WEBHOOK", "")

# ─── Logging (stdout para que Render lo muestre en su panel) ──────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── Estado ───────────────────────────────────────────────────────────────────
def load_seen() -> set:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set):
    with open(STATE_FILE, "w") as f:
        json.dump(list(seen), f)

# ─── RSS ──────────────────────────────────────────────────────────────────────
def fetch_products() -> list:
    try:
        feed = feedparser.parse(RSS_URL)
        products = []
        for entry in feed.entries:
            uid = hashlib.md5(entry.get("link", entry.get("title", "")).encode()).hexdigest()
            products.append({
                "uid":   uid,
                "title": entry.get("title", "Sin título"),
                "link":  entry.get("link", ""),
                "price": extract_price(entry),
                "image": extract_image(entry),
            })
        return products
    except Exception as e:
        log.error(f"Error al descargar RSS: {e}")
        return []

def extract_price(entry) -> str:
    import re
    content = entry.get("summary", "")
    if entry.get("content"):
        content += entry["content"][0].get("value", "")
    match = re.search(r'[\d]+[,.]?\d*\s*€', content)
    return match.group(0) if match else ""

def extract_image(entry) -> str:
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url", "")
    if hasattr(entry, "enclosures") and entry.enclosures:
        return entry.enclosures[0].get("href", "")
    return ""

# ─── Notificaciones ───────────────────────────────────────────────────────────
def notify_telegram(product: dict):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    price_line = f"💰 *Precio:* {product['price']}\n" if product["price"] else ""
    text = (
        f"🛍️ *¡Nuevo producto en PuntoAhorro!*\n\n"
        f"📦 *{product['title']}*\n"
        f"{price_line}"
        f"🔗 [Ver producto]({product['link']})"
    )

    if product["image"]:
        url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "photo": product["image"],
                   "caption": text, "parse_mode": "Markdown"}
    else:
        url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            log.info(f"✅ Telegram OK: {product['title']}")
        else:
            log.error(f"❌ Telegram {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"❌ Telegram excepción: {e}")


def notify_discord(product: dict):
    if not DISCORD_WEBHOOK:
        return

    price_line = f"💰 **Precio:** {product['price']}\n" if product["price"] else ""
    embed = {
        "title":       f"🛍️ {product['title']}",
        "url":         product["link"],
        "description": f"{price_line}¡Nuevo producto disponible en PuntoAhorro!",
        "color":       0xFF6B00,
        "footer":      {"text": f"PuntoAhorro Monitor • {datetime.now().strftime('%d/%m/%Y %H:%M')}"},
    }
    if product["image"]:
        embed["thumbnail"] = {"url": product["image"]}

    payload = {
        "username":   "PuntoAhorro Bot",
        "avatar_url": "https://puntoahorro.com/favicon.ico",
        "embeds":     [embed],
    }

    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if r.status_code in (200, 204):
            log.info(f"✅ Discord OK: {product['title']}")
        else:
            log.error(f"❌ Discord {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"❌ Discord excepción: {e}")


# ─── Ciclo de comprobación ────────────────────────────────────────────────────
def check_once(seen: set) -> set:
    log.info("🔍 Comprobando nuevos productos...")
    products = fetch_products()

    if not products:
        log.warning("RSS vacío o error de red.")
        return seen

    new_products = [p for p in products if p["uid"] not in seen]

    if not new_products:
        log.info(f"Sin novedades. ({len(products)} productos en el feed)")
        return seen

    log.info(f"🆕 {len(new_products)} producto(s) nuevo(s)!")
    for product in new_products:
        log.info(f"  → {product['title']}")
        notify_telegram(product)
        notify_discord(product)
        seen.add(product["uid"])

    save_seen(seen)
    return seen


# ─── Main: bucle infinito ─────────────────────────────────────────────────────
def main():
    log.info("🚀 PuntoAhorro Monitor arrancado.")
    log.info(f"⏱️  Intervalo de comprobación: {CHECK_INTERVAL} segundos")

    # Validar configuración
    if not TELEGRAM_BOT_TOKEN:
        log.warning("⚠️  TELEGRAM_BOT_TOKEN no configurado")
    if not TELEGRAM_CHAT_ID:
        log.warning("⚠️  TELEGRAM_CHAT_ID no configurado")
    if not DISCORD_WEBHOOK:
        log.warning("⚠️  DISCORD_WEBHOOK no configurado")

    seen = load_seen()
    log.info(f"📂 Productos ya conocidos: {len(seen)}")

    while True:
        try:
            seen = check_once(seen)
        except Exception as e:
            log.error(f"💥 Error inesperado en el ciclo: {e}")

        log.info(f"😴 Esperando {CHECK_INTERVAL // 60} minutos...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
