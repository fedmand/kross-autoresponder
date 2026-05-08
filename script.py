# ── Imports ───────────────────────────────────────────────────────────────────
import os           # read environment variables at runtime
import re           # sanitize apartment names into safe filenames
import json         # parse Claude's escalation JSON
import time         # sleep between polling cycles
import requests     # make HTTP requests to Kross and Telegram APIs
import anthropic    # official Anthropic SDK — wraps the Claude API
from dotenv import load_dotenv


# ── Load credentials from .env ────────────────────────────────────────────────
# Must run before any os.getenv() call.
load_dotenv()

KROSS_API_KEY  = os.getenv("KROSS_API_KEY")
KROSS_HOTEL_ID = os.getenv("KROSS_HOTEL_ID")
KROSS_USERNAME = os.getenv("KROSS_USERNAME")
KROSS_PASSWORD = os.getenv("KROSS_PASSWORD")

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_URL      = "https://api.krossbooking.com/v5"
POLL_INTERVAL = 300  # seconds between polling cycles (5 min, well within rate limits)

# TESTING ONLY — remove this constant and the early-return check in process_thread() for full production.
# Lists the apartments the bot is allowed to handle. All others are silently skipped.
# Use the exact name_room_type string returned by Kross (e.g. as printed in the console logs).
ACTIVE_APARTMENTS = {"Palestrina 4/B"}

# Global bearer token — fetched once on startup, auto-refreshed on 401.
_token = None


# ── Generic Kross HTTP helper ─────────────────────────────────────────────────
def kross_post(endpoint, payload, token=None):
    # Headers carry metadata: Content-Type tells Kross the body is JSON,
    # Authorization carries the bearer token for authenticated endpoints.
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    r = requests.post(f"{BASE_URL}{endpoint}", json=payload, headers=headers)
    r.raise_for_status()  # raises on 4xx/5xx so errors don't silently pass
    return r.json()


def kross_call(endpoint, payload):
    # All authenticated calls go through here instead of kross_post directly.
    # If Kross returns 401 (token expired), we re-authenticate and retry once.
    global _token
    try:
        return kross_post(endpoint, payload, token=_token)
    except requests.HTTPError as e:
        if e.response.status_code == 401:
            print("Token expired — re-authenticating...")
            _token = get_auth_token()
            return kross_post(endpoint, payload, token=_token)
        raise


# ── Kross API calls ───────────────────────────────────────────────────────────
def get_auth_token():
    # Credentials go in the body. Returns a token valid for 7 days.
    # Real response field: "auth_token" (not "token").
    data = kross_post("/auth/get-token", {
        "api_key":  KROSS_API_KEY,
        "hotel_id": KROSS_HOTEL_ID,
        "username": KROSS_USERNAME,
        "password": KROSS_PASSWORD,
    })
    return data["auth_token"]


def get_threads():
    # Returns only threads with unread guest messages (to_read: true).
    # Real response: {"data": [{id_thread, id_reservation, name_room_type, to_read, ...}]}
    return kross_call("/messaging/get-threads", {"to_read": True})


def get_thread(id_thread):
    # Returns full message history for one thread, ordered newest-first.
    # Each message has: message, translated_message, user_role ("guest"/"owner"), from_first_name.
    return kross_call("/messaging/get-thread", {"id_thread": id_thread})


def get_reservation(id_reservation):
    # with_rooms: true adds the "rooms" array with apartment details and guest count.
    # Also returns: guest language (lang), notes, check-in/out, phone.
    return kross_call("/reservations/get-list",
                      {"id_reservation": id_reservation, "with_rooms": True})


def send_message(id_thread, message):
    return kross_call("/messaging/send-message",
                      {"id_thread": id_thread, "message": message})


# ── Apartment info files ──────────────────────────────────────────────────────
def load_apartment_file(apartment_name):
    # Apartment names can contain "/" (e.g. "Palestrina 4/B") which is invalid in file paths.
    # We replace any filesystem-unsafe chars with "-" to get a consistent filename.
    safe_name = re.sub(r'[<>:"/\\|?*]', "-", apartment_name)
    path = os.path.join("apartments", f"{safe_name}.txt")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No apartment file found for '{apartment_name}' (expected: {path})")
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── Claude ────────────────────────────────────────────────────────────────────
# System prompt: tells Claude its role, tone, language rule, and when to escalate.
SYSTEM_PROMPT = """You are an AI assistant managing guest communications for Milano Holiday Homes, a short-term rental company in Milan, Italy.

You will receive a guest message along with context about the apartment and reservation. Reply in a friendly, professional tone — as if you were the host. Always reply in the same language the guest used.

If you cannot answer confidently — the question requires information you don't have, involves a complaint needing human judgment, or concerns something outside what the apartment info covers — respond ONLY with this JSON and nothing else:
{"action": "escalate", "reason": "<brief explanation of why you can't handle it>"}

Otherwise write a direct, helpful reply. Do not include any preamble or sign-off."""


