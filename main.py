import os
import time
import re
import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
VINTED_COOKIE = os.getenv("VINTED_COOKIE")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # co ile sekund sprawdzać nowe ogłoszenia
SEARCH_QUERIES = os.getenv("SEARCH_QUERIES", "")
EXCLUDE_KEYWORDS = os.getenv("EXCLUDE_KEYWORDS", "").split(",")

seen_items = set()

def fetch_description(item_id):
    """Scrapuje opis ogłoszenia z jego strony Vinted."""
    url = f"https://www.vinted.pl/items/{item_id}"
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": VINTED_COOKIE}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Pobiera opis z <meta name="description">
        desc_meta = soup.find("meta", {"name": "description"})
        if desc_meta and desc_meta.get("content"):
            return desc_meta["content"].lower()
        return ""
    except Exception as e:
        print(f"[ERR] fetch_description {item_id}: {e}")
        return ""

def send_telegram(text, photo_url=None):
    """Wysyła wiadomość do Telegrama (z opcjonalnym zdjęciem)."""
    try:
        if photo_url:
            photo_resp = requests.get(photo_url, timeout=15)
            files = {"photo": photo_resp.content}
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": text,
                "parse_mode": "HTML",
            }
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                data=payload,
                files=files,
            )
        else:
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=payload
            )
        print(f"[DEBUG] Status wysłania: {resp.status_code}")
    except Exception as e:
        print(f"[ERR] send_telegram: {e}")


def slugify(title):
    replacements = {
        "ą": "a",
        "ć": "c",
        "ę": "e",
        "ł": "l",
        "ń": "n",
        "ó": "o",
        "ś": "s",
        "ż": "z",
        "ź": "z",
    }
    for src, target in replacements.items():
        title = title.replace(src, target)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug


def extract_memory(title):
    match = re.search(r"(\d{2,4})\s?GB", title, re.IGNORECASE)
    return match.group(1) + "GB" if match else "Nie podano"


def is_excluded(item):
    description = fetch_description(item["id"])
    matched_keywords = [kw.strip() for kw in EXCLUDE_KEYWORDS if kw.strip().lower() in description]
    if matched_keywords:
        print(f"[INFO] Wykluczono ogłoszenie {item.get('title')} po słowach kluczowych: {', '.join(matched_keywords)}")
        return True
    return False



def fetch_page(catalog_id, brand_id, collection_id, price_from, price_to):
    url = (
        "https://www.vinted.pl/api/v2/catalog/items"
        f"?catalog_ids[]={catalog_id}"
        f"&brand_ids[]={brand_id}"
        f"&brand_collection_ids[]={collection_id}"
        f"&price_from={price_from}"
        f"&price_to={price_to}"
        "&page=1"
        "&per_page=10"
        "&order=newest_first"
        "&currency=PLN"
    )
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Cookie": VINTED_COOKIE}
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 401:
            msg = "⚠️ Cookie wygasły! Zaloguj się na Vinted i wklej nowe do .env"
            print("[ERR] Unauthorized – cookie wygasły")
            send_telegram(msg)
            return None

        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[ERR] fetch_page: {e}")
        return None


def format_offer(item):
    """Formatuje wiadomość do Telegrama z linkiem, zdjęciem i pamięcią telefonu."""
    item_id = item.get("id")
    title = item.get("title", "Bez tytułu")
    price_amount = item.get("price", {}).get("amount", "0")
    price_currency = item.get("price", {}).get("currency_code", "PLN")
    photo = item.get("photo", {}).get("url", "")

    slug = slugify(title)
    url = f"https://www.vinted.pl/items/{item_id}-{slug}"
    memory = extract_memory(title)

    message = (
        f"📢 <b>Nowe ogłoszenie!</b>\n\n"
        f"📱 <b>{title}</b>\n"
        f"💾 Pamięć: <b>{memory}</b>\n"
        f"💰 Cena: <b>{price_amount} {price_currency}</b>\n"
        f"🔗 <a href='{url}'>Zobacz ogłoszenie</a>"
    )
    return message, photo


def check_new_items():
    global seen_items
    queries = SEARCH_QUERIES.split(",")
    for q in queries:
        parts = q.split(":")
        if len(parts) != 6:
            continue
        name, catalog_id, brand_id, collection_id, price_from, price_to = parts
        print(f"[INFO] Sprawdzanie wyszukiwania: {name}")
        data = fetch_page(catalog_id, brand_id, collection_id, price_from, price_to)
        if not data:
            continue

        items = data.get("items", [])
        print(f"[INFO] Znaleziono {len(items)} ogłoszeń dla {name}")

        for item in items:
            item_id = item["id"]
            if item_id not in seen_items:
                if is_excluded(item):
                    print(f"[INFO] Wykluczono ogłoszenie {item.get('title')} ze względu na słowa kluczowe")
                    continue
                seen_items.add(item_id)
                message, photo = format_offer(item)
                print(f"[DEBUG] Wysyłam wiadomość: {item.get('title')}")
                send_telegram(message, photo_url=photo)


def main():
    print("Bot wystartował.")
    send_telegram("🤖 Bot wystartował 🚀")

    while True:
        check_new_items()
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
