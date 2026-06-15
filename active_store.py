"""
Shared store for the set of apartments the bot is allowed to handle.

This used to be a hard-coded constant (ACTIVE_APARTMENTS) in script.py, which
meant onboarding a house required a code edit + redeploy. It now lives in a small
JSON file that both sides touch:
- the bot (script.py) READS it at the start of every poll cycle, so toggling a
  house takes effect within one cycle, no restart needed;
- the host web app (web/main.py) READS and WRITES it from the dashboard.

Semantics (a "whitelist"): the bot handles a thread ONLY if its apartment is in
this set. An empty set therefore means "handle nothing" — deliberately safe, so
a missing/empty file can never cause the bot to suddenly answer all 40 houses.

The file is seeded once (from DEFAULT_ACTIVE) on first read so behaviour is
identical to the previous hard-coded list until the host changes it.
"""
import json
import os
import tempfile

# Anchored to this module's location (repo root), NOT the process CWD — mirrors
# apartments_store.py so the bot and web app always resolve the same file.
_HERE = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.path.join(_HERE, "active_apartments.json")

# Seed value: the apartments that were hard-coded in script.py before this store
# existed. On first run the file is created with exactly these, so nothing about
# the bot's behaviour changes until the host edits the list from the dashboard.
DEFAULT_ACTIVE = [
    "Costantino Nigra 29",
    "Pellegrini 26",
    "Petrella 4",
    "Terraggio 21",
]


def _read_raw():
    with open(STORE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    # Stored as a sorted list; tolerate a bare list too.
    if isinstance(data, dict):
        return data.get("active", [])
    return data


def _write_raw(names):
    # Atomic write so the bot never reads a half-written file mid-save.
    clean = sorted({n.strip() for n in names if n and n.strip()})
    fd, tmp = tempfile.mkstemp(dir=_HERE, prefix=".active_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"active": clean}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STORE_PATH)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return clean


def get_active():
    """Return the set of active apartment names.

    Seeds the file from DEFAULT_ACTIVE on first access (or if it is unreadable),
    so the bot keeps its previous behaviour out of the box.
    """
    try:
        return set(_read_raw())
    except (OSError, ValueError):
        _write_raw(DEFAULT_ACTIVE)
        return set(DEFAULT_ACTIVE)


def is_active(name):
    return name in get_active()


def set_active(names):
    """Replace the whole active set. Returns the stored sorted list."""
    return _write_raw(names)


def add_active(name):
    active = get_active()
    active.add(name)
    return _write_raw(active)


def remove_active(name):
    active = get_active()
    active.discard(name)
    return _write_raw(active)


def toggle_active(name):
    """Flip a single apartment's active state. Returns True if now active."""
    active = get_active()
    if name in active:
        active.discard(name)
        now_active = False
    else:
        active.add(name)
        now_active = True
    _write_raw(active)
    return now_active
