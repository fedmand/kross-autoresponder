"""
DIAGNOSTICA (sola lettura): perché send-message fallisce con 400 su un thread?

Dato un id_thread, stampa:
- la riga del thread in get-threads (canale, to_read, last_update, ...)
- l'intera cronologia messaggi (get-thread)
- i dati della reservation collegata (get-reservation): canale, stato, date, ...

NON invia mai messaggi: usa solo endpoint di lettura, quindi è sicuro da lanciare
in produzione. Serve a capire la causa del 400 (es. conversazione OTA chiusa dopo
il check-out, canale che non supporta l'invio, prenotazione cancellata, ecc.).

Uso (sul VPS, dentro la cartella del progetto):
  source venv/bin/activate
  python tests/script/diagnose_thread.py 10216
"""
import os
import sys
import json
import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

BASE_URL = "https://api.krossbooking.com/v5"

ID_THREAD = int(sys.argv[1]) if len(sys.argv) > 1 else 10216


def pp(label, data):
    print(f"\n{'=' * 70}\n  {label}\n{'=' * 70}")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ── Auth ──────────────────────────────────────────────────────────────────────
r = requests.post(f"{BASE_URL}/auth/get-token", json={
    "api_key":  os.getenv("KROSS_API_KEY"),
    "hotel_id": os.getenv("KROSS_HOTEL_ID"),
    "username": os.getenv("KROSS_USERNAME"),
    "password": os.getenv("KROSS_PASSWORD"),
})
r.raise_for_status()
token = r.json()["auth_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def post(endpoint, payload):
    resp = requests.post(f"{BASE_URL}{endpoint}", json=payload, headers=headers)
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text}
    return resp.status_code, body


print(f"\n### Diagnostica thread {ID_THREAD} (sola lettura) ###")

# ── 1. Riga del thread nella lista get-threads ────────────────────────────────
# Cerchiamo il thread sia tra i to_read che tra tutti, per vedere i metadati
# che il bot riceve "gratis" (canale, last_message_from_name, last_update).
status, threads = post("/messaging/get-threads", {})
match = None
if isinstance(threads, dict) and isinstance(threads.get("data"), list):
    match = next((t for t in threads["data"] if t.get("id_thread") == ID_THREAD), None)
if match:
    pp("get-threads — riga di questo thread", match)
else:
    print(f"\n[get-threads] thread {ID_THREAD} non trovato nella lista (status={status})")

# ── 2. Cronologia completa del thread ─────────────────────────────────────────
status, thread = post("/messaging/get-thread", {"id_thread": ID_THREAD})
print(f"\n[get-thread] HTTP {status}")
if isinstance(thread, dict) and isinstance(thread.get("data"), list):
    msgs = list(reversed(thread["data"]))  # ordine cronologico
    print(f"  {len(msgs)} messaggi nel thread:")
    for m in msgs:
        snippet = (m.get("message") or "[no text / foto]")[:70].replace("\n", " ")
        print(f"    [{m.get('user_role'):7}] to_read={str(m.get('to_read')):5} "
              f"{m.get('created_at')}  {snippet}")
    if msgs:
        pp("get-thread — tutti i campi dell'ULTIMO messaggio", msgs[-1])
    id_reservation = match.get("id_reservation") if match else None
    if not id_reservation and thread["data"]:
        id_reservation = thread["data"][0].get("id_reservation")
else:
    pp("get-thread — risposta", thread)
    id_reservation = match.get("id_reservation") if match else None

# ── 3. Reservation collegata ──────────────────────────────────────────────────
if id_reservation:
    status, res = post("/reservations/get-list",
                       {"id_reservation": id_reservation, "with_rooms": True})
    print(f"\n[get-reservation] HTTP {status} (id_reservation={id_reservation})")
    if isinstance(res, dict) and res.get("data"):
        pp("get-reservation — data[0]", res["data"][0])
    else:
        pp("get-reservation — risposta", res)
else:
    print("\n[get-reservation] nessun id_reservation disponibile per questo thread")

print("\n### Fine diagnostica — nessun messaggio inviato ###")
