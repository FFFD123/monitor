import os
import hashlib
import logging
import requests
import feedparser
from datetime import datetime, timedelta
import time

# ─── Configuración ────────────────────────────────────────────────────────────
RSS_URL = "https://puntoahorro.com/feed/?post_type=product"
# Tiempo máximo hacia atrás para considerar un producto como "nuevo" (15 min)
MAX_AGE_MINUTES = 999999  # Para pruebas, lo ponemos muy alto para ver todos los productos

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK    = os.environ.get("DISCORD_WEBHOOK", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── Lógica de Tiempo ────────────────────────────────────────────────────────
def is_recent(entry) -> bool:
    # Obtenemos la fecha del producto del RSS
    published_parsed = entry.get("published_parsed")
    if not published_parsed:
        return False
    
    # Convertimos a timestamp y comparamos con la hora actual (UTC)
    pub_time = datetime.fromtimestamp(time.mktime(published_parsed))
    now = datetime.utcnow()
    
    # Si el producto tiene menos de 15 minutos, es "nuevo" para nosotros
    return now - pub_time < timedelta(minutes=MAX_AGE_MINUTES)

# ─── RSS y Extracción ────────────────────────────────────────────────────────
def fetch_products() -> list:
    try:
        feed = feedparser.parse(RSS_URL)
        products = []
        for entry in feed.entries:
            # Solo procesamos si es reciente
            if is_recent(entry):
                products.append({
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
    return ""

# ─── Notificaciones (Telegram / Discord) ──────────────────────────────────────
def notify_telegram(product):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Faltan credenciales de Telegram")
        return

    text = f"🛍️ *¡Nuevo!* {product['title']}\n💰 {product['price']}\n🔗 [Ver]({product['link']})"
    
    if product["image"]:
        url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {"chat_id": str(TELEGRAM_CHAT_ID), "photo": product["image"],
                   "caption": text, "parse_mode": "Markdown"}
    else:
        url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": str(TELEGRAM_CHAT_ID), "text": text, "parse_mode": "Markdown"}

    r = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        log.info(f"✅ Telegram OK: {product['title']}")
    else:
        log.error(f"❌ Telegram error {r.status_code}: {r.text}")  # ← esto te dirá exactamente qué falla

def notify_discord(product):
    if not DISCORD_WEBHOOK: return
    embed = {"title": f"🛍️ {product['title']}", "url": product["link"], "description": f"💰 **Precio:** {product['price']}", "color": 0xFF6B00}
    if product["image"]: embed["thumbnail"] = {"url": product["image"]}
    requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]}, timeout=10)

# ─── Ejecución Única ─────────────────────────────────────────────────────────
def main():
    log.info("🔍 Escaneando productos recientes...")
    new_products = fetch_products()
    
    if not new_products:
        log.info("No hay productos nuevos en los últimos 15 minutos.")
        return

    for p in new_products:
        log.info(f"Notificando: {p['title']}")
        notify_telegram(p)
        notify_discord(p)

if __name__ == "__main__":
    main()
