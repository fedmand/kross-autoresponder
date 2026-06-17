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

# Seed content for a brand-new apartment created from the web app. It is only a
# scaffold to get the host started — the file is non-empty so subsequent edits
# go through the normal write_apartment() path, and the bot has *some* context to
# work with until the host fills it in. {name} is the apartment's display name.
NEW_APARTMENT_TEMPLATE = """# {name}

<!-- Compila queste informazioni: l'assistente le userà per rispondere agli ospiti di questa casa. -->

## Indirizzo e accesso


## Wi-Fi


## Check-in / Check-out


## Elettrodomestici e istruzioni


## Regole della casa


## Parcheggio e trasporti


## Contatti e note
"""


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


def apartment_exists(apartment_name):
    """True if there is already a file on disk for this apartment."""
    return os.path.exists(apartment_path(apartment_name))


def _validate_new_name(apartment_name):
    """Return the cleaned display name, or raise ValueError if it is unusable.

    write_apartment() never had to validate names because it refused to create
    files — the name always came from an existing file. create_apartment() opens
    that door, so we guard against names that would produce an empty file, a
    hidden/dot file (e.g. ".", "..", or anything colliding with the .backups
    folder), or a name made up entirely of separator/illegal characters. Path
    traversal is already neutralized by safe_filename() (it strips / and \\).
    """
    name = (apartment_name or "").strip()
    if not name:
        raise ValueError("Il nome della casa è obbligatorio.")

    stem = safe_filename(name).strip()
    # Reject stems that collapse to nothing, that are only dots/dashes/spaces
    # (".", "..", "--", etc.), or that would create a hidden/dot file.
    if not stem or stem.startswith(".") or set(stem) <= {".", "-", " "}:
        raise ValueError(f"Nome casa non valido: {apartment_name!r}")
    return name


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


def delete_apartment(apartment_name):
    """Delete an apartment's .md file, backing it up first so a mistaken delete
    can be recovered from apartments/.backups/.

    Returns the backup path (or None if there was nothing to back up). Raises
    FileNotFoundError if there is no file for this apartment.
    """
    path = apartment_path(apartment_name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No apartment file found for '{apartment_name}' (expected: {path})"
        )
    backup = _backup_existing(apartment_name)
    os.remove(path)
    return backup


def create_apartment(apartment_name, content=None):
    """Create a brand-new apartment file (the web 'add house' flow).

    Unlike write_apartment(), this is the ONE place allowed to create a file
    that does not yet exist. Safety rules:
    - the name must pass _validate_new_name() (no empty / dot / traversal names);
    - it refuses to overwrite an existing apartment (use write_apartment to edit
      one) — raises FileExistsError so the caller can just open the editor;
    - when no content is given, the file is seeded with NEW_APARTMENT_TEMPLATE so
      it is never empty (the bot reads it as plain text on its next cycle).

    IMPORTANT: the filename must exactly match Kross's name_room_type for the bot
    to find it; the web layer sources names from real reservations to guarantee
    this. Returns the path created.
    """
    name = _validate_new_name(apartment_name)
    path = apartment_path(name)
    if os.path.exists(path):
        raise FileExistsError(f"La casa '{name}' esiste già.")

    if content is None or not content.strip():
        content = NEW_APARTMENT_TEMPLATE.format(name=name)
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    os.makedirs(APARTMENTS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
