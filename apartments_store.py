"""
Shared access layer for the per-apartment knowledge-base files (apartments/*.md).

Both sides of the system touch these files:
- the bot (script.py) READS the matching file on every reply to build Claude's
  system prompt;
- the host web app (web/main.py) lists, READS and EDITS them.

Keeping the directory path and the filename sanitization in one module
guarantees the bot and the web app always resolve to the exact same file on
disk — regardless of the process's current working directory. The path is
anchored to this file's location, so it works whether the bot is launched from
the repo root, a systemd unit, or anywhere else.
"""
import os
import re

# Anchored to this module's location (repo root), NOT the process CWD.
APARTMENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apartments")

# Backups live in a hidden subfolder. It is never picked up by list_apartments()
# because that only matches *.md files directly inside APARTMENTS_DIR.
BACKUP_DIR = os.path.join(APARTMENTS_DIR, ".backups")

# How many timestamped backups to keep per apartment before pruning the oldest.
MAX_BACKUPS_PER_APARTMENT = 20


def safe_filename(apartment_name):
    """Map a display name to its on-disk stem.

    Apartment names can contain characters that are invalid in file paths
    (e.g. "Palestrina 4/B"). Replace any filesystem-unsafe char with "-".
    The bot and the web app MUST share this exact rule so they never read and
    write different copies of the same apartment.
    """
    return re.sub(r'[<>:"/\\|?*]', "-", apartment_name)


def apartment_path(apartment_name):
    """Absolute path to the .md file backing the given apartment."""
    return os.path.join(APARTMENTS_DIR, f"{safe_filename(apartment_name)}.md")


def list_apartments():
    """All managed apartments, derived from the .md files on disk (sorted)."""
    try:
        return sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(APARTMENTS_DIR)
            if f.endswith(".md") and os.path.isfile(os.path.join(APARTMENTS_DIR, f))
        )
    except OSError:
        return []


def read_apartment(apartment_name):
    """Return the full text of an apartment file.

    Raises FileNotFoundError if there is no file for this apartment.
    """
    path = apartment_path(apartment_name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No apartment file found for '{apartment_name}' (expected: {path})"
        )
    with open(path, encoding="utf-8") as f:
        return f.read()


def _backup_existing(apartment_name):
    """Copy the current file (if any) into BACKUP_DIR with a timestamp.

    Returns the backup path, or None if there was nothing to back up.
    """
    src = apartment_path(apartment_name)
    if not os.path.exists(src):
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)
    from datetime import datetime

    stem = safe_filename(apartment_name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"{stem}.{stamp}.md")
    # Avoid clobbering if two saves land in the same second.
    n = 1
    while os.path.exists(dst):
        dst = os.path.join(BACKUP_DIR, f"{stem}.{stamp}-{n}.md")
        n += 1

    with open(src, encoding="utf-8") as fsrc:
        data = fsrc.read()
    with open(dst, "w", encoding="utf-8") as fdst:
        fdst.write(data)

    _prune_backups(stem)
    return dst


def _prune_backups(stem):
    """Keep only the most recent MAX_BACKUPS_PER_APARTMENT backups for a stem."""
    try:
        backups = sorted(
            f for f in os.listdir(BACKUP_DIR)
            if f.startswith(f"{stem}.") and f.endswith(".md")
        )
    except OSError:
        return
    for old in backups[:-MAX_BACKUPS_PER_APARTMENT]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass


def write_apartment(apartment_name, content):
    """Overwrite an apartment file with new content, after backing up the old one.

    Safety rules (a bad edit reaches guests on the bot's next poll cycle):
    - the apartment must already exist (no creating brand-new houses from the web);
    - empty / whitespace-only content is rejected;
    - the previous version is always backed up first.

    Raises FileNotFoundError or ValueError on a rejected save. Returns the
    backup path that was created (or None if there was no prior file).
    """
    path = apartment_path(apartment_name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No apartment file found for '{apartment_name}' (expected: {path})"
        )
    if not content or not content.strip():
        raise ValueError("Refusing to save empty apartment info.")

    # Normalize line endings to \n; the bot reads these as plain text.
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    backup = _backup_existing(apartment_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return backup
