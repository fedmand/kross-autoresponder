"""
Telegram smoke test — run from the project root:
    python tests/test_telegram.py

Sends a test message, a simulated escalation, and a simulated error
to your Telegram chat so you can verify the bot token and chat ID are correct.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import script

print("=== 1. Plain notification ===")
script.notify("Test from Kross Autoresponder — Telegram is working.")
print("Sent.")

print("\n=== 2. Escalation notification ===")
script.notify_escalation(
    apartment_name="Pellegrini 26",
    guest_message="Can I check in at 6am? I have an early flight.",
    reason="Early check-in request requires host confirmation",
)
print("Sent.")

print("\n=== 3. Error notification ===")
script.notify_error(
    apartment_name="Pellegrini 26",
    error="FileNotFoundError: No apartment file found (simulated)",
)
print("Sent.")

print("\nAll done — check your Telegram.")
