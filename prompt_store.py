"""
Shared access layer for the bot's system prompt (system_prompt.md).

Same role as apartments_store.py, but for the single global prompt instead of
per-apartment files:
- the bot (script.py) READS it on every reply, as the base of Claude's system
  prompt (dynamic reservation/apartment context is appended after it);
- the host web app (web/main.py) READS and EDITS it.

No default/fallback text lives in code: if the file is missing, read_prompt()
raises so the caller finds out loudly (the bot's per-thread error handler in
script.py already turns that into a logged error + Telegram alert + retry on
the next cycle) rather than silently falling back to some baked-in prompt
nobody remembers exists.
"""
import os
from datetime import datetime

# Anchored to this module's location (repo root), NOT the process CWD.
PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_prompt.md")

# Backups live alongside the apartment backups' sibling pattern: a hidden
# subfolder next to the file itself.
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".prompt_backups")

# How many timestamped backups to keep before pruning the oldest.
MAX_BACKUPS = 20


def read_prompt():
    """Return the full text of the system prompt.

    Raises FileNotFoundError if system_prompt.md doesn't exist.
    """
    if not os.path.exists(PROMPT_PATH):
        raise FileNotFoundError(f"System prompt file not found: {PROMPT_PATH}")
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _backup_existing():
    """Copy the current file (if any) into BACKUP_DIR with a timestamp."""
    if not os.path.exists(PROMPT_PATH):
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"system_prompt.{stamp}.md")
    n = 1
    while os.path.exists(dst):
        dst = os.path.join(BACKUP_DIR, f"system_prompt.{stamp}-{n}.md")
        n += 1

    with open(PROMPT_PATH, encoding="utf-8") as fsrc:
        data = fsrc.read()
    with open(dst, "w", encoding="utf-8") as fdst:
        fdst.write(data)

    _prune_backups()
    return dst


def _prune_backups():
    """Keep only the most recent MAX_BACKUPS backups."""
    try:
        backups = sorted(
            f for f in os.listdir(BACKUP_DIR)
            if f.startswith("system_prompt.") and f.endswith(".md")
        )
    except OSError:
        return
    for old in backups[:-MAX_BACKUPS]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass


def write_prompt(content):
    """Overwrite the system prompt, after backing up the previous version.

    Refuses empty/whitespace-only content. Returns the backup path created
    (or None if there was no prior file).
    """
    if not content or not content.strip():
        raise ValueError("Refusing to save an empty system prompt.")

    content = content.replace("\r\n", "\n").replace("\r", "\n")

    backup = _backup_existing()
    with open(PROMPT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    return backup
