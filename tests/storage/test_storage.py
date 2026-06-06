"""
TEST: verifica storage.py in isolamento, prima di collegarlo al bot vero.

Crea il DB da zero, inserisce notifiche finte, controlla la deduplicazione
(id_thread, id_message), il vincolo UNIQUE, mark_resolved() e
get_pending_notifications(). Ogni step stampa cosa succede e cosa ci si
aspetta — dopo puoi anche aprire notifications.db con DB Browser for SQLite
e vedere le righe con i tuoi occhi.
"""
import sys, os

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import storage

# Riparti da zero a ogni run, cosi' il test e' ripetibile.
if os.path.exists(storage.DB_PATH):
    os.remove(storage.DB_PATH)

storage.init_db()
print(f"DB creato in: {storage.DB_PATH}\n")

# ── Notifiche finte (stesso thread, due messaggi diversi) ─────────────────────
fake_1 = {
    "id_thread": 9070, "id_message": 1001, "id_reservation": 5302,
    "category": "riparazione", "home": "Costantino Nigra 29",
    "guest_name": "Bariş Çal", "channel": "airbnb",
    "check_in": "2026-05-22", "check_out": "2026-05-24", "booking_date": "2026-05-10",
    "message": "La doccia perde acqua, potete mandare qualcuno?",
    "summary": "Problema di manutenzione che richiede intervento fisico",
}
fake_2 = {
    "id_thread": 9070, "id_message": 1002, "id_reservation": 5302,
    "category": "checkin_checkout", "home": "Costantino Nigra 29",
    "guest_name": "Bariş Çal", "channel": "airbnb",
    "check_in": "2026-05-22", "check_out": "2026-05-24", "booking_date": "2026-05-10",
    "message": "Possiamo fare il check-out alle 13 invece delle 11?",
    "summary": "Richiesta di late check-out, serve approvazione host",
}

# ── TEST 1: dedup check su una coppia mai vista ───────────────────────────────
print("TEST 1 — notification_exists() su (9070, 1001) prima di registrarla")
print(f"  esiste? {storage.notification_exists(9070, 1001)}   atteso: False\n")

# ── TEST 2: registra due notifiche ────────────────────────────────────────────
print("TEST 2 — record_notification() x2 (stesso thread, messaggi diversi)")
storage.record_notification(fake_1)
storage.record_notification(fake_2)
print("  Inserite 2 notifiche.\n")

# ── TEST 3: ora il dedup check le trova entrambe ──────────────────────────────
print("TEST 3 — notification_exists() dopo l'inserimento")
print(f"  (9070, 1001) esiste? {storage.notification_exists(9070, 1001)}   atteso: True")
print(f"  (9070, 1002) esiste? {storage.notification_exists(9070, 1002)}   atteso: True")
print(f"  (9070, 9999) esiste? {storage.notification_exists(9070, 9999)}   atteso: False (mai visto)\n")

# ── TEST 4: vincolo UNIQUE — un secondo escalation sullo stesso messaggio ─────
print("TEST 4 — record_notification() di nuovo su (9070, 1001): deve fallire")
try:
    storage.record_notification(fake_1)
    print("  PROBLEMA: l'inserimento duplicato e' passato — non dovrebbe succedere!\n")
except Exception as e:
    print(f"  OK, bloccato dal vincolo UNIQUE: {type(e).__name__}\n")

# ── TEST 5: notifiche pending ──────────────────────────────────────────────────
print("TEST 5 — get_pending_notifications()")
pending = storage.get_pending_notifications()
print(f"  {len(pending)} notifiche pending (atteso: 2)")
for n in pending:
    print(f"    id={n['id']}  msg={n['id_message']}  status={n['status']}  -> {n['summary'][:55]}")
print()

# ── TEST 6: Teo segna come gestita la notifica del messaggio 1001 ────────────
print("TEST 6 — mark_resolved() sulla notifica del messaggio 1001")
target = next(n for n in pending if n["id_message"] == 1001)
storage.mark_resolved(target["id"], handled_by="Teo")
print(f"  Notifica id={target['id']} segnata come risolta da 'Teo'\n")

# ── TEST 7: sparisce dalla lista pending (cosi' la GUI non la mostra piu') ────
print("TEST 7 — get_pending_notifications() dopo mark_resolved")
pending_after = storage.get_pending_notifications()
print(f"  {len(pending_after)} notifiche pending (atteso: 1, solo il messaggio 1002)")
for n in pending_after:
    print(f"    id={n['id']}  msg={n['id_message']}  status={n['status']}")
print()

# ── TEST 8: ma il record resta — questa e' la rete di sicurezza anti-duplicati ─
print("TEST 8 — notification_exists() rimane True anche per una notifica risolta")
print(f"  (9070, 1001) esiste ancora? {storage.notification_exists(9070, 1001)}   atteso: True")
print("  -> il record resta nel DB anche da risolto: e' quello che impedisce")
print("     una nuova notifica se Teo ha gestito il problema senza rispondere")
print("     su Kross (es. telefonata) e il filtro difensivo del bot non se ne accorge.")
