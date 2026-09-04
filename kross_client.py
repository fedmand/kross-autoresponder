"""
Minimal Kross client used by the host web app.

The bot (script.py) has its own battle-tested Kross client with full rate-limit
tracking and exponential backoff. This module is deliberately separate and tiny:
the web app needs, from Kross, the list of all apartment (name_room_type) values
(only on demand, when the host clicks "Aggiorna da Kross") and the ability to
send a host-drafted reply to a guest thread (only on demand, when the host sends
a draft from a notification). Keeping it here avoids importing script.py (which
would spin up the bot's logging and other side effects).

The fetched apartment list is cached to disk so ordinary page loads NEVER call
Kross — only the explicit refresh button does. This keeps API credit usage
predictable.
"""
import json
import os
import time

import requests
from dotenv import load_dotenv

# Anchored to this module's location (repo root), NOT the process CWD — mirrors
# apartments_store.py so the bot and web app always agree on paths.
_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))

BASE_URL = "https://api.krossbooking.com/v5"

# Cached apartment list lives next to the code (repo root).
CACHE_PATH = os.path.join(_HERE, "kross_apartments_cache.json")

# Pagination tuning. total_count was ~5.7k reservations at 1000/page (~6 pages);
# _MAX_PAGES is a safety cap so a misbehaving API can never spin forever.
_PAGE_SIZE = 1000
_MAX_PAGES = 20
_PAGE_PAUSE = 1.0   # seconds between pages — polite to Kross's 10/min limit
_TIMEOUT = 60       # per-request timeout (with_rooms pages are large/slow)


class KrossError(RuntimeError):
    """Raised when the apartment list cannot be fetched from Kross."""


def _credentials():
    creds = {
        "api_key": os.getenv("KROSS_API_KEY"),
        "hotel_id": os.getenv("KROSS_HOTEL_ID"),
        "username": os.getenv("KROSS_USERNAME"),
        "password": os.getenv("KROSS_PASSWORD"),
    }
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise KrossError("Credenziali Kross mancanti: " + ", ".join(missing))
    return creds


def _get_token():
    try:
        r = requests.post(f"{BASE_URL}/auth/get-token", json=_credentials(), timeout=30)
        r.raise_for_status()
        return r.json()["auth_token"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise KrossError(f"Autenticazione Kross fallita: {exc}") from exc


def _post(endpoint, payload, token):
    # One light retry on 429. The refresh is manual and rare, so a single short
    # backoff is enough to ride out a per-minute spike shared with the bot.
    for attempt in range(3):
        r = requests.post(
            f"{BASE_URL}{endpoint}",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
        if r.status_code == 429 and attempt < 2:
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()


def fetch_apartment_names():
    """All distinct apartment names (name_room_type) currently in Kross, sorted.

    Paginates /reservations/get-list with `with_rooms` and collects every
    distinct room name. This is the same field the bot matches on
    (thread['name_room_type']), so the names line up exactly with the .md files.
    Raises KrossError on any failure so the caller can keep the previous cache.
    """
    token = _get_token()
    names = set()
    offset = 0
    try:
        for _ in range(_MAX_PAGES):
            body = _post(
                "/reservations/get-list",
                {"with_rooms": True, "limit": _PAGE_SIZE, "offset": offset},
                token,
            )
            data = body.get("data") or []
            for rsv in data:
                for room in (rsv.get("rooms") or []):
                    name = room.get("name_room_type")
                    if name:
                        names.add(name)
            if not body.get("has_next_page") or not data:
                break
            offset += _PAGE_SIZE
            time.sleep(_PAGE_PAUSE)
    except (requests.RequestException, ValueError) as exc:
        raise KrossError(f"Lettura appartamenti da Kross fallita: {exc}") from exc
    return sorted(names)


def send_message(id_thread, message):
    """Sends a message to the guest in this thread. Raises KrossError on failure.

    Used only by the host-drafted-reply flow (web/main.py) — a deliberate,
    on-demand write, unlike the read-only apartment-list fetch above. Fetches
    a fresh token per call rather than caching one: this path fires rarely
    (a host clicking "send"), so the extra auth round-trip is negligible.
    """
    token = _get_token()
    try:
        return _post("/messaging/send-message",
                      {"id_thread": id_thread, "message": message}, token)
    except requests.RequestException as exc:
        raise KrossError(f"Invio messaggio a Kross fallito: {exc}") from exc


def refresh_cache():
    """Fetch from Kross and atomically write the cache. Returns (names, fetched_at)."""
    names = fetch_apartment_names()
    fetched_at = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"names": names, "fetched_at": fetched_at}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE_PATH)
    return names, fetched_at


def load_cache():
    """Return (names, fetched_at) from the cache file, or ([], None) if absent."""
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("names", [])), data.get("fetched_at")
    except (OSError, ValueError):
        return [], None
