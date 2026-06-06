# GUI — Host dashboard (MVP)

Airbnb-style dashboard that lists the notifications produced by the AI
autoresponder so the hosts can review them and mark them as handled.

This is the **frontend** part. It currently reads from a mock JSON file; the real
backend (a shared data store of notifications) will be plugged in later by the
colleague's branch.

## Run

```bash
pip install -r gui/requirements.txt
streamlit run gui/app.py
```

## Structure

```
gui/
  app.py                     # Streamlit app
  data/
    mock_notifications.json  # sample data the UI is built against
  requirements.txt
  README.md
```

Scope: only notifications that need host intervention (the bot's escalations).

## Filters (as agreed)

- **Stato prenotazione** (combinable): Passate / Presente / Future — computed by
  the GUI from `check_in` / `check_out` vs. today
- **Categoria** (single select): Tutti / Riparazioni / Early-late check-in/out
- **Casa** (combinable): one entry per apartment
- **Ordina per**: Data notifica (chronological) or Data prenotazione

Category is single-select; Stato and Casa combine with it and with each other.

## Interaction (Phase 1)

Click **anywhere on a card** to zoom into the detail view, then **Segna come
gestita** to remove it from the list.

> Note: "gestita" currently acts only locally (in the Streamlit session). When
> the backend lands, this should write `status: "resolved"` back to the shared
> store so it disappears for all hosts. Deep-linking to Kross/Airbnb is a later
> phase.

## Data contract

The UI expects records shaped like `data/mock_notifications.json`:

| field | meaning |
|---|---|
| `id`, `id_thread`, `id_reservation` | identifiers |
| `category` | `intervento_host` \| `riparazione` \| `checkin_checkout` |
| `home` | apartment name (matches Kross `name_room_type`) |
| `guest_name`, `channel` | guest + source (airbnb/booking/kross) |
| `check_in`, `check_out`, `booking_date` | dates (YYYY-MM-DD) |
| `message` | full guest message |
| `summary` | short reason (escalation) or message preview (auto) |
| `created_at`, `status` | when received + lifecycle state |
| `handled_by`, `read_by` | reserved for the future multi-host phase |

To switch from mock to real data later, replace `load_notifications()` in
`app.py`.
