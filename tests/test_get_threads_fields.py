"""
TEST: verifica il parametro last_update di get-threads.

Obiettivo: invece di chiamare get_threads(to_read=True) e ricevere 1000 thread storici,
passare last_update=<timestamp ultimo poll> e ricevere SOLO i thread aggiornati di recente.
Se funziona, riduce i thread da 1000 a ~0-10 per ciclo, eliminando il problema del rate limit
e l'accumulo di thread vecchi.

Il test chiama get-threads con tre varianti:
1. Senza filtri (baseline)
2. Con last_update = 1 ora fa
3. Con last_update = 10 minuti fa

e stampa quanti thread ritorna ciascuna variante.
"""
import sys, os, requests
from datetime import datetime, timedelta
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

def get_threads(payload):
    resp = requests.post("https://api.krossbooking.com/v5/messaging/get-threads",
        json=payload, headers=headers).json()
    return resp

def ts(minutes_ago):
    dt = datetime.now() - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# ── Test 1: nessun filtro ─────────────────────────────────────────────────────
print("TEST 1 — nessun filtro (baseline)")
resp = get_threads({})
print(f"  total_count={resp.get('total_count')}  count={resp.get('count')}")
print(f"  Primo thread: id_thread={resp['data'][0]['id_thread']}  last_update={resp['data'][0].get('last_update')}\n")

# ── Test 2: last_update = 1 ora fa ────────────────────────────────────────────
print(f"TEST 2 — last_update = 1 ora fa ({ts(60)})")
resp2 = get_threads({"last_update": ts(60)})
print(f"  total_count={resp2.get('total_count')}  count={resp2.get('count')}")
if resp2.get("data"):
    for t in resp2["data"][:5]:
        print(f"    id_thread={t['id_thread']}  apartment={t.get('name_room_type')}  last_update={t.get('last_update')}  last_msg_from={t.get('last_message_from_name')}")
else:
    print("  Nessun thread.")
print()

# ── Test 3: last_update = 10 minuti fa ───────────────────────────────────────
print(f"TEST 3 — last_update = 10 minuti fa ({ts(10)})")
resp3 = get_threads({"last_update": ts(10)})
print(f"  total_count={resp3.get('total_count')}  count={resp3.get('count')}")
if resp3.get("data"):
    for t in resp3["data"][:5]:
        print(f"    id_thread={t['id_thread']}  apartment={t.get('name_room_type')}  last_update={t.get('last_update')}  last_msg_from={t.get('last_message_from_name')}")
else:
    print("  Nessun thread.")
print()

# ── Test 4: last_update + to_read=True (combinato) ───────────────────────────
print(f"TEST 4 — last_update 1h fa + to_read=True (combinato)")
resp4 = get_threads({"last_update": ts(60), "to_read": True})
print(f"  total_count={resp4.get('total_count')}  count={resp4.get('count')}")
if resp4.get("data"):
    for t in resp4["data"][:5]:
        print(f"    id_thread={t['id_thread']}  to_read={t.get('to_read')}  last_update={t.get('last_update')}")
else:
    print("  Nessun thread.")
