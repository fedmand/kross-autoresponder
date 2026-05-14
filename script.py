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
ACTIVE_APARTMENTS = {"Pellegrini 26"}

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
    path = os.path.join("apartments", f"{safe_name}.md")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No apartment file found for '{apartment_name}' (expected: {path})")
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── Claude ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT_BASE = """You are an AI assistant managing guest communications for Nicolo&Matteo, a short-term rental company in Milan, Italy.

You will receive the full conversation history between the host and the guest, plus context about the apartment and reservation. Reply in a friendly, professional tone — as if you were the host. Rispondi sempre in italiano, indipendentemente dalla lingua usata dall'ospite.

Respond ONLY with this JSON (and nothing else) in ANY of these situations:
{"action": "escalate", "reason": "<brief explanation>"}

Escalate when:
- The guest reports a problem that PERSISTS after instructions were already given (e.g. "still not working", "tried that and it doesn't work")
- The guest is angry, aggressive, or uses offensive language
- There is a maintenance or technical issue requiring physical presence (broken appliance, leak, broken lock, etc.)
- The guest asks for something requiring host approval (late check-out, extra guests, early check-in, bianchieria)
- The question requires information not in the apartment info and not answerable with certainty
- Any situation involving a complaint, dissatisfaction, or request for compensation

Do NOT promise to check, verify, or get back to the guest — if you cannot give a definitive answer right now, escalate.

Otherwise write a direct, helpful reply. Do not include any preamble or sign-off."""


def build_system_prompt(apartment_name, apartment_info, reservation):
    # Reservation and apartment context go in the system prompt so Claude has them
    # as standing background, separate from the conversation turns.
    res   = reservation["data"][0]
    rooms = res.get("rooms", [{}])[0]

    lines = [
        SYSTEM_PROMPT_BASE,
        "\n--- Reservation Context ---",
        f"Apartment: {apartment_name}",
        f"Check-in: {res['arrival']} | Check-out: {res['departure']}",
        f"Guest: {res['label']} | Guests: {rooms.get('qt_guests', '?')} | Language: {res.get('lang', '?')}",
    ]
    if res.get("note"):
        lines.append(f"Notes: {res['note']}")
    if apartment_info:
        lines.append(f"\n--- Apartment Information ---\n{apartment_info}")

    return "\n".join(lines)


def build_conversation(all_messages, up_to_id_message):
    # Converts this guest's thread history into the Claude messages array format.
    # all_messages is the full history for one thread (one guest), chronological order.
    # We include only messages up to and including the one we're replying to.
    # guest → "user" turn, owner → "assistant" turn.
    # Claude requires strictly alternating roles starting with "user", so consecutive
    # messages from the same side are merged into one turn.
    cutoff = next(i for i, m in enumerate(all_messages) if m["id_message"] == up_to_id_message)
    relevant = all_messages[:cutoff + 1]

    messages = []
    for msg in relevant:
        role = "user" if msg["user_role"] == "guest" else "assistant"
        content = msg["message"]
        # Append translation inline so Claude understands non-Italian/English messages
        if msg.get("translated_message") and msg["translated_message"] != msg["message"]:
            content += f"\n(Translation: {msg['translated_message']})"

        if messages and messages[-1]["role"] == role:
            # Merge consecutive same-role messages into one turn
            messages[-1]["content"] += f"\n\n{content}"
        else:
            messages.append({"role": role, "content": content})

    # Claude requires the first message to be "user". If the thread started with
    # an owner message, prepend a placeholder to satisfy the constraint.
    if messages and messages[0]["role"] == "assistant":
        messages.insert(0, {"role": "user", "content": "[conversation start]"})

    return messages


def call_anthropic(system, messages):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",  # good balance of quality and cost for guest replies
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return msg.content[0].text


def is_escalation(reply):
    # Returns True if Claude responded with the escalation JSON instead of a reply.
    try:
        data = json.loads(reply.strip())
        return isinstance(data, dict) and data.get("action") == "escalate"
    except (json.JSONDecodeError, AttributeError):
        return False


# ── Formatting helpers ────────────────────────────────────────────────────────
def fmt_date(iso):
    y, mo, day = iso.split("-")
    return f"{day}-{mo}-{y}"

def fmt_ts(created_at):  # "2026-04-16 11:25:10+02" → "16-04-2026 11:25"
    date_str, time_str = created_at.split(" ")
    return f"{fmt_date(date_str)} {time_str[:5]}"


# ── Telegram notification ─────────────────────────────────────────────────────
def notify(text, parse_mode=None):
    # Sends a message to the host's Telegram chat. Pass parse_mode="Markdown" for bold/italic.
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json=payload)


def notify_escalation(apartment_name, guest_name, checkin, checkout, timestamp, guest_message, reason):
    notify(
        f"🚨 *{apartment_name}*\n"
        f"Ospite: *{guest_name}*\n"
        f"Check-in: *{fmt_date(checkin)}* | Check-out: *{fmt_date(checkout)}*\n"
        f"Orario messaggio: {fmt_ts(timestamp)}\n\n"
        f"Messaggio: {guest_message}\n\n"
        f"Motivo: {reason}",
        parse_mode="Markdown",
    )


def notify_error(apartment_name, error):
    notify(
        f"⚠️ *{apartment_name}*\n"
        f"Errore nell'elaborazione del thread — intervento necessario\n\n"
        f"{error}",
        parse_mode="Markdown",
    )


# ── Process a single thread (thread = reservation)───────────────────────────────────────────────────
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

    # If any unread guest message has no text, it's a photo — Claude can't see images,
    # so escalate the whole thread and let the host handle it.
    if any(not m.get("message") for m in unread_guest_msgs):
        reservation = get_reservation(id_reservation)
        res         = reservation["data"][0]
        photo_msg   = next(m for m in unread_guest_msgs if not m.get("message"))
        print(f"    → Photo detected, notifying host")
        notify(
            f"📷 *{apartment_name}*\n"
            f"Ospite: *{photo_msg['from_first_name']}*\n"
            f"Check-in: *{fmt_date(res['arrival'])}* | Check-out: *{fmt_date(res['departure'])}*\n"
            f"Orario messaggio: {fmt_ts(photo_msg['created_at'])}\n"
            f"L'ospite ha mandato una foto. Controlla su Kross.",
            parse_mode="Markdown",
        )
        return

    apartment_info = load_apartment_file(apartment_name)
    reservation    = get_reservation(id_reservation)

    # Build once per thread — same apartment and reservation context for all messages.
    system       = build_system_prompt(apartment_name, apartment_info, reservation)
    # Full thread history in chronological order (data[] from Kross is newest-first).
    all_messages = list(reversed(detail["data"]))

    # Pass full history up to the last unread message — Claude sees the full context
    # and produces one aggregated reply instead of one reply per message.
    messages = build_conversation(all_messages, unread_guest_msgs[-1]["id_message"])
    reply    = call_anthropic(system, messages)

    if is_escalation(reply):
        reason = json.loads(reply.strip())["reason"]
        print(f"    → Escalating: {reason}")
        res      = reservation["data"][0]
        last_msg = unread_guest_msgs[-1]
        notify_escalation(apartment_name, res["label"], res["arrival"], res["departure"], last_msg["created_at"], last_msg["message"], reason)
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
