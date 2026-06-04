"""
Kross API smoke tests — run from the project root:
    python tests/test_kross.py

Checks: authentication, get-threads, get-thread detail, get-reservation.
Only looks at Pellegrini 26 threads.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import script

APARTMENT = "Pellegrini 26"

print("=== 1. Authentication ===")
script._token = script.get_auth_token()
print(f"Token: {script._token[:20]}...")

print("\n=== 2. Get threads ===")
threads_resp = script.get_threads()
all_threads = threads_resp["data"]
print(f"Total unread threads: {len(all_threads)}")
for t in all_threads:
    print(f"  [{t['id_thread']}] {t['name_room_type']}  reservation={t['id_reservation']}")

pellegrini_threads = [t for t in all_threads if t["name_room_type"] == APARTMENT]
print(f"\nPellegrini 26 unread threads: {len(pellegrini_threads)}")

if not pellegrini_threads:
    print("No unread Pellegrini 26 threads right now — skipping steps 3 & 4.")
    sys.exit(0)

thread = pellegrini_threads[0]
id_thread      = thread["id_thread"]
id_reservation = thread["id_reservation"]

print(f"\n=== 3. Get thread detail (id_thread={id_thread}) ===")
detail = script.get_thread(id_thread)
messages = list(reversed(detail["data"]))  # chronological
print(f"Messages in thread: {len(messages)}")
for m in messages:
    flag = " [UNREAD]" if m.get("to_read") else ""
    role = (m['user_role'] or 'none')
    text = (m['message'] or '')[:80]
    print(f"  [{role:6}]{flag} {text}")

print(f"\n=== 4. Get reservation (id_reservation={id_reservation}) ===")
reservation = script.get_reservation(id_reservation)
res   = reservation["data"][0]
rooms = res.get("rooms", [{}])[0]
print(f"Guest:    {res['label']}")
print(f"Check-in: {res['arrival']}  Check-out: {res['departure']}")
print(f"Guests:   {rooms.get('qt_guests', '?')}")
print(f"Language: {res.get('lang', '?')}")
if res.get("note"):
    print(f"Notes:    {res['note']}")
