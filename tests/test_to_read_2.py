"""
Simula la chiamata del bot: get-threads con to_read=True, poi ispeziona
il primo thread restituito per vedere se ci sono messaggi guest to_read=True
a cui Teo/Nico hanno già risposto.
"""
import os, requests
from dotenv import load_dotenv

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

# ── Stessa chiamata che fa il bot ─────────────────────────────────────────────
all_threads = requests.post("https://api.krossbooking.com/v5/messaging/get-threads",
    json={"to_read": True}, headers=headers).json()["data"]

threads = [t for t in all_threads if t.get("name_room_type") == "Pellegrini 26"]
print(f"{len(threads)} thread(s) Pellegrini 26 con to_read=True")
if not threads:
    print("Nessun thread.")
    exit()

thread = threads[5]
res = requests.post("https://api.krossbooking.com/v5/reservations/get-list",
    json={"id_reservation": thread["id_reservation"], "with_rooms": True},
    headers=headers).json()["data"][0]
print(f"\nThread {thread['id_thread']} | {thread['name_room_type']}")
print(f"Ospite: {res['label']} | Check-in: {res['arrival']} | Check-out: {res['departure']}\n")

messages = requests.post("https://api.krossbooking.com/v5/messaging/get-thread",
    json={"id_thread": thread["id_thread"]}, headers=headers).json()["data"]

for m in reversed(messages):  # chronological order
    snippet = (m.get("message") or "[vuoto/foto]")[:55].replace("\n", " ").replace("\r", " ")
    role = repr(m.get("user_role"))  # repr() mostra None vs "" vs "guest" chiaramente
    internal = m.get("internal")
    print(f"[{role:10}] to_read={str(m['to_read']):5}  internal={str(internal):5}  {snippet}")
