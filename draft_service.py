"""
Drafts a guest-facing reply for the host web dashboard.

Given a pending notification (escalation) and a short instruction from the
host describing what to tell the guest, asks Claude to write the actual
guest-facing message — in the guest's own language, using the same apartment
knowledge base and system prompt tone the bot's own replies use — for the
host to review and send.

Deliberately separate from script.py (same reasoning as kross_client.py):
importing script.py would spin up the bot's logging setup and other
module-level side effects just to draft one message.
"""
import os

import anthropic
from dotenv import load_dotenv

import apartments_store
import prompt_store

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-4-6"


class DraftError(RuntimeError):
    """Raised when a reply draft can't be produced."""


def _build_system_prompt(notification):
    try:
        apartment_info = apartments_store.read_apartment(notification["home"])
    except FileNotFoundError:
        apartment_info = ""

    lines = [
        prompt_store.read_prompt(),
        "\n--- Reservation Context ---",
        f"Apartment: {notification['home']}",
        f"Guest: {notification.get('guest_name', '?')}",
        f"Check-in: {notification.get('check_in', '?')} | Check-out: {notification.get('check_out', '?')}",
    ]
    if apartment_info:
        lines.append(f"\n--- Apartment Information ---\n{apartment_info}")
    lines.append(
        "\n--- Task ---\n"
        "The host has already decided how to handle this guest's message and is "
        "giving you an instruction below on what to tell them. You are NOT deciding "
        "whether to escalate — ignore any escalation instructions above, they don't "
        "apply here. Write ONLY the guest-facing reply message itself, in the same "
        "language the guest used in their message below, matching the tone/style "
        "guidance above. Output nothing but the reply text: no JSON, no preamble, "
        "no explanation, no quotation marks around it."
    )
    return "\n".join(lines)


def draft_reply(notification, host_instruction):
    """Returns the drafted reply text for the host to review. Raises DraftError
    on any failure (missing API key, Claude error, missing prompt file, ...)."""
    if not host_instruction or not host_instruction.strip():
        raise DraftError("Scrivi prima un'istruzione su cosa rispondere.")

    try:
        system = _build_system_prompt(notification)
    except FileNotFoundError as exc:
        raise DraftError(f"Prompt di sistema mancante: {exc}") from exc

    guest_message = notification.get("message") or "[foto]"
    user_content = (
        f"Guest's message:\n{guest_message}\n\n"
        f"Host's instruction on what to answer:\n{host_instruction.strip()}"
    )
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        raise DraftError(f"Generazione bozza fallita: {exc}") from exc
