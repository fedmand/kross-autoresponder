"""
House knowledge-base schema — the 23 categories from the host's master document
(Database_Master_Chatbot_BnB). Single source of truth for:

- the auto-generated input form (one section per category, one input per field), and
- the deterministic markdown renderer (houses_store.render_markdown).

Each category has:
  id            stable slug (used in form field names and the stored JSON)
  title         human title shown in the form and as the markdown heading
  fields        ordered list of field labels (structured inputs)
  instructions  whether to show a free-text "istruzioni / note" textarea
  free_text     True for categories that ARE just a free-text block (21, 23):
                no structured fields, the instructions textarea is the content.

Only the categories/fields the host actually fills are rendered into the output;
empty ones are skipped (handled in houses_store.render_markdown).
"""

INSTRUCTIONS_LABEL = "Istruzioni / note (testo libero)"

SCHEMA = [
    {
        "id": "informazioni_generali",
        "title": "1. Informazioni generali",
        "fields": [
            "Nome appartamento", "Nome annuncio", "Indirizzo completo",
            "Descrizione palazzo (colore/numero piani totale)",
            "Descrizione porta condominiale", "Piano", "Presenza ascensore",
            "Metratura totale", "Numero camere da letto", "Numero bagni",
            "Numero soggiorni", "Numero massimo ospiti", "Numero letti totali",
            "Numero matrimoniali", "Numero singoli",
            "Divano letto presente (marca e tipologia)", "Anno ristrutturazione",
            "Presenza balcone", "Presenza terrazza", "Giardino privato",
            "Vista particolare",
        ],
    },
    {
        "id": "check_in",
        "title": "2. Check-in",
        "fields": [
            "Link accesso all'appartamento", "Orario check-in",
            "Early check-in disponibile", "Costo early check-in", "Self check-in",
            "Check-in in presenza", "Codice portone", "Codice keybox",
            "Posizione keybox", "Nome sul citofono", "Numero interno",
            "Piano corretto", "Foto ingresso", "Codice smart lock",
            "Numero telefono assistenza",
        ],
    },
    {
        "id": "check_out",
        "title": "3. Check-out",
        "fields": [
            "Link istruzioni check out", "Orario check-out",
            "Late check-out disponibile", "Costo late check-out",
            "Dove lasciare chiavi", "Cosa fare prima di uscire",
            "Dove buttare immondizia", "Spegnere climatizzatore",
            "Lasciare finestre chiuse", "Lasciare stoviglie pulite",
            "Procedura check-out",
        ],
    },
    {
        "id": "camere",
        "title": "4. Camere",
        "fields": [
            "Numero camere", "Dimensione camere", "Letto matrimoniale",
            "Letti singoli", "Tipologia di materassi", "Armadio", "Appendiabiti",
            "Comodini", "Lampade", "Oscuranti", "Tende", "Cuscini extra",
            "Coperte extra", "Aria condizionata", "Riscaldamento",
        ],
    },
    {
        "id": "bagni",
        "title": "5. Bagni",
        "fields": [
            "Numero bagni", "Doccia", "Vasca", "Bidet", "Asciugacapelli",
            "Sapone mani", "Shampoo", "Bagnoschiuma", "Carta igienica extra",
            "Asciugamani viso", "Asciugamani doccia", "Tappetino bagno",
            "Scaldasalviette", "Lavatrice", "Stendino",
        ],
    },
    {
        "id": "cucina",
        "title": "6. Cucina",
        "fields": [
            "Cucina completa", "Piano induzione", "Piano gas", "Forno",
            "Microonde", "Lavastoviglie", "Frigorifero", "Congelatore",
            "Bollitore", "Macchina caffè", "Moka", "Tostapane", "Pentole",
            "Padelle", "Piatti", "Bicchieri", "Calici vino", "Posate",
            "Tagliere", "Apribottiglie", "Sale", "Olio", "Zucchero", "Caffè",
            "Tè",
        ],
    },
    {
        "id": "soggiorno",
        "title": "7. Soggiorno",
        "fields": [
            "Divano", "Divano letto", "Smart TV", "Dimensione TV", "Netflix",
            "Prime Video", "Disney+", "Wi-Fi", "Velocità internet",
            "Tavolo da pranzo", "Sedie disponibili", "Aria condizionata",
            "Riscaldamento",
        ],
    },
    {
        "id": "elettrodomestici",
        "title": "8. Elettrodomestici",
        "fields": [
            "Lavatrice", "Asciugatrice", "Ferro da stiro", "Asse da stiro",
            "Aspirapolvere", "Robot aspirapolvere", "Phon", "Ventilatore",
            "Deumidificatore", "Caldaia", "Scaldabagno",
        ],
    },
    {
        "id": "climatizzazione",
        "title": "9. Climatizzazione",
        "fields": [
            "Aria condizionata", "Numero split/fancoil", "Riscaldamento autonomo",
            "Tipo riscaldamento", "Termostato", "Temperatura consigliata",
            "Manuale utilizzo",
        ],
    },
    {
        "id": "connessione_internet",
        "title": "10. Connessione internet",
        "fields": [
            "Nome Wi-Fi", "Password Wi-Fi", "Router posizione", "Fibra presente",
            "Velocità media", "Procedura reset router",
        ],
    },
    {
        "id": "sicurezza",
        "title": "11. Sicurezza",
        "fields": [
            "Estintore", "Rilevatore fumo", "Rilevatore monossido",
            "Kit pronto soccorso", "Numero emergenze", "Quadro elettrico",
            "Contatore elettrico", "Contatore acqua", "Contatore gas",
            "Valvola del gas", "Rubinetto acqua generale",
        ],
    },
    {
        "id": "parcheggio",
        "title": "12. Parcheggio",
        "fields": [
            "Garage privato", "Box auto", "Parcheggio gratuito",
            "Parcheggio a pagamento", "Posto numerato", "Altezza massima garage",
            "Telepass/ZTL",
        ],
    },
    {
        "id": "accessibilita",
        "title": "13. Accessibilità",
        "fields": [
            "Ascensore", "Rampe", "Accesso disabili", "Doccia accessibile",
            "Piano terra",
        ],
    },
    {
        "id": "servizi_extra",
        "title": "14. Servizi extra",
        "fields": [
            "Culla", "Seggiolone", "Lettino bambino", "Giochi per bambini",
            "Animali ammessi", "Ciotole animali", "Deposito bagagli",
            "Pulizie extra", "Cambio biancheria", "Taxi convenzionato",
            "Transfer aeroporto", "Noleggio bici",
        ],
    },
    {
        "id": "regole_casa",
        "title": "15. Regole casa",
        "fields": [
            "Vietato fumare", "Vietate feste", "Orario silenzio",
            "Numero massimo ospiti", "Animali consentiti",
            "Ospiti esterni consentiti", "Penalità danni", "Cauzione",
        ],
    },
    {
        "id": "gestione_problemi",
        "title": "16. Gestione problemi",
        "fields": [
            "Mancanza acqua calda", "Salta corrente", "Wi-Fi non funziona",
            "Aria condizionata non funziona", "Serratura bloccata",
            "Perdite d'acqua", "Odori strani", "Insetti", "Rumori vicini",
            "Guasto elettrodomestici",
        ],
    },
    {
        "id": "rifiuti",
        "title": "17. Rifiuti",
        "fields": [
            "Raccolta differenziata", "Dove sono i bidoni", "Calendario raccolta",
            "Umido", "Carta", "Plastica", "Vetro", "Secco",
        ],
    },
    {
        "id": "trasporti",
        "title": "18. Trasporti",
        "fields": [
            "Metro più vicina", "Bus più vicino", "Stazione ferroviaria",
            "Aeroporto", "Taxi", "Car sharing", "Tempo per il centro",
        ],
    },
    {
        "id": "attrazioni_dintorni",
        "title": "19. Attrazioni e dintorni",
        "fields": [
            "Supermercato", "Farmacia", "Ospedale", "Ristoranti", "Pizzerie",
            "Bar", "Palestra", "Lavanderia", "Bancomat", "Luoghi turistici",
        ],
    },
    {
        "id": "gestione_prenotazione",
        "title": "20. Gestione prenotazione",
        "fields": [
            "Tassa di soggiorno", "Modalità pagamento", "Fattura disponibile",
            "Prolungamento soggiorno", "Early check-in", "Late check-out",
            "Oggetti smarriti", "Rimborso", "Reclami", "Contatto emergenze",
        ],
    },
    {
        "id": "personalita_ai",
        "title": "21. Personalità chatbot / AI operating rules",
        "fields": [],
        "free_text": True,
        "instructions_label": "Tono di voce, sembianze e obiettivi principali che "
                              "l'AI deve assumere nelle conversazioni con gli ospiti",
    },
    {
        "id": "faq",
        "title": "22. FAQ",
        "fields": [
            "Wifi non funziona", "Lavatrice non funziona",
            "Lavastoviglie non funziona",
            "Salta la corrente: procedura da seguire", "Mancanza di acqua",
            "Mancanza di acqua calda",
        ],
        "value_label": "RISPOSTA",
    },
    {
        "id": "escalation_policy",
        "title": "23. Escalation policy",
        "fields": [],
        "free_text": True,
        "instructions_label": "Quando il chatbot deve inviare una notifica di "
                              "richiesta intervento (casi che richiedono "
                              "coordinamento con terzi: tecnici, pulizie, ecc.)",
    },
]

# Quick lookup by id (used by the renderer / form save).
SCHEMA_BY_ID = {c["id"]: c for c in SCHEMA}


def instructions_label(category):
    """Label for a category's free-text textarea."""
    return category.get("instructions_label", INSTRUCTIONS_LABEL)


def empty_house():
    """A blank house structure with every category present but unfilled."""
    return {
        "name": "",
        "categories": {
            c["id"]: {"fields": {}, "instructions": ""} for c in SCHEMA
        },
    }
