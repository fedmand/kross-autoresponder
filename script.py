# ── Imports ───────────────────────────────────────────────────────────────────
import os           # read environment variables at runtime
import re           # sanitize apartment names into safe filenames
import json         # parse Claude's escalation JSON
import time         # sleep between polling cycles
import requests     # make HTTP requests to Kross and Telegram APIs
import anthropic    # official Anthropic SDK — wraps the Claude API
import storage      # SQLite-backed notification store — dedup + shared GUI data
import apartments_store  # shared apartments/*.md path + read/write (also used by web app)
import active_store  # shared whitelist of apartments the bot may handle (web-managed)
import logging      # structured, timestamped logging to file + console
from logging.handlers import TimedRotatingFileHandler  # one log file per day
from collections import deque, Counter  # rate-limit window + per-cycle tallies
from datetime import datetime   # current Italian date/time for Claude's context
from zoneinfo import ZoneInfo   # Europe/Rome timezone (handles CET/CEST automatically)
from dotenv import load_dotenv


# ── Load credentials from .env ────────────────────────────────────────────────
# Must run before any os.getenv() call.
load_dotenv()


# ── Logging ───────────────────────────────────────────────────────────────────
# Writes to a daily-rotating file (logs/bot.log, one file per day kept for 30 days)
# AND to the console, so `journalctl -u kross-bot` keeps working unchanged.
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_file_handler = TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "bot.log"),
    when="midnight",     # roll over at 00:00 local time
    backupCount=30,      # keep 30 days of history, then discard the oldest
    encoding="utf-8",
)
_file_handler.suffix = "%Y-%m-%d"  # rotated files look like bot.log.2026-06-07

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[_file_handler, logging.StreamHandler()],
)
log = logging.getLogger("kross")

