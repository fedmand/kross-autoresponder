"""
TEST: ispeziona tutti i thread restituiti da get-threads (to_read=True) per la
reservation di Lola (Cavour 5, 21/05-24/05/2026, id_reservation=5302).

Obiettivo:
- Quanti thread esistono per quella reservation?
- I 55 notifiche nell'app Kross corrispondono a 55 thread separati o a 55 messaggi in un thread?
- Il campo last_message_from_name e' affidabile? (confrontiamo con il vero ultimo messaggio di get-thread)
"""
import sys, os, requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

TARGET_RESERVATION_ID = 5302  # Lola, Cavour 5, 21/05-24/05/2026

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

# ── Tutti i thread to_read=True, filtrati per reservation ────────────────────
all_threads = requests.post("https://api.krossbooking.com/v5/messaging/get-threads",
    json={"to_read": True}, headers=headers).json()["data"]

lola_threads = [t for t in all_threads if t["id_reservation"] == TARGET_RESERVATION_ID]

print(f"Thread trovati per id_reservation={TARGET_RESERVATION_ID} (Lola, Cavour 5): {len(lola_threads)}\n")

for i, t in enumerate(lola_threads):
    print(f"=== THREAD {i+1}/{len(lola_threads)} ===")
    for k, v in t.items():
        print(f"  {k}: {v}")

    # ── Recupera i messaggi del thread ────────────────────────────────────────
    print(f"\n  Messaggi (get-thread, ordine cronologico):")
    messages = requests.post("https://api.krossbooking.com/v5/messaging/get-thread",
        json={"id_thread": t["id_thread"]}, headers=headers).json()["data"]
    messages = list(reversed(messages))  # cronologico

    for m in messages:
        role    = m.get("user_role", "?")
        to_read = m.get("to_read")
        text    = (m.get("message") or "[vuoto/foto]")[:100].replace("\n", " ").replace("\r", " ")
        print(f"    [{role:8}] to_read={str(to_read):5}  {text}")

    print()
