"""
Test: verify how Kross sets to_read on individual messages after a human reply.

Takes the oldest Pellegrini 26 thread (where Teo has likely already replied manually)
and prints each message with user_role + to_read, so we can confirm whether Kross
correctly sets to_read=False on guest messages that have already been answered.
"""
import os, requests
from dotenv import load_dotenv

load_dotenv()

APARTMENT = "Pellegrini 26"

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

# ── Get all threads, pick oldest Pellegrini 26 one ────────────────────────────
all_threads = requests.post("https://api.krossbooking.com/v5/messaging/get-threads",
    json={}, headers=headers).json()["data"]

pellegrini = [t for t in all_threads if t.get("name_room_type") == APARTMENT]
if not pellegrini:
    print(f"No threads found for '{APARTMENT}'")
    exit()

# Kross returns newest-first — last item is the oldest thread
thread = pellegrini[-1]
print(f"Thread {thread['id_thread']} | thread-level to_read={thread.get('to_read')}")

# ── Reservation details ───────────────────────────────────────────────────────
res_data = requests.post("https://api.krossbooking.com/v5/reservations/get-list",
    json={"id_reservation": thread["id_reservation"], "with_rooms": True},
    headers=headers).json()
res = res_data["data"][0]
print(f"Guest: {res['label']} | Check-in: {res['arrival']} | Check-out: {res['departure']}\n")

# ── Inspect messages ──────────────────────────────────────────────────────────
messages = requests.post("https://api.krossbooking.com/v5/messaging/get-thread",
    json={"id_thread": thread["id_thread"]}, headers=headers).json()["data"]

for m in reversed(messages):  # chronological order
    snippet = (m.get("message") or "")[:60].replace("\n", " ")
    print(f"[{m['user_role']:7}] to_read={str(m['to_read']):5}  {snippet}")

# Print all fields of the last message to see the full structure (timestamp etc.)
print("\n--- Full fields of last message ---")
for k, v in messages[0].items():
    print(f"  {k}: {v}")
