"""
Diagnostica: quanti thread restituisce get-threads con to_read=True?
Breakdown per appartamento e per anno di check-in.
"""
import os, requests
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

r = requests.post("https://api.krossbooking.com/v5/auth/get-token", json={
    "api_key":  os.getenv("KROSS_API_KEY"),
    "hotel_id": os.getenv("KROSS_HOTEL_ID"),
    "username": os.getenv("KROSS_USERNAME"),
    "password": os.getenv("KROSS_PASSWORD"),
})
r.raise_for_status()
token = r.json()["auth_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

threads = requests.post("https://api.krossbooking.com/v5/messaging/get-threads",
    json={"to_read": True}, headers=headers).json()["data"]

print(f"Totale thread con to_read=True: {len(threads)}\n")

by_apartment = Counter(t.get("name_room_type", "?") for t in threads)
print("Per appartamento:")
for apt, count in by_apartment.most_common():
    print(f"  {apt}: {count}")