KROSS_API_KEY  = os.getenv("KROSS_API_KEY")
KROSS_HOTEL_ID = os.getenv("KROSS_HOTEL_ID")
KROSS_USERNAME = os.getenv("KROSS_USERNAME")
KROSS_PASSWORD = os.getenv("KROSS_PASSWORD")

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
DEEPSEEK_API_KEY   = os.getenv("DEEPSEEK_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_URL      = "https://api.krossbooking.com/v5"
POLL_INTERVAL = 1000  # seconds between polling cycles (5 min, well within rate limits)

# Switch to "deepseek" to use DeepSeek instead of Claude (requires DEEPSEEK_API_KEY in .env).
MODEL_PROVIDER = "claude"

# Apartments the bot is allowed to handle ("whitelist"). All others are silently
# skipped. This list is now managed from the host web app (Info case → toggle)
# and persisted by active_store; the bot re-reads it every cycle, so onboarding a
# house no longer needs a code change. An empty list means "handle nothing".
# Seeded once from active_store.DEFAULT_ACTIVE so behaviour is unchanged at first.

# Names that appear as last_message_from_name when a host/cohost sent the last message.
# If the last sender is a known host, we skip get_thread() entirely — no reply needed.
KNOWN_HOSTS = {"Matteo", "Nicolo", "Riccardo", "api"}

# Global bearer token — fetched once on startup, auto-refreshed on 401.
_token = None

# ── Kross rate-limit tracking ─────────────────────────────────────────────────
# Documented Kross limits: 10/min, 300/hour, 5000/day. Every Kross call funnels
# through kross_post(), so we count there. We keep the timestamps of the last
# 24h of calls and, on each call, report usage and warn when nearing a limit.
KROSS_LIMITS = {"1m": (60, 10), "1h": (3600, 300), "24h": (86400, 5000)}
RATE_WARN_RATIO = 0.8  # warn once usage reaches 80% of any limit
_call_times = deque()

# ── 429 retry / backoff ───────────────────────────────────────────────────────
# Kross recommends an exponential backoff for temporary errors (429/500):
# 10s, 20s, 40s, 80s... After ~7 retries (~10 min) it advises contacting support.
KROSS_MAX_RETRIES   = 6
KROSS_BACKOFF_BASE  = 10  # seconds for the first retry; doubles each attempt

# ── Claude circuit breaker ────────────────────────────────────────────────────
# Prevents hammering Claude when calls keep failing (e.g. exhausted credit, API
# outage). After CLAUDE_FAILURE_THRESHOLD consecutive failures we stop calling
# Claude for CLAUDE_COOLDOWN seconds; a single success resets the counter.
CLAUDE_FAILURE_THRESHOLD = 5
CLAUDE_COOLDOWN = 1800  # 30 minutes
_claude_consecutive_failures = 0
_claude_paused_until = 0.0


def claude_circuit_open():
    # True while Claude calls are paused after repeated failures.
    return time.time() < _claude_paused_until


def _throttle():
    # Safety net (Fix 3): block before a call would exceed any Kross window.
    # Uses the same _call_times deque the tracker maintains. If we're already at
    # a limit, sleep just long enough for the oldest call in that window to age
    # out, then re-check. This guarantees the bot never self-inflicts a 429 even
    # if a burst occurs, regardless of the fixed sleeps elsewhere.
    while True:
        now = time.time()
        while _call_times and now - _call_times[0] > 86400:
            _call_times.popleft()

        wait = 0.0
        for name, (window, limit) in KROSS_LIMITS.items():
            in_window = [t for t in _call_times if now - t <= window]
            if len(in_window) >= limit:
                # Sleep until the oldest call in this window leaves it.
                needed = window - (now - in_window[0]) + 0.1
                if needed > wait:
                    wait = needed
        if wait <= 0:
            return
        log.warning(f"[RATE] throttling — sleeping {wait:.1f}s to stay within Kross limits")
        time.sleep(wait)


def _record_api_call():
    now = time.time()
    _call_times.append(now)
    # Drop timestamps older than the largest window (24h) so the deque stays bounded.
    while _call_times and now - _call_times[0] > 86400:
        _call_times.popleft()

    counts = {
        name: sum(1 for t in _call_times if now - t <= window)
        for name, (window, _limit) in KROSS_LIMITS.items()
    }
    log.info(
        "[RATE] kross calls — "
        + "  ".join(f"{name}={counts[name]}/{limit}" for name, (_w, limit) in KROSS_LIMITS.items())
    )
    for name, (_window, limit) in KROSS_LIMITS.items():
        if counts[name] >= RATE_WARN_RATIO * limit:
            log.warning(
                f"[RATE] approaching Kross {name} limit: {counts[name]}/{limit} "
                f"({counts[name] / limit:.0%})"
            )


# ── Generic Kross HTTP helper ─────────────────────────────────────────────────
def kross_post(endpoint, payload, token=None):
    # Headers carry metadata: Content-Type tells Kross the body is JSON,
    # Authorization carries the bearer token for authenticated endpoints.
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Retry loop (Fix 1): on 429 (Too Many Requests) back off exponentially and
    # retry instead of crashing the thread. A 429 from the per-minute window
    # clears within ~60s, so the first retry almost always succeeds.
    delay = KROSS_BACKOFF_BASE
    for attempt in range(KROSS_MAX_RETRIES + 1):
        _throttle()  # Fix 3: never exceed a window in the first place
        log.info(f"[API] POST {endpoint}")
        r = requests.post(f"{BASE_URL}{endpoint}", json=payload, headers=headers)
        _record_api_call()  # count the call regardless of HTTP status — it still hit Kross

        if r.status_code == 429 and attempt < KROSS_MAX_RETRIES:
            log.warning(
                f"[RATE] 429 Too Many Requests on {endpoint} — backing off {delay}s "
                f"(attempt {attempt + 1}/{KROSS_MAX_RETRIES})"
            )
            time.sleep(delay)
            delay *= 2
            continue

        # On any 4xx/5xx, Kross returns the real reason in the body
        # (error_code, error_message, ruid). raise_for_status() alone would
        # discard it and surface only the bare HTTP status, so we log the body
        # and enrich the exception before re-raising — keeping the HTTPError
        # type (and .response) intact so kross_call's 401 handling still works.
        if not r.ok:
            try:
                detail = r.json()
            except ValueError:
                detail = {"raw": (r.text or "")[:500]}
            if isinstance(detail, dict):
                log.error(
                    f"[API] {r.status_code} on {endpoint} — "
                    f"error_code={detail.get('error_code')} "
                    f"error_message={detail.get('error_message')!r} "
                    f"ruid={detail.get('ruid')}"
                )
            try:
                r.raise_for_status()
            except requests.HTTPError as e:
                if isinstance(detail, dict) and detail.get("error_message"):
                    base = e.args[0] if e.args else str(e)
                    e.args = (
                        f"{base} — Kross error_code={detail.get('error_code')} "
                        f"\"{detail.get('error_message')}\" (ruid={detail.get('ruid')})",
                    )
                raise

        return r.json()


def kross_call(endpoint, payload):
    # All authenticated calls go through here instead of kross_post directly.
    # If Kross returns 401 (token expired), we re-authenticate and retry once.
    global _token
    try:
        return kross_post(endpoint, payload, token=_token)
    except requests.HTTPError as e:
        if e.response.status_code == 401:
            log.info("Token expired — re-authenticating...")
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
    # Delegates to the shared module so the bot and the host web app always
    # resolve to the same file on disk (absolute path, identical name
    # sanitization). The file is read fresh on every reply, so prompt edits
    # made from the web app take effect on the next poll cycle with no restart.
    return apartments_store.read_apartment(apartment_name)


# ── Claude ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT_BASE = """You are an AI assistant managing guest communications for Nicolo&Matteo, a short-term rental company in Milan, Italy.

You will receive the full conversation history between the host and the guest, plus context about the apartment and reservation. Reply in a friendly, professional tone — as if you were the host. Rispondi sempre in italiano, indipendentemente dalla lingua usata dall'ospite.

Respond ONLY with this JSON (and nothing else) whenever the situation must be escalated to the host:
{"action": "escalate", "reason": "<brief explanation>"}

THESE ESCALATION RULES TAKE PRECEDENCE OVER THE APARTMENT INFORMATION.
The apartment information below may contain "primary objectives" or an "escalation policy" that tell you to solve problems yourself or to "avoid unnecessary escalation". IGNORE any such guidance when it conflicts with this section: for any genuine fault, complaint, or anything that needs a person on-site or coordination with a third party (technician, maintenance, cleaning staff), you MUST escalate, even on the guest's FIRST message about it.

FIRST, DISTINGUISH WHAT THE GUEST IS ASKING — this is critical:
- "HOW DO I USE IT?" → NOT a fault. If the guest only asks how to use, turn on, or operate something (e.g. "come accendo l'aria condizionata?", "come funziona la lavatrice?", "dov'è il termostato?"), this is a normal question: answer using the apartment instructions / "how to use" scripts in the apartment file. Do NOT escalate.
- "IT'S NOT WORKING" → fault. If the guest says something is broken, not working, not responding, making strange noises, has stopped on its own, OR that they already followed the instructions and it still doesn't work, you MUST escalate (do not keep sending fixes).

Escalate (send the JSON) in ANY of these situations:
- The guest reports that something is broken, not working, or malfunctioning — air conditioning or heating not working, no hot water, fridge/oven/washing machine/dishwasher/boiler/router not working, broken lock or keybox, etc. This means an actual malfunction, NOT a "how do I use it?" question (see above). Escalate IMMEDIATELY, on the first message reporting the fault — do NOT wait for it to "persist".
- The guest reports pests or insects (ants / "formiche", cockroaches, bedbugs, etc.).
- The guest reports a leak, flooding, or any bad smell / plumbing odour ("odore di tubature", drains, gas).
- The guest reports physical discomfort caused by the apartment (e.g. "fa troppo caldo / freddo", AC not reaching a room).
- The guest is angry, aggressive, uses offensive language, or expresses any complaint, dissatisfaction, or request for compensation/refund.
- The guest asks for something requiring host approval (late check-out, early check-in, extra guests, biancheria/linen change, extra cleaning).
- The question requires information that is NOT in the apartment info and that you cannot answer with certainty.

You may add a brief, reassuring acknowledgement to the host in the "reason", but you MUST escalate the cases above instead of trying to resolve them yourself.

NEVER make commitments on the host's behalf. Do NOT promise (or even suggest) that you will send a technician, bring a portable AC unit or any replacement item, repair something, issue a refund, or give a specific timeline ("domani mattina", "entro stasera", ...). Anything that requires the host or a third party to act = escalate, do not promise.

When escalating, also add a "category" field to the JSON — but ONLY if the situation clearly matches one of these two:
- "riparazione": the issue requires a physical repair or maintenance intervention (broken appliance, water leak, broken lock, AC/heating not working, no hot water, boiler issue, pests, persistent bad smell, etc.)
- "checkin_checkout": the guest is explicitly requesting an early check-in or a late check-out.
If neither applies, omit the "category" field entirely.

Examples:
{"action": "escalate", "reason": "Perdita d'acqua sotto il lavandino", "category": "riparazione"}
{"action": "escalate", "reason": "Aria condizionata non funziona, ospite accaldato", "category": "riparazione"}
{"action": "escalate", "reason": "Formiche in cucina", "category": "riparazione"}
{"action": "escalate", "reason": "Richiesta late check-out alle 14:00", "category": "checkin_checkout"}
{"action": "escalate", "reason": "Ospite arrabbiato per il rumore"}

Do NOT promise to check, verify, or get back to the guest — if you cannot give a definitive answer right now, escalate. When in doubt about a fault or a complaint, ESCALATE rather than answering.

CRITICAL — output format rules:
- When escalating, output ONLY the raw JSON object: no markdown code fences, no backticks, no text before or after it.
- When NOT escalating, write ONLY the plain-text reply for the guest. NEVER include any JSON, curly braces, "action", "escalate", or any machine-readable content in a guest-facing reply. The escalation JSON is read by the system, never shown to the guest.

The current date/time and the check-in/check-out dates are given below ALREADY with their weekday and a relative descriptor (oggi/domani/tra N giorni) precomputed for you. ALWAYS use those exact weekdays and dates as given — NEVER compute or guess the day of the week yourself. When referring to a day, use the weekday and date exactly as provided (e.g. "venerdì 26 giugno"); do NOT say "sabato" / "domani" / "oggi" unless it matches the precomputed value below.

Otherwise (for ordinary questions with no fault or complaint) write a direct, helpful reply. Do not include any preamble or sign-off."""


# Italian weekday/month names, indexed to match datetime.weekday() (Mon=0) and
# month-1. Hard-coded so the output never depends on the server's locale.
ITALIAN_DAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
ITALIAN_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
                  "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def format_italian_date(iso, today, with_relative=True):
    """Turn an ISO date ("YYYY-MM-DD") into "venerdì 26 giugno 2026 (domani)".

    The weekday and a relative descriptor (oggi/domani/ieri/tra N giorni) are
    computed here in Python so the LLM never has to do date arithmetic itself —
    that arithmetic is exactly what produced wrong weekdays ("sabato" for a
    Friday) before. Returns the raw string unchanged if it can't be parsed.
    """
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return iso or "?"
    label = f"{ITALIAN_DAYS[d.weekday()]} {d.day} {ITALIAN_MONTHS[d.month - 1]} {d.year}"
    if not with_relative:
        return label
    delta = (d - today).days
    if delta == 0:
        rel = "oggi"
    elif delta == 1:
        rel = "domani"
    elif delta == -1:
        rel = "ieri"
    elif delta > 1:
        rel = f"tra {delta} giorni"
    else:
        rel = f"{-delta} giorni fa"
    return f"{label} ({rel})"


def build_system_prompt(apartment_name, apartment_info, reservation):
    # Reservation and apartment context go in the system prompt so Claude has them
    # as standing background, separate from the conversation turns.
    res   = reservation["data"][0]
    rooms = res.get("rooms", [{}])[0]

    now_it = datetime.now(ZoneInfo("Europe/Rome"))
    today  = now_it.date()

    lines = [
        SYSTEM_PROMPT_BASE,
        "\n--- Current Date/Time (Italy) ---",
        f"Oggi è {format_italian_date(today.isoformat(), today, with_relative=False)}, "
        f"ore {now_it.strftime('%H:%M')} (ora italiana).",
        "\n--- Reservation Context ---",
        f"Apartment: {apartment_name}",
        # Weekday + relative day are precomputed so the model NEVER computes them
        # itself (it used to guess the wrong weekday).
        f"Check-in: {format_italian_date(res['arrival'], today)}",
        f"Check-out: {format_italian_date(res['departure'], today)}",
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
        content = msg["message"] or "[foto]"
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


def call_llm(system, messages):
    global _claude_consecutive_failures, _claude_paused_until
    try:
        if MODEL_PROVIDER == "deepseek":
            from openai import OpenAI
            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
            resp = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=1024,
                messages=[{"role": "system", "content": system}] + messages,
            )
            text = resp.choices[0].message.content
        else:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system,
                messages=messages,
            )
            text = msg.content[0].text
    except Exception:
        _claude_consecutive_failures += 1
        if _claude_consecutive_failures >= CLAUDE_FAILURE_THRESHOLD:
            _claude_paused_until = time.time() + CLAUDE_COOLDOWN
            log.error(
                f"[CIRCUIT] {_claude_consecutive_failures} consecutive LLM failures — "
                f"pausing LLM calls for {CLAUDE_COOLDOWN}s"
            )
        raise

    _claude_consecutive_failures = 0  # reset on any success
    return text


def extract_escalation(reply):
    # Returns the parsed escalation dict if Claude's reply contains the escalation
    # JSON, otherwise None. Robust against Claude wrapping the JSON in markdown
    # fences or stray text — we locate the first {...} block and parse that, so a
    # malformed wrapper never causes the raw JSON to leak to the guest.
    if not isinstance(reply, str):
        return None

    # Fast path: the whole reply is the JSON object.
    candidates = [reply.strip()]

    # Fallback: pull out the first {...} block found anywhere in the text.
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("action") == "escalate":
            return data
    return None


def is_escalation(reply):
    # Returns True if Claude responded with the escalation JSON instead of a reply.
    return extract_escalation(reply) is not None


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
def process_thread(thread, active_apartments):
    id_thread      = thread["id_thread"]
    id_reservation = thread["id_reservation"]
    apartment_name = thread["name_room_type"]

    # Whitelist gate: handle this apartment only if the host has activated it in
    # the dashboard. active_apartments is read once per cycle in main().
    if apartments_store.safe_filename(apartment_name) not in active_apartments:
        return "skip"

    # Pre-filter: last_message_from_name comes free from get_threads() with no extra API call.
    # If the last message was sent by a known host, the host already replied — nothing to do.
    if thread.get("last_message_from_name") in KNOWN_HOSTS:
        return "skip"

    # Fix 2: skip threads with nothing new since we last handled them. get-threads
    # returns each thread's last_update for free; if it matches the value we stored
    # after fully handling this thread, no message changed and we avoid the
    # expensive get-thread call. This is what stops permanently to_read threads
    # (host replied via Airbnb/Booking, which never clears to_read) from costing a
    # get-thread call every single cycle.
    last_update = thread.get("last_update")
    if last_update and storage.get_thread_last_seen(id_thread) == last_update:
        return "skip"

    log.info(f"Thread {id_thread} ({apartment_name})")

    time.sleep(20)  # avoid hitting Kross rate limits on sequential get-thread calls
    detail       = get_thread(id_thread)
    all_messages = list(reversed(detail["data"]))  # chronological order, built once

    # Defensive filter: only include guest messages with to_read=True that have no
    # owner/cohost reply after them — guards against replying to already-handled messages
    # when Teo/Nico replied from the Airbnb/Booking app (which doesn't update to_read in Kross).
    unread_guest_msgs = []
    for i, m in enumerate(all_messages):
        if m["user_role"] == "guest" and m["to_read"]:
            has_reply_after = any(
                all_messages[j]["user_role"] in ("owner", "cohost")
                for j in range(i + 1, len(all_messages))
            )
            if not has_reply_after:
                unread_guest_msgs.append(m)

    if not unread_guest_msgs:
        log.info("    → Skipped (already handled)")
        return "skip"

    # If any unread guest message has no text, it's a photo — Claude can't see images,
    # so escalate the whole thread and let the host handle it.
    if any(not m.get("message") for m in unread_guest_msgs):
        photo_msg = next(m for m in unread_guest_msgs if not m.get("message"))

        # Dedup BEFORE fetching the reservation — already-notified photos cost nothing.
        if storage.notification_exists(id_thread, photo_msg["id_message"]):
            log.info("    → Photo already notified — skipping")
            return "duplicate"

        reservation = get_reservation(id_reservation)
        res         = reservation["data"][0]
        log.info(f"    Ospite: {res['label']} | Check-in: {res['arrival']} | Check-out: {res['departure']}")
        log.info("    → Photo detected, notifying host")
        storage.record_notification({
            "id_thread":      id_thread,
            "id_message":     photo_msg["id_message"],
            "id_reservation": id_reservation,
            "category":       "intervento_host",
            "home":           apartment_name,
            "guest_name":     res["label"],
            "channel":        res.get("channel"),
            "check_in":       res["arrival"],
            "check_out":      res["departure"],
            "message":        "[foto]",
            "summary":        "L'ospite ha mandato una foto — intervento necessario.",
        })
        notify(
            f"📷 *{apartment_name}*\n"
            f"Ospite: *{photo_msg['from_first_name']}*\n"
            f"Check-in: *{fmt_date(res['arrival'])}* | Check-out: *{fmt_date(res['departure'])}*\n"
            f"Orario messaggio: {fmt_ts(photo_msg['created_at'])}\n"
            f"L'ospite ha mandato una foto. Controlla su Kross.",
            parse_mode="Markdown",
        )
        return "photo"

    # Dedup BEFORE any Claude call AND before the extra get_reservation Kross call.
    # Skip if we already escalated on this message OR already auto-replied to it.
    last_msg = unread_guest_msgs[-1]
    if (storage.notification_exists(id_thread, last_msg["id_message"])
            or storage.reply_exists(id_thread, last_msg["id_message"])):
        log.info("    → Already handled for this message — skipping")
        return "duplicate"

    # Circuit breaker: if Claude has been failing repeatedly, don't keep calling it.
    # The message stays unread, so it'll be retried once the cooldown elapses.
    if claude_circuit_open():
        log.warning("    → Claude paused (circuit breaker open) — skipping for now")
        return "skip"

    reservation = get_reservation(id_reservation)
    res         = reservation["data"][0]
    log.info(f"    Ospite: {res['label']} | Check-in: {res['arrival']} | Check-out: {res['departure']}")

    apartment_info = load_apartment_file(apartment_name)

    system = build_system_prompt(apartment_name, apartment_info, reservation)

    # Pass full history up to the last unread message — Claude sees the full context
    # and produces one aggregated reply instead of one reply per message.
    messages = build_conversation(all_messages, last_msg["id_message"])
    reply    = call_llm(system, messages)

    escalation_data = extract_escalation(reply)
    if escalation_data:
        reason   = escalation_data["reason"]
        # Use Claude's category if it provided one; fall back to the generic
        # intervento_host so the notification still appears under "Tutti".
        category = escalation_data.get("category", "intervento_host")
        if category not in ("riparazione", "checkin_checkout"):
            category = "intervento_host"

        log.info(f"    → Escalating ({category}): {reason}")
        storage.record_notification({
            "id_thread":      id_thread,
            "id_message":     last_msg["id_message"],
            "id_reservation": id_reservation,
            "category":       category,
            "home":           apartment_name,
            "guest_name":     res["label"],
            "channel":        res.get("channel"),
            "check_in":       res["arrival"],
            "check_out":      res["departure"],
            "message":        last_msg["message"],
            "summary":        reason,
        })
        notify_escalation(apartment_name, res["label"], res["arrival"], res["departure"], last_msg["created_at"], last_msg["message"], reason)
        return "escalate"
    else:
        log.info(f"    → Replying: {reply[:80]}...")
        try:
            send_message(id_thread, reply)
        except requests.HTTPError as e:
            # A 400 on send-message is not transient: it almost always means the
            # OTA conversation is closed / read-only (thread closed after
            # check-out, cancelled reservation, or a channel that doesn't accept
            # outbound messages). Retrying every cycle would fail forever and spam
            # the host with the generic error notification. Instead, escalate this
            # message ONCE (deduped on id_thread+id_message via the notifications
            # table) and return a non-error outcome so main() records the thread as
            # seen and skips it until a genuinely new guest message arrives.
            if e.response is not None and e.response.status_code == 400:
                detail = {}
                try:
                    detail = e.response.json()
                except ValueError:
                    pass
                kross_msg = detail.get("error_message", "Bad Request") if isinstance(detail, dict) else "Bad Request"
                reason = (
                    "Risposta automatica non inviata (errore 400 — conversazione "
                    f"probabilmente chiusa o di sola lettura). Kross: {kross_msg}. "
                    "Rispondi manualmente su Kross/OTA."
                )
                log.error(f"    → send-message 400 — escalating to host instead of retrying: {kross_msg}")
                storage.record_notification({
                    "id_thread":      id_thread,
                    "id_message":     last_msg["id_message"],
                    "id_reservation": id_reservation,
                    "category":       "intervento_host",
                    "home":           apartment_name,
                    "guest_name":     res["label"],
                    "channel":        res.get("channel"),
                    "check_in":       res["arrival"],
                    "check_out":      res["departure"],
                    "message":        last_msg["message"],
                    "summary":        reason,
                })
                notify_escalation(
                    apartment_name, res["label"], res["arrival"], res["departure"],
                    last_msg["created_at"], last_msg["message"], reason,
                )
                return "send_failed"
            raise
        # Record the reply so we don't re-call Claude for this same message next
        # cycle if Kross hasn't yet reflected our sent reply in the thread history.
        storage.record_reply(id_thread, last_msg["id_message"])
        return "reply"


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    global _token

    log.info("Starting Kross Autoresponder...")
    _token = get_auth_token()
    log.info("Authenticated.")
    storage.init_db()

    while True:
        cycle_start = time.time()
        stats = Counter()
        try:
            # Re-read the whitelist every cycle so dashboard changes take effect
            # without restarting the bot.
            active_apartments = active_store.get_active()
            threads = get_threads()
            unread  = threads["data"]
            # Match the whitelist gate in process_thread: sanitize the Kross name
            # before comparing, so houses whose name_room_type contains a
            # filesystem-unsafe char (e.g. "Fantoni 1/I" → "Fantoni 1-I") are
            # counted correctly here too.
            active  = [
                t for t in unread
                if apartments_store.safe_filename(t.get("name_room_type", "")) in active_apartments
            ]
            log.info(f"Polling — {len(unread)} unread thread(s) total, {len(active)} in active apartments.")

            for thread in unread:
                try:
                    outcome = process_thread(thread, active_apartments) or "skip"
                    stats[outcome] += 1
                    # Fix 2: record the thread's current last_update only after a
                    # clean (non-error) outcome, so next cycle skips it unless a new
                    # message arrives. On error we deliberately skip recording so the
                    # thread is retried.
                    if thread.get("last_update"):
                        storage.record_thread_seen(thread["id_thread"], thread["last_update"])
                except Exception as e:
                    stats["error"] += 1
                    log.exception(f"Error on thread {thread['id_thread']}: {e}")
                    notify_error(thread.get("name_room_type", f"thread {thread['id_thread']}"), e)

        except Exception as e:
            stats["error"] += 1
            log.exception(f"Error polling: {e}")

        duration = time.time() - cycle_start
        log.info(
            f"[CYCLE] done in {duration:.1f}s — "
            f"replies={stats['reply']} escalations={stats['escalate']} "
            f"photos={stats['photo']} duplicates={stats['duplicate']} "
            f"send_failed={stats['send_failed']} "
            f"skipped={stats['skip']} errors={stats['error']}"
        )
        log.info(f"Sleeping {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
