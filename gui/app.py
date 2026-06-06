"""
Kross Autoresponder — Host dashboard (MVP).

Airbnb-style list of the host-intervention notifications produced by the AI
autoresponder (escalations only). Reads from a mock JSON file for now; the real
backend (data store) will be plugged in later by replacing load_notifications().

Run with:  streamlit run gui/app.py
"""

import json
import os
from datetime import date, datetime

import streamlit as st

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "mock_notifications.json")

# ── Display config ────────────────────────────────────────────────────────────
# Category chips: "Tutti" = all interventions. Sub-categories filter within them.
CATEGORY_LABELS = {
    "tutti": "Tutti",
    "riparazione": "Riparazioni",
    "checkin_checkout": "Early/late check-in/out",
}

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


# ── Data loading ──────────────────────────────────────────────────────────────
def load_notifications():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def compute_booking_status(check_in, check_out, today=None):
    """Booking status is computed by the GUI for now (per agreed plan)."""
    today = today or date.today()
    ci = datetime.strptime(check_in, "%Y-%m-%d").date()
    co = datetime.strptime(check_out, "%Y-%m-%d").date()
    if co < today:
        return "passata"
    if ci > today:
        return "futura"
    return "presente"


def fmt_date(iso):  # "2026-06-10" -> "10 giu"
    months = ["gen", "feb", "mar", "apr", "mag", "giu",
              "lug", "ago", "set", "ott", "nov", "dic"]
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    return f"{d.day} {months[d.month - 1]}"


# ── State ─────────────────────────────────────────────────────────────────────
def init_state():
    st.session_state.setdefault("category", "tutti")
    st.session_state.setdefault("stato_filter", [])
    st.session_state.setdefault("casa_filter", [])
    st.session_state.setdefault("sort_by", "created_at")
    st.session_state.setdefault("selected_id", None)
    st.session_state.setdefault("resolved", set())


