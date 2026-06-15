"""
Kross Autoresponder — Host dashboard (FastAPI).

Airbnb-style web dashboard for the host-intervention notifications produced by
the AI bot. Reads/writes the same SQLite store (storage.py) the bot uses; falls
back to the mock JSON when the DB doesn't exist yet (local dev).

Run locally:  uvicorn web.main:app --reload
Production:   uvicorn web.main:app --host 127.0.0.1 --port 8000
"""

import json
import os
import sys
from datetime import date, datetime
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# storage.py lives in the repo root (one level above web/).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, REPO_ROOT)
import storage  # noqa: E402
import apartments_store  # noqa: E402  shared apartments/*.md access (also used by the bot)

MOCK_PATH = os.path.join(REPO_ROOT, "gui", "data", "mock_notifications.json")
APARTMENTS_DIR = apartments_store.APARTMENTS_DIR

app = FastAPI(title="Kross — Notifiche host")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ── Display config ────────────────────────────────────────────────────────────
CATEGORY_LABELS = {
    "tutti": "Tutti",
    "riparazione": "Riparazioni",
    "checkin_checkout": "Early/late check-in/out",
}

# (background, foreground, label)
CATEGORY_BADGE = {
    "intervento_host": ("#ffe3e3", "#c92a2a", "Intervento"),
    "riparazione": ("#fff3bf", "#e67700", "Riparazione"),
    "checkin_checkout": ("#e7f5ff", "#1971c2", "Check-in/out"),
}

STATO_BADGE = {
    "passata": ("#e9ecef", "#495057", "Passata"),
    "presente": ("#d0ebff", "#1971c2", "In corso"),
    "futura": ("#e5dbff", "#6741d9", "Futura"),
}

STATO_LABELS = {"passata": "Passate", "presente": "Presente", "futura": "Future"}
STATO_ORDER = ["presente", "futura", "passata"]

_MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu",
           "lug", "ago", "set", "ott", "nov", "dic"]


# ── Data access ───────────────────────────────────────────────────────────────
def load_notifications():
    """Real SQLite DB if it exists; otherwise the mock JSON (local dev)."""
    if os.path.exists(storage.DB_PATH):
        rows = storage.get_pending_notifications()
        for r in rows:
            r.setdefault("booking_date", r.get("check_in", ""))
            r["id"] = str(r["id"])
        return rows
    with open(MOCK_PATH, encoding="utf-8") as f:
        return json.load(f)


def using_db():
    return os.path.exists(storage.DB_PATH)


def known_homes():
    """All apartments we manage, taken from the apartments/ folder (one .md per
    apartment). Used so every apartment always appears as a filter option, even
    when it currently has no pending notification."""
    return apartments_store.list_apartments()


def compute_booking_status(check_in, check_out, today=None):
    today = today or date.today()
    try:
        ci = datetime.strptime(check_in, "%Y-%m-%d").date()
        co = datetime.strptime(check_out, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "presente"
    if co < today:
        return "passata"
    if ci > today:
        return "futura"
    return "presente"


def fmt_date(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return iso or "?"
    return f"{d.day} {_MONTHS[d.month - 1]}"


def fmt_datetime(value):
    # created_at is stored as "YYYY-MM-DD HH:MM:SS" (DB) or "YYYY-MM-DD HH:MM"
    # (mock). Render a compact "13 giu 09:15" for the card timestamp.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            d = datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
        return f"{d.day} {_MONTHS[d.month - 1]} {d.strftime('%H:%M')}"
    return value or ""


def build_view(n):
    """Precompute everything the templates need so they stay presentational."""
    cat_bg, cat_fg, cat_lbl = CATEGORY_BADGE.get(
        n["category"], ("#e9ecef", "#495057", n.get("category", "")))
    stato = n["_stato"]
    st_bg, st_fg, st_lbl = STATO_BADGE[stato]
    return {
        **n,
        "stato": stato,
        "dates": f"{fmt_date(n['check_in'])} – {fmt_date(n['check_out'])}",
        "check_in_fmt": fmt_date(n["check_in"]),
        "check_out_fmt": fmt_date(n["check_out"]),
        "booking_date_fmt": fmt_date(n.get("booking_date", "")),
        "created_at_fmt": fmt_datetime(n.get("created_at", "")),
        "cat_badge": {"bg": cat_bg, "fg": cat_fg, "label": cat_lbl},
        "stato_badge": {"bg": st_bg, "fg": st_fg, "label": st_lbl},
    }


def get_enriched():
    items = [dict(n) for n in load_notifications()]
    for n in items:
        n["_stato"] = compute_booking_status(n["check_in"], n["check_out"])
    return items


# ── Filtering & sorting ───────────────────────────────────────────────────────
def apply_filters(items, category, stato, casa, sort_by):
    out = []
    for n in items:
        if category != "tutti" and n["category"] != category:
            continue
        if stato and n["_stato"] not in stato:
            continue
        if casa and n["home"] not in casa:
            continue
        out.append(n)

    if sort_by == "booking_date":
        out.sort(key=lambda n: n.get("booking_date", ""), reverse=True)
    else:
        out.sort(key=lambda n: n.get("created_at", ""), reverse=True)
    return out


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    category: str = "tutti",
    stato: list[str] = Query(default=[]),
    casa: list[str] = Query(default=[]),
    sort: str = "created_at",
):
    items = get_enriched()
    # Union the canonical apartment list with any homes present in the data, so
    # every managed apartment shows as a filter even with no pending notification.
    homes = sorted(set(known_homes()) | {n["home"] for n in items})

    filtered = apply_filters(items, category, stato, casa, sort)
    views = [build_view(n) for n in filtered]

    query_string = request.url.query  # for preserving filters into detail/back
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "notifications": views,
            "count": len(views),
            "category": category,
            "category_labels": CATEGORY_LABELS,
            "stato_selected": stato,
            "stato_order": STATO_ORDER,
            "stato_labels": STATO_LABELS,
            "homes": homes,
            "casa_selected": casa,
            "sort": sort,
            "query_string": query_string,
            "using_db": using_db(),
        },
    )


