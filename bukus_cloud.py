import requests
import time
import re
import json
import os
import hashlib
import base64
from bs4 import BeautifulSoup

URL = "https://bigusbukus.com/knjige"
BOOK_URL = "https://bigusbukus.com/knjiga/{}"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY")
GH_TOKEN = os.environ.get("GH_TOKEN")
GITHUB_REPO = "kljuse031/bukus-monitor"
STATE_FILE = "state.json"
WATCHLIST_FILE = "watchlist.txt"

HEARTBEAT_MAX_AGE = 27 * 60  # 19 minutes in seconds

# ─── Cookies ──────────────────────────────────────────────────────────────────

def _decrypt(data: str, key: str) -> str:
    key_bytes = hashlib.sha256(key.encode()).digest()
    decoded = base64.b64decode(data)
    decrypted = bytes([decoded[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(decoded))])
    return decrypted.decode()

def load_cookies_from_github():
    try:
        headers = {
            "Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/cookies.json",
            headers=headers, timeout=10
        )
        if r.status_code == 200:
            raw = base64.b64decode(r.json()["content"]).decode()
            decrypted = _decrypt(raw, GH_TOKEN)
            cookies = json.loads(decrypted)
            print(f"Loaded {len(cookies)} cookies from GitHub.")
            return cookies
    except Exception as e:
        print(f"Cookie load error: {e}")
    return {}

# ─── Telegram ────────────────────────────────────────────────────────────────

def send_telegram(message):
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
        print(f"Telegram response: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Telegram error: {e}")

# ─── Heartbeat ───────────────────────────────────────────────────────────────

def pc_is_online():
    try:
        headers = {
            "Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/heartbeat.txt",
            headers=headers,
            timeout=10
        )
        if r.status_code != 200:
            return False
        content = base64.b64decode(r.json()["content"]).decode().strip()
        last_beat = int(content)
        age = time.time() - last_beat
        print(f"Heartbeat age: {int(age)}s (max {HEARTBEAT_MAX_AGE}s)")
        return age < HEARTBEAT_MAX_AGE
    except Exception as e:
        print(f"Heartbeat check error: {e}")
        return False

# ─── State ───────────────────────────────────────────────────────────────────

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f).get("max_known_id", 0)
    except:
        return 0

def save_state(max_id):
    with open(STATE_FILE, "w") as f:
        json.dump({"max_known_id": max_id}, f)

# ─── Watchlist ────────────────────────────────────────────────────────────────

def load_watchlist():
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return [line.strip().lower() for line in f if line.strip()]
    except:
        return []

def normalize(text):
    text = text.lower()
    for a, b in [("š", "s"), ("č", "c"), ("ž", "z"), ("ć", "c"), ("đ", "d")]:
        text = text.replace(a, b)
    return text

def is_on_watchlist(title, author, watchlist):
    combined = normalize(title + " " + author)
    for entry in watchlist:
        pattern = r'\b' + re.escape(normalize(entry)) + r'\b'
        if re.search(pattern, combined):
            return True
    return False

# ─── Scraping ─────────────────────────────────────────────────────────────────

def scrape_url(target_url, cookies):
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
    proxy_url = (
        f"http://api.scraperapi.com/?api_key={SCRAPER_API_KEY}"
        f"&url={requests.utils.quote(target_url)}&keep_headers=true"
    )
    resp = requests.get(proxy_url, timeout=30, headers={"Cookie": cookie_str})
    return resp

def parse_books_from_page(page, cookies):
    target_url = URL if page == 1 else f"{URL}?page={page}"
    resp = scrape_url(target_url, cookies)
    soup = BeautifulSoup(resp.text, "html.parser")
    print(f"Page {page} — status: {resp.status_code}, h3 count: {len(soup.find_all('h3'))}")

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
        next_p = h3.find_next_sibling("p")
        if next_p:
            author = next_p.text.strip()

        if title:
            books.append((book_id, title, author))

    return books

# ─── Main ─────────────────────────────────────────────────────────────────────

def check_books():
    max_known_id = load_state()
    watchlist = load_watchlist()
    first_run = max_known_id == 0

    if pc_is_online():
        print(f"[{time.strftime('%H:%M')}] PC is online, skipping.")
        return

    print(f"[{time.strftime('%H:%M')}] PC is offline, cloud taking over.")

    # Load cookies once — passed to all scrape calls
    cookies = load_cookies_from_github()

    try:
        books = parse_books_from_page(1, cookies)

        if not books:
            print(f"[{time.strftime('%H:%M')}] No books found.")
            return

        page_ids = {b[0] for b in books}
        book_map = {b[0]: (b[1], b[2]) for b in books}
        current_max = max(page_ids)

        if first_run:
            save_state(current_max)
            print(f"[{time.strftime('%H:%M')}] First run. Baseline set at #{current_max}.")
            send_telegram("BigusBukus cloud monitor started! Watching from book #" + str(current_max))
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
                # Book not on page 1 — skip rather than burn credits
                # paginating through 30 pages per book would drain quota fast
                print(f"  #{book_id} not on page 1, skipping detail lookup.")
                title, author = f"Book #{book_id}", ""

            if title is None:
                print(f"  #{book_id} already sold, skipping.")
                continue

            print(f"  New book: {title} by {author} (#{book_id})")

            on_watchlist = watchlist and is_on_watchlist(title, author, watchlist)
            if on_watchlist:
                msg = (f"⭐ *Watchlist match on BigusBukus!*\n\n"
                       f"📖 *{title}*\n"
                       f"✍️ {author or 'Unknown'}\n"
                       f"🔗 [Open book]({BOOK_URL.format(book_id)})")
            else:
                msg = (f"📚 *New book on BigusBukus!*\n\n"
                       f"📖 *{title}*\n"
                       f"✍️ {author or 'Unknown'}\n"
                       f"🔗 [Open book]({BOOK_URL.format(book_id)})")

            send_telegram(msg)
            time.sleep(0.5)

        save_state(current_max)

    except Exception as e:
        print(f"[{time.strftime('%H:%M')}] Error: {e}")


check_books()