# ── Styling ───────────────────────────────────────────────────────────────────
def inject_css():
    st.markdown(
        """
        <style>
        /* Trim the large default empty space above the title */
        .block-container { padding-top: 3rem; }

        /* Smaller, denser page title */
        .app-title { font-size: 1.35rem; font-weight: 700; margin: 0 0 2px 0; }
        .app-sub { color: #868e96; font-size: 0.8rem; margin: 0 0 10px 0; }

        /* Compact notification cards */
        .card {
            border: 1px solid #e9ecef;
            border-radius: 11px;
            padding: 9px 13px;
            background: #ffffff;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        }
        .card-home { font-size: 0.92rem; font-weight: 700; color: #212529; line-height: 1.2; }
        .card-dates { color: #868e96; font-size: 0.76rem; margin: 1px 0 4px 0; }
        .card-summary { color: #343a40; font-size: 0.83rem; line-height: 1.25; }
        .badge {
            display: inline-block; padding: 1px 8px; border-radius: 999px;
            font-size: 0.66rem; font-weight: 600; margin-left: 5px;
        }
        .guest { color: #495057; }

        /* Tight spacing + small "Apri" button under each card */
        [class*="st-key-card_"] { margin-bottom: 5px; }
        [class*="st-key-card_"] [data-testid="stVerticalBlock"] { gap: 4px; }
        [class*="st-key-card_"] button {
            padding: 1px 12px; font-size: 0.72rem;
            min-height: unset; height: auto; border-radius: 7px; width: auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(text, bg, fg):
    return f'<span class="badge" style="background:{bg};color:{fg};">{text}</span>'


# ── Filtering & sorting ───────────────────────────────────────────────────────
def apply_filters(items):
    cat = st.session_state.category
    stato_f = st.session_state.stato_filter
    casa_f = st.session_state.casa_filter

    out = []
    for n in items:
        if n["id"] in st.session_state.resolved:
            continue
        if cat != "tutti" and n["category"] != cat:
            continue
        if stato_f and n["_stato"] not in stato_f:
            continue
        if casa_f and n["home"] not in casa_f:
            continue
        out.append(n)

    if st.session_state.sort_by == "booking_date":
        out.sort(key=lambda n: n["booking_date"], reverse=True)
    else:
        out.sort(key=lambda n: n["created_at"], reverse=True)
    return out


# ── Views ─────────────────────────────────────────────────────────────────────
def render_card(n):
    cat_bg, cat_fg, cat_lbl = CATEGORY_BADGE.get(n["category"], ("#e9ecef", "#495057", n["category"]))
    st_bg, st_fg, st_lbl = STATO_BADGE[n["_stato"]]

    # Stato (date) badge first, then category badge — per requested order.
    with st.container(key=f"card_{n['id']}"):
        st.markdown(
            f"""
            <div class="card">
                <div class="card-home">{n['home']}
                    <span style="float:right;">{badge(st_lbl, st_bg, st_fg)}{badge(cat_lbl, cat_bg, cat_fg)}</span>
                </div>
                <div class="card-dates">{fmt_date(n['check_in'])} – {fmt_date(n['check_out'])}
                    &nbsp;·&nbsp; <span class="guest">{n['guest_name']} · {n['channel']}</span>
                </div>
                <div class="card-summary">{n['summary']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Apri", key=f"btn_{n['id']}"):
            st.session_state.selected_id = n["id"]
            st.rerun()


def render_detail(n):
    if st.button("← Indietro"):
        st.session_state.selected_id = None
        st.rerun()

    cat_bg, cat_fg, cat_lbl = CATEGORY_BADGE.get(n["category"], ("#e9ecef", "#495057", n["category"]))
    st_bg, st_fg, st_lbl = STATO_BADGE[n["_stato"]]

    st.markdown(f"### {n['home']}")
    st.markdown(badge(st_lbl, st_bg, st_fg) + badge(cat_lbl, cat_bg, cat_fg), unsafe_allow_html=True)

    st.markdown(
        f"**Ospite:** {n['guest_name']}  ·  **Canale:** {n['channel']}  \n"
        f"**Check-in:** {fmt_date(n['check_in'])}  ·  **Check-out:** {fmt_date(n['check_out'])}  \n"
        f"**Prenotato il:** {fmt_date(n['booking_date'])}  ·  **Ricevuto:** {n['created_at']}"
    )

    st.markdown("#### Messaggio dell'ospite")
    st.info(n["message"])

    st.markdown("#### Perche' serve l'host")
    st.warning(n["summary"])

    st.divider()
    # Phase 1 interaction: resolve/cancel (local-only for now — see README).
    if st.button("Segna come gestita", type="primary"):
        st.session_state.resolved.add(n["id"])
        st.session_state.selected_id = None
        st.toast("Notifica segnata come gestita.")
        st.rerun()
    st.caption("Nota: per ora 'gestita' agisce solo localmente (nessun salvataggio sul backend).")


# ── Sidebar filters ───────────────────────────────────────────────────────────
def render_sidebar(items):
    with st.sidebar:
        st.header("Filtri")

        # Date/stato filter first, then category — per requested order.
        st.session_state.stato_filter = st.multiselect(
            "Stato prenotazione",
            options=STATO_ORDER,
            format_func=lambda k: STATO_LABELS[k],
            default=st.session_state.stato_filter,
        )

        cat_keys = list(CATEGORY_LABELS.keys())
        st.session_state.category = st.radio(
            "Categoria",
            options=cat_keys,
            format_func=lambda k: CATEGORY_LABELS[k],
            index=cat_keys.index(st.session_state.category),
        )

        homes = sorted({n["home"] for n in items})
        st.session_state.casa_filter = st.multiselect(
            "Casa", options=homes, default=st.session_state.casa_filter
        )

        st.session_state.sort_by = st.selectbox(
            "Ordina per",
            options=["created_at", "booking_date"],
            format_func=lambda k: "Data notifica" if k == "created_at" else "Data prenotazione",
            index=0 if st.session_state.sort_by == "created_at" else 1,
        )

        n_resolved = len(st.session_state.resolved)
        if n_resolved and st.button(f"Ripristina {n_resolved} gestite"):
            st.session_state.resolved = set()
            st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(page_title="Kross — Notifiche host", page_icon="🏠", layout="centered")
    init_state()
    inject_css()

    items = [dict(n) for n in load_notifications()]
    for n in items:
        n["_stato"] = compute_booking_status(n["check_in"], n["check_out"])

    render_sidebar(items)

    by_id = {n["id"]: n for n in items}
    if st.session_state.selected_id and st.session_state.selected_id in by_id:
        render_detail(by_id[st.session_state.selected_id])
        return

    filtered = apply_filters(items)
    st.markdown('<div class="app-title">🏠 Notifiche host</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="app-sub">{len(filtered)} notifiche</div>', unsafe_allow_html=True)

    if not filtered:
        st.info("Nessuna notifica con questi filtri.")
        return

    for n in filtered:
        render_card(n)


if __name__ == "__main__":
    main()
