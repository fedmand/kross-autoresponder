"""
Claude smoke test — run from the project root:
    python tests/test_claude.py

Loads the Pellegrini 26 apartment file, builds a fake reservation context,
then calls Claude with a sample guest message and prints the reply.
Lets you verify the prompt, apartment info, and Claude response quality.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import script

APARTMENT = "Pellegrini 26"

# Simulated guest messages to test — change freely
SAMPLE_MESSAGES = [
    "Hi! What time can we check in?",
    "Is there parking nearby?",
    "The wifi isn't working, what do we do?",
    "Can we have an early check-in at 10am?",
    "L'appartamento si trova in ZTL?",
    "Ho seguito tutto quello che mi hai detto per il wifi ma non funziona ancora!",
    "Che cazzo stai dicendo??? Non funziona!!!",
    "La porta non si apre",
    "La casa è pronta?"
]

print("=== 1. Load apartment file ===")
info = script.load_apartment_file(APARTMENT)
print(f"Loaded {len(info)} chars from apartments/{APARTMENT}.md")
print(f"Preview: {info[:200]}\n")

# Fake reservation (no real Kross call needed)
fake_reservation = {
    "data": [{
        "arrival":    "2026-05-14",
        "departure":  "2026-05-18",
        "label":      "Test Guest",
        "lang":       "en",
        "note":       "",
        "rooms": [{"qt_guests": 2}],
    }]
}

system = script.build_system_prompt(APARTMENT, info, fake_reservation)
print("=== 2. System prompt ===")
print(system)

print("\n=== 3. Claude replies ===")
for msg_text in SAMPLE_MESSAGES:
    messages = [{"role": "user", "content": msg_text}]
    reply = script.call_anthropic(system, messages)
    escalated = script.is_escalation(reply)
    print(f"\nGuest: {msg_text}")
    if escalated:
        reason = json.loads(reply.strip())["reason"]
        print(f"[ESCALATE] {reason}")
        script.notify_escalation(APARTMENT, fake_reservation["data"][0]["arrival"], fake_reservation["data"][0]["departure"], msg_text, reason)
        print("→ Notifica Telegram inviata.")
    else:
        print(f"[REPLY] {reply}")