@app.get("/notification/{notif_id}", response_class=HTMLResponse)
def detail(request: Request, notif_id: str, next: str = ""):
    items = get_enriched()
    match = None
    for n in items:
        if str(n["id"]) == notif_id:
            match = n
            break
    if match is None:
        # Already resolved or unknown — send the user back to the list.
        return RedirectResponse(url=("/?" + next) if next else "/", status_code=303)

    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "n": build_view(match),
            "next": next,
            "using_db": using_db(),
        },
    )


@app.post("/notification/{notif_id}/resolve")
def resolve(notif_id: str, next: str = Form(default="")):
    if using_db():
        try:
            storage.mark_resolved(int(notif_id))
        except (ValueError, TypeError):
            pass
    target = "/?" + next if next else "/"
    return RedirectResponse(url=target, status_code=303)


@app.get("/api/notifications")
def api_notifications():
    """JSON endpoint — handy for debugging / future integrations."""
    return [build_view(n) for n in get_enriched()]


# ── House info editor ─────────────────────────────────────────────────────────
# Lets the host edit the per-apartment knowledge base (apartments/*.md) that the
# bot feeds to Claude. Scope is deliberately limited to these per-house files —
# the global base prompt lives in script.py and stays a developer-only change.
# The bot re-reads the file on every reply, so a save here takes effect on the
# next poll cycle with no restart.
@app.get("/houses", response_class=HTMLResponse)
def houses(request: Request, saved: str = ""):
    return templates.TemplateResponse(
        request,
        "houses.html",
        {
            "homes": sorted(known_homes()),
            "saved": saved,
        },
    )


@app.get("/houses/{name}/edit", response_class=HTMLResponse)
def house_edit(request: Request, name: str, error: str = ""):
    if name not in known_homes():
        return RedirectResponse(url="/houses", status_code=303)
    try:
        content = apartments_store.read_apartment(name)
    except FileNotFoundError:
        return RedirectResponse(url="/houses", status_code=303)
    return templates.TemplateResponse(
        request,
        "house_edit.html",
        {
            "name": name,
            "content": content,
            "error": error,
        },
    )


@app.post("/houses/{name}")
def house_save(name: str, content: str = Form(default="")):
    # Validate against the known list first — never let a URL name escape the
    # apartments folder or create a brand-new file from the web.
    if name not in known_homes():
        return RedirectResponse(url="/houses", status_code=303)
    try:
        apartments_store.write_apartment(name, content)
    except (FileNotFoundError, ValueError) as exc:
        err = urlencode({"error": str(exc)})
        return RedirectResponse(url=f"/houses/{name}/edit?{err}", status_code=303)
    saved = urlencode({"saved": name})
    return RedirectResponse(url=f"/houses?{saved}", status_code=303)
