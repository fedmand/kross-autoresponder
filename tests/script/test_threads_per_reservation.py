"""
TEST 1 — distribuzione thread per reservation (statistiche generali)
TEST 2 — ispezione di una reservation con piu thread
         Stampa tutti i messaggi di ogni thread cosi' puoi confrontare con Kross
         e capire se i thread corrispondono a qualcosa di semanticamente diverso.
"""
import sys, os, requests
from collections import defaultdict, Counter
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

# ── get-threads ───────────────────────────────────────────────────────────────
all_threads = requests.post("https://api.krossbooking.com/v5/messaging/get-threads",
    json={"to_read": True}, headers=headers).json()["data"]

print(f"Totale thread to_read=True: {len(all_threads)}\n")

# ── TEST 1: statistiche ───────────────────────────────────────────────────────
by_reservation = defaultdict(list)
for t in all_threads:
    by_reservation[t["id_reservation"]].append(t)

none_threads = by_reservation.pop(None, [])
counts = sorted(len(t) for t in by_reservation.values())
dist = Counter(counts)

print(f"Reservation univoche (1 thread):  {sum(1 for c in counts if c == 1)}")
print(f"Reservation con piu thread:       {sum(1 for c in counts if c > 1)}")
print(f"Thread nel gruppo None:           {len(none_threads)}")
print(f"\nDistribuzione:")
for n, cnt in sorted(dist.items()):
    print(f"  {n} thread -> {cnt} reservation(s)")
print(f"Media: {sum(counts)/len(counts):.2f}  |  Max: {max(counts)}")

# ── TEST 2: ispezione reservation con piu thread ──────────────────────────────
multi = {r: t for r, t in by_reservation.items() if len(t) > 1}
if not multi:
    print("\nNessuna reservation con piu thread trovata.")
    exit()

# Prendi la prima reservation con piu thread
res_id, threads = list(multi.items())[1]  # cambia indice per vedere reservation diverse
print(f"\n{'=' * 60}")
print(f"TEST 2 — reservation con piu thread")
print(f"id_reservation: {res_id}  |  {len(threads)} thread(s)")

# Info identificative dalla reservation
res_data = requests.post("https://api.krossbooking.com/v5/reservations/get-list",
    json={"id_reservation": res_id, "with_rooms": True}, headers=headers).json()["data"][0]
print(f"Ospite:    {res_data['label']}")
print(f"Checkin:   {res_data['arrival']}  |  Checkout: {res_data['departure']}")
print(f"Apartment: {res_data['rooms'][0]['name_room_type']}")
print(f"Canale:    {res_data['channel']}  |  Codice: {res_data.get('reservation_confirmation_code') or res_data.get('ota_id', '?')}")
print(f"{'=' * 60}")

# Stampa tutti i messaggi di ogni thread
for i, thread in enumerate(threads):
    print(f"\n--- THREAD {i+1}/{len(threads)}  id_thread={thread['id_thread']}  to_read={thread['to_read']} ---")
    print(f"    last_message_from_name: {thread.get('last_message_from_name')}")
    print(f"    last_message_created_at: {thread.get('last_message_created_at')}")

    messages = requests.post("https://api.krossbooking.com/v5/messaging/get-thread",
        json={"id_thread": thread["id_thread"]}, headers=headers).json()["data"]
    messages = list(reversed(messages))  # cronologico

    print(f"    Messaggi ({len(messages)} totali):")
    for m in messages:
        role    = m.get("user_role", "?")
        to_read = m.get("to_read")
        ts      = m.get("created_at", "")[:16]
        text    = (m.get("message") or "[foto]")[:100].replace("\n", " ").replace("\r", " ")
        print(f"      [{str(role or '?'):8}] {ts}  to_read={str(to_read):5}  {text}")