def build_prompt(guest_message, translated_message, apartment_name, apartment_info, reservation):
    # Build the user-turn message Claude will read. Packs in all available context.
    res   = reservation["data"][0]
    rooms = res.get("rooms", [{}])[0]

    lines = [
        f"Apartment: {apartment_name}",
        f"Check-in: {res['arrival']} | Check-out: {res['departure']}",
        f"Guest: {res['label']} | Guests: {rooms.get('qt_guests', '?')} | Language: {res.get('lang', '?')}",
    ]
    if res.get("note"):
        lines.append(f"Reservation notes: {res['note']}")

    if apartment_info:
        lines.append(f"\n--- Apartment Information ---\n{apartment_info}")

    lines.append(f"\n--- Guest Message ---\n{guest_message}")
    # Include translation when the guest wrote in a different language — helps Claude understand
    if translated_message and translated_message != guest_message:
        lines.append(f"(Translation: {translated_message})")

    return "\n".join(lines)


def call_anthropic(prompt):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",  # good balance of quality and cost for guest replies
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def is_escalation(reply):
    # Returns True if Claude responded with the escalation JSON instead of a reply.
    try:
        data = json.loads(reply.strip())
        return isinstance(data, dict) and data.get("action") == "escalate"
    except (json.JSONDecodeError, AttributeError):
        return False


# ── Telegram notification ─────────────────────────────────────────────────────
def notify(text):
    # Sends a plain-text message to the host's Telegram chat.
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
    )


def notify_escalation(apartment_name, guest_message, reason):
    notify(
        f"Unhandled guest message — action needed\n\n"
        f"Apartment: {apartment_name}\n\n"
        f"Guest: {guest_message}\n\n"
        f"Reason not auto-replied: {reason}"
    )


def notify_error(apartment_name, error):
    notify(
        f"Error processing thread — action needed\n\n"
        f"Apartment: {apartment_name}\n\n"
        f"Error: {error}"
    )


# ── Process a single thread ───────────────────────────────────────────────────
def process_thread(thread):
    id_thread      = thread["id_thread"]
    id_reservation = thread["id_reservation"]
    apartment_name = thread["name_room_type"]

    # TESTING ONLY — remove this block for full production (together with ACTIVE_APARTMENTS above).
    if ACTIVE_APARTMENTS and apartment_name not in ACTIVE_APARTMENTS:
        return

    print(f"  Thread {id_thread} ({apartment_name})")

    # Collect all unread guest messages, then reverse so we reply oldest-first.
    # data[] comes newest-first from Kross; reversing gives chronological order.
    detail = get_thread(id_thread)
    unread_guest_msgs = [
        m for m in reversed(detail["data"])
        if m["user_role"] == "guest" and m["to_read"]
    ]

    # Thread has no unread guest messages — nothing to reply to
    if not unread_guest_msgs:
        return

    apartment_info = load_apartment_file(apartment_name)
    reservation    = get_reservation(id_reservation)

    for guest_msg in unread_guest_msgs:
        prompt = build_prompt(
            guest_msg["message"],
            guest_msg.get("translated_message"),
            apartment_name,
            apartment_info,
            reservation,
        )
        reply = call_anthropic(prompt)

        if is_escalation(reply):
            reason = json.loads(reply.strip())["reason"]
            print(f"    → Escalating: {reason}")
            notify_escalation(apartment_name, guest_msg["message"], reason)
        else:
            print(f"    → Replying: {reply[:80]}...")
            send_message(id_thread, reply)


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    global _token

    print("Starting Kross Autoresponder...")
    _token = get_auth_token()
    print("Authenticated.")

    while True:
        try:
            threads = get_threads()
            unread  = threads["data"]
            print(f"\nPolling — {len(unread)} unread thread(s).")

            for thread in unread:
                try:
                    process_thread(thread)
                except Exception as e:
                    print(f"  Error on thread {thread['id_thread']}: {e}")
                    notify_error(thread.get("name_room_type", f"thread {thread['id_thread']}"), e)

        except Exception as e:
            print(f"Error polling: {e}")

        print(f"Sleeping {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
