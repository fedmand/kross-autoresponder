"""
Structured house knowledge-base store (form-managed houses).

This sits on top of apartments_store and adds the "fill a form, auto-generate the
prompt" workflow the host asked for:

- SOURCE OF TRUTH: one JSON per house in houses/<name>.json — the values the host
  typed into the 23-category form (house_schema.SCHEMA).
- GENERATED ARTIFACT: apartments/<name>.md — produced deterministically from that
  JSON by render_markdown() (no LLM, so access codes / WiFi passwords are copied
  verbatim) and written through apartments_store so it gets the same backups and
  the bot picks it up unchanged on its next cycle.

A house is "form-managed" iff it has a houses/<name>.json. Only NEW houses created
through this flow get one; the existing hand-written apartment files have no JSON
and keep using the legacy raw-markdown editor, so their content is never touched.
"""
import os
import json

import house_schema as schema
import apartments_store

HOUSES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "houses")

MD_HEADER = (
    "# 🤖 CLAUDE AI GUEST ASSISTANT KNOWLEDGE BASE\n\n"
    "> Optimized operational guide for Claude AI guest support.\n"
)


def _json_path(name):
    # Reuse apartments_store's sanitization so JSON and .md share one stem.
    return os.path.join(HOUSES_DIR, f"{apartments_store.safe_filename(name)}.json")


# ── Form-managed detection & loading ──────────────────────────────────────────
def is_form_managed(name):
    return os.path.exists(_json_path(name))


def load_house(name):
    """Return the house's form data, normalized so every schema category/field is
    present (empty string when unset). None if the house isn't form-managed."""
    path = _json_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    return _normalize(data, name)


def _normalize(data, name):
    base = schema.empty_house()
    base["name"] = data.get("name") or name
    stored = data.get("categories", {})
    for cat in schema.SCHEMA:
        cid = cat["id"]
        scat = stored.get(cid, {}) if isinstance(stored, dict) else {}
        sfields = scat.get("fields", {}) if isinstance(scat, dict) else {}
        base["categories"][cid]["fields"] = {
            label: (sfields.get(label, "") or "") for label in cat["fields"]
        }
        base["categories"][cid]["instructions"] = (
            scat.get("instructions", "") if isinstance(scat, dict) else ""
        ) or ""
    return base


# ── Persistence ───────────────────────────────────────────────────────────────
def _write_json(data):
    os.makedirs(HOUSES_DIR, exist_ok=True)
    with open(_json_path(data["name"]), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def init_house(name):
    """Mark a freshly-created house as form-managed: write an empty JSON and an
    initial (header-only) markdown so the editor and the bot agree from the start.
    The apartment .md file must already exist (apartments_store.create_apartment)."""
    data = schema.empty_house()
    data["name"] = name
    _write_json(data)
    _write_markdown(name, render_markdown(data))


def save_form(name, form):
    """Build the house data from submitted form values, persist the JSON, and
    regenerate the apartment .md (with backup). Returns (data, markdown)."""
    data = build_from_form(name, form)
    _write_json(data)
    md = render_markdown(data)
    _write_markdown(name, md)
    return data, md


def _write_markdown(name, md):
    # Delegate to apartments_store so we inherit its backup + path handling. It
    # refuses to create a non-existent file, so fall back to create on first use.
    if apartments_store.apartment_exists(name):
        apartments_store.write_apartment(name, md)
    else:
        apartments_store.create_apartment(name, md)


# ── Deterministic markdown renderer ───────────────────────────────────────────
def _clean(value):
    # Collapse internal whitespace/newlines so a value stays in one table cell.
    return " ".join((value or "").split())


def render_markdown(data):
    """Turn the filled form into the structured prompt. Empty fields and
    fully-empty categories are omitted entirely."""
    categories = data.get("categories", {})
    blocks = [MD_HEADER]

    for cat in schema.SCHEMA:
        cdata = categories.get(cat["id"], {})
        fields = cdata.get("fields", {}) if isinstance(cdata, dict) else {}
        instructions = (cdata.get("instructions") or "").strip() if isinstance(cdata, dict) else ""

        filled = []
        for label in cat["fields"]:
            v = fields.get(label)
            if v and v.strip():
                filled.append((label, _clean(v)))

        if not filled and not instructions:
            continue

        section = [f"# {cat['title'].upper()}\n"]
        if filled:
            value_header = cat.get("value_label", "VALUE")
            section.append(f"| FIELD | {value_header} |")
            section.append("|---|---|")
            for label, value in filled:
                section.append(f"| {label} | {value} |")
            section.append("")
        if instructions:
            for line in instructions.splitlines():
                line = line.strip()
                if line:
                    section.append(f"> {line}")
            section.append("")

        blocks.append("\n".join(section).rstrip() + "\n")

    return ("\n---\n\n".join(blocks)).rstrip() + "\n"


# ── Form (de)serialization helpers ────────────────────────────────────────────
def field_input_name(category_id, index):
    return f"f__{category_id}__{index}"


def instructions_input_name(category_id):
    return f"i__{category_id}"


def build_from_form(name, form):
    """Build a normalized house dict from submitted form values (a Mapping)."""
    data = schema.empty_house()
    data["name"] = (name or "").strip()
    for cat in schema.SCHEMA:
        cid = cat["id"]
        for idx, label in enumerate(cat["fields"]):
            value = form.get(field_input_name(cid, idx), "")
            data["categories"][cid]["fields"][label] = (value or "").strip()
        instr = form.get(instructions_input_name(cid), "")
        data["categories"][cid]["instructions"] = (instr or "").strip()
    return data


def form_view(data):
    """Shape the data for the template: a list of categories with their fields
    (label, value, input_name) and instructions (text, input_name, label)."""
    categories = data.get("categories", {})
    view = []
    for cat in schema.SCHEMA:
        cid = cat["id"]
        cdata = categories.get(cid, {})
        fields = cdata.get("fields", {}) if isinstance(cdata, dict) else {}
        rows = [
            {
                "label": label,
                "value": fields.get(label, ""),
                "input_name": field_input_name(cid, idx),
            }
            for idx, label in enumerate(cat["fields"])
        ]
        view.append({
            "id": cid,
            "title": cat["title"],
            "value_label": cat.get("value_label", "VALUE"),
            "free_text": cat.get("free_text", False),
            "fields": rows,
            "instructions": cdata.get("instructions", "") if isinstance(cdata, dict) else "",
            "instructions_name": instructions_input_name(cid),
            "instructions_label": schema.instructions_label(cat),
        })
    return view
