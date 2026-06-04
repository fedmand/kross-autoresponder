"""
TEST: mostra la risposta grezza dei 3 endpoint principali.
- get-threads: primo thread restituito (tutti i campi)
- get-thread:  primi 3 messaggi del thread sopra
- get-reservation: dati della reservation del thread sopra
"""
import sys, os, json, requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

# ── Auth ──────────────────────────────────────────────────────────────────────
r = requests.post("https://api.krossbooking.com/v5/auth/get-token", json={
    "api_key":  os.getenv("KROSS_API_KEY"),
    "hotel_id": os.getenv("KROSS_HOTEL_ID"),
    "username": os.getenv("KROSS_USERNAME"),
    "password": os.getenv("KROSS_PASSWORD"),
})
r.raise_for_status()
token = r.json()["auth_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def pp(label, data):
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print('=' * 60)
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))

# ── 1. get-threads ────────────────────────────────────────────────────────────
threads_resp = requests.post("https://api.krossbooking.com/v5/messaging/get-threads",
    json={"to_read": True}, headers=headers).json()

pp("get-threads — struttura top-level della risposta (senza data[])", {
    k: v for k, v in threads_resp.items() if k != "data"
})
pp("get-threads — primo thread in data[]", threads_resp["data"][0])

first_thread = threads_resp["data"][0]
id_thread      = first_thread["id_thread"]
id_reservation = first_thread["id_reservation"]

# ── 2. get-thread ─────────────────────────────────────────────────────────────
thread_resp = requests.post("https://api.krossbooking.com/v5/messaging/get-thread",
    json={"id_thread": id_thread}, headers=headers).json()

pp("get-thread — struttura top-level (senza data[])", {
    k: v for k, v in thread_resp.items() if k != "data"
})
pp(f"get-thread — primo messaggio in data[] (id_thread={id_thread})", thread_resp["data"][0])
if len(thread_resp["data"]) > 1:
    pp("get-thread — secondo messaggio", thread_resp["data"][1])

# ── 3. get-reservation ────────────────────────────────────────────────────────
if id_reservation:
    res_resp = requests.post("https://api.krossbooking.com/v5/reservations/get-list",
        json={"id_reservation": id_reservation, "with_rooms": True}, headers=headers).json()

    pp("get-reservation — struttura top-level (senza data[])", {
        k: v for k, v in res_resp.items() if k != "data"
    })
    pp(f"get-reservation — data[0] (id_reservation={id_reservation})", res_resp["data"][0])
else:
    print("\n[get-reservation skipped — id_reservation is None per questo thread]")
