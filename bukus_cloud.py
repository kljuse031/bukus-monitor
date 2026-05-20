import requests
import time
import re
import json
from bs4 import BeautifulSoup
import os
import sys
print(f"Python version: {sys.version}")
print(f"TELEGRAM_TOKEN set: {bool(os.environ.get('TELEGRAM_TOKEN'))}")
print(f"TELEGRAM_CHAT_ID set: {bool(os.environ.get('TELEGRAM_CHAT_ID'))}")
URL = "https://bigusbukus.com/"
BOOK_URL = "https://bigusbukus.com/knjiga/{}"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
STATE_FILE = "state.json"
WATCHLIST_FILE = "watchlist.txt"

def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False
            },
            timeout=10
        )
    except Exception as e:
        print(f"Telegram error: {e}")

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f).get("max_known_id", 0)
    except:
        return 0

def save_state(max_id):
    with open(STATE_FILE, "w") as f:
        json.dump({"max_known_id": max_id}, f)

def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return [line.strip().lower() for line in f if line.strip()]
    except:
        return []

def normalize(text):
    replacements = {
        'š': 's', 'č': 'c', 'ž': 'z', 'ć': 'c', 'đ': 'd'
    }
    text = text.lower()
    for accented, plain in replacements.items():
        text = text.replace(accented, plain)
    return text

def is_on_watchlist(title, author, watchlist):
    combined = normalize(title + " " + author)
    return any(normalize(entry) in combined for entry in watchlist)

def parse_books_from_page(page=1):
    url = URL if page == 1 else f"{URL}?page={page}"
    resp = requests.get(url, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")

    books = []
    seen_ids = set()

    for h3 in soup.find_all("h3"):
        link = h3.find("a", href=re.compile(r"/knjiga/\d+"))
        if not link:
            continue
        match = re.search(r"/knjiga/(\d+)", link.get("href", ""))
        if not match:
            continue
        book_id = int(match.group(1))
        if book_id in seen_ids:
            continue
        seen_ids.add(book_id)

        title = link.text.strip()
        author = ""
        if h3.parent:
            for sibling in h3.next_siblings:
                text = sibling.text.strip() if hasattr(sibling, "text") else str(sibling).strip()
                if text and len(text) < 100 and text != title:
                    author = text
                    break

        if title:
            books.append((book_id, title, author))

    return books

def get_book_details_from_pages(book_id):
    for page in range(1, 30):
        try:
            books = parse_books_from_page(page)
            if not books:
                break
            for bid, title, author in books:
                if bid == book_id:
                    return title, author
            if all(bid < book_id for bid, _, _ in books):
                break
        except:
            break
    return None, None

def check_books():
    max_known_id = load_state()
    watchlist = load_watchlist()
    first_run = max_known_id == 0

    try:
        books = parse_books_from_page(1)
        if not books:
            print(f"[{time.strftime('%H:%M')}] No books found.")
            return

        page_ids = {b[0] for b in books}
        book_map = {b[0]: (b[1], b[2]) for b in books}
        current_max = max(page_ids)

        if first_run:
            save_state(current_max)
            print(f"[{time.strftime('%H:%M')}] First run. Baseline set at #{current_max}.")
            send_telegram(f"✅ BigusBukus cloud monitor started! Watching from book \\#{current_max}.")
            return

        if current_max <= max_known_id:
            print(f"[{time.strftime('%H:%M')}] No new books. Highest ID still #{max_known_id}.")
            return

        new_ids = list(range(max_known_id + 1, current_max + 1))
        print(f"[{time.strftime('%H:%M')}] Found {len(new_ids)} new book(s)!")

        for book_id in new_ids:
            if book_id in book_map:
                title, author = book_map[book_id]
            else:
                title, author = get_book_details_from_pages(book_id)

            if title is None:
                print(f"  #{book_id} already sold, skipping.")
                continue

            print(f"  New book: {title} by {author} (#{book_id})")

            if watchlist and is_on_watchlist(title, author, watchlist):
                print(f"  ⭐ WATCHLIST MATCH: {title}")
                msg = (
                    f"⭐ *Watchlist match on BigusBukus!*\n\n"
                    f"📖 *{title}*\n"
                    f"✍️ {author if author else 'Unknown author'}\n"
                    f"🔗 [Open book]({BOOK_URL.format(book_id)})"
                )
            else:
                msg = (
                    f"📚 *New book on BigusBukus!*\n\n"
                    f"📖 *{title}*\n"
                    f"✍️ {author if author else 'Unknown author'}\n"
                    f"🔗 [Open book]({BOOK_URL.format(book_id)})"
                )

            send_telegram(msg)
            time.sleep(0.5)

        save_state(current_max)

    except Exception as e:
        print(f"[{time.strftime('%H:%M')}] Error: {e}")

check_books()
