"""Scrittura su Google Sheets: sempre batch, mai cella per cella (15.1 regola 5).

Il punto critico di M0 (criterio di accettazione): prima di sovrascrivere un
foglio, si rileggono le colonne che l'utente modifica a mano (`stato`, `note`,
`bloccato`, `soppressa`) e si riportano nei dati da scrivere. Senza questo
passaggio, ogni run cancella il lavoro manuale della notte precedente
(08.8, 03.1.1).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import gspread

COLONNE_EVENTI = [
    "id", "titolo", "descrizione", "tipologia", "data_inizio", "ora_inizio",
    "data_fine", "ora_fine", "serie_id", "occorrenza", "comune", "luogo",
    "km", "minuti", "prezzo", "organizzatore", "url", "url_immagine",
    "fonti", "confidenza", "stato", "note", "primo_visto", "ultimo_visto",
    "bloccato", "soppressa",
]

# Colonne che appartengono all'utente: un run non le sovrascrive mai con un
# valore calcolato, le riporta così come le trova sul foglio (03.1.1).
# 'comune' aggiunta il 2026-08-29 (richiesto dall'utente): serve soprattutto
# per Quarantena (un evento con comune ambiguo/non risolto, che l'operatore
# assegna a mano), ma vale anche per Eventi — se qualcuno corregge un
# comune sbagliato per errore di estrazione, la modifica non deve sparire
# al prossimo giro, stesso principio di stato/note/bloccato.
COLONNE_UTENTE = {"stato", "note", "bloccato", "soppressa", "comune"}


def _leggi_overrides_utente(worksheet: gspread.Worksheet) -> dict[str, dict[str, str]]:
    """Rilettura preventiva: id evento -> {colonna_utente: valore}."""
    valori = worksheet.get_all_records()
    overrides: dict[str, dict[str, str]] = {}
    for riga in valori:
        event_id = riga.get("id")
        if not event_id:
            continue
        overrides[event_id] = {col: riga.get(col, "") for col in COLONNE_UTENTE}
    return overrides


def pubblica_eventi(worksheet: gspread.Worksheet, righe: list[dict]) -> None:
    """Scrive l'intero foglio `Eventi` in un colpo solo, preservando le colonne utente.

    `righe` è la lista di eventi calcolati da questo run (dict con le chiavi
    di COLONNE_EVENTI, tranne le colonne utente che vengono qui reintegrate).
    Le righe con `bloccato = si` letto dal foglio non vengono toccate: si
    riscrive comunque l'intera riga, ma con gli stessi valori già presenti
    (08.8: "Le righe con bloccato = sì non vengono mai sovrascritte, solo
    riposizionate").
    """
    overrides = _leggi_overrides_utente(worksheet)

    corpo = []
    for riga in righe:
        event_id = riga["id"]
        utente = overrides.get(event_id, {})
        riga_finale = dict(riga)
        for col in COLONNE_UTENTE:
            if col in utente and utente[col] != "":
                riga_finale[col] = utente[col]
        corpo.append([riga_finale.get(col, "") for col in COLONNE_EVENTI])

    worksheet.clear()
    worksheet.update(
        [COLONNE_EVENTI] + corpo,
        value_input_option="USER_ENTERED",
    )
    # 2026-08-28, richiesto dall'utente: titolo/descrizione (colonne B/C) con
    # a capo attivo, così un testo lungo non trabocca nella cella accanto.
    worksheet.format("B:C", {"wrapStrategy": "WRAP"})
    # 2026-08-30, bug trovato dall'utente: un font impostato a mano su
    # singole righe non regge — ogni publish riordina gli eventi (data,
    # km) e riscrive da capo, e Google Sheets tiene la formattazione per
    # POSIZIONE di cella, non per contenuto: il font "segue" il numero di
    # riga fisico invece dell'evento, finendo a macchia di leopardo dopo
    # pochi giri. Fissare la dimensione sull'intera colonna (A:Z, oltre
    # l'ultima colonna usata) la rende indipendente da quante righe
    # esistono o in che ordine sono.
    worksheet.format("A:Z", {"textFormat": {"fontSize": 8}})


COLONNE_PERIMETRO = ["comune", "alias", "provincia", "lat", "lon", "istat", "km", "minuti", "fascia", "attivo"]


def pubblica_perimetro(worksheet: gspread.Worksheet, conn: sqlite3.Connection) -> int:
    """Scrive il foglio `Perimetro` da SQLite (03.1.4). Nessuna colonna utente qui:
    `attivo` è l'unica modificabile a mano ma il foglio Perimetro è a bassa
    frequenza di scrittura (si aggiorna solo dopo un nuovo import), quindi
    non serve la rilettura preventiva di pubblica_eventi.
    """
    cur = conn.execute(
        "SELECT comune, alias, provincia, lat, lon, istat, km, minuti, fascia, attivo FROM comuni ORDER BY km ASC"
    )
    righe = [[row[col] for col in COLONNE_PERIMETRO] for row in cur.fetchall()]
    worksheet.clear()
    worksheet.update([COLONNE_PERIMETRO] + righe, value_input_option="USER_ENTERED")
    return len(righe)


COLONNE_FONTI = [
    "source_id", "soggetto", "categoria", "comune_riferimento", "fascia",
    "polling_diretto", "canale", "url", "piattaforma",
    "metodo", "tier", "endpoint", "stato",
    "ultimo_run", "giorni_in_errore", "eventi_totali", "eventi_utili",
]

# 10 colonne rimosse dal foglio il 2026-08-28 (richiesto dall'utente):
# handle, seguito, frequenza, attivo, priorita, finestra_attenzione,
# ultimo_esito, primo_errore, resa_annuale, regime. Nessuna aveva un dato
# sorgente reale (nemmeno 'primo_errore', che esiste come colonna SQL ma
# non è mai scritta da nessuna logica) — coerente con "vuoto non è un
# errore" (04.7): meglio non mostrarle che mostrarle sempre vuote.
# 'categoria' aggiunta il 2026-08-28, 'polling_diretto' aggiunta il
# 2026-08-28 insieme a pull_fonti. 'eventi_totali'/'eventi_utili'/'stato'
# esistevano già in sources ma non erano mai state mappate qui
# (2026-08-28). 'soggetto'/'canale' aggiunte il 2026-08-28, derivate dal
# source_id (vedi pubblica_fonti), non hanno una colonna SQL propria.
_MAPPA_COLONNE_FONTI_DA_SOURCES = {
    "source_id": "source_id",
    "url": "endpoint",
    "categoria": "categoria",
    "polling_diretto": "polling_diretto",
    "piattaforma": "piattaforma",
    "metodo": "tier",
    "tier": "tier",
    "endpoint": "endpoint",
    "ultimo_run": "last_run",
    "giorni_in_errore": "consecutive_errors",
    "eventi_totali": "eventi_totali",
    "eventi_utili": "eventi_utili",
    "stato": "stato",
}

# Colonne del foglio Fonti che l'operatore compila a mano e che pull_fonti
# riporta in SQLite (03, 08.3): l'operatore le marca lì, non in SQLite
# direttamente, perché il foglio è il posto dove sceglie/rivede le fonti.
COLONNE_FONTI_PULL = {"categoria": "categoria", "polling_diretto": "polling_diretto"}


_PREFISSO_SOGGETTO = {"comune": "Comune di", "proloco": "Pro Loco di"}


def _soggetto_e_canale(source_id: str, categoria: str | None) -> tuple[str, str]:
    """Deriva 'soggetto' (nome leggibile) e 'canale' (sito/facebook/
    instagram) dal source_id — nessuna colonna SQL dedicata, sarebbe
    ridondante col source_id stesso. 'comune-acqui-terme' -> ('Comune di
    Acqui Terme', 'sito'); 'proloco-calosso-facebook' -> ('Pro Loco di
    Calosso', 'facebook'); per le fonti sintetiche feed-* e le altre
    entità (teatro/aggregatore) il soggetto è il nome ripulito dai
    trattini, coerente con come compaiono già in CoperturaAltreEntita."""
    canale = "sito"
    corpo = source_id
    for suffisso, nome_canale in (("-facebook", "facebook"), ("-instagram", "instagram"), ("-sito", "sito")):
        if source_id.endswith(suffisso):
            canale = nome_canale
            corpo = source_id[: -len(suffisso)]
            break

    prefisso = _PREFISSO_SOGGETTO.get(categoria or "")
    if prefisso and "-" in corpo:
        _, nome = corpo.split("-", 1)
        soggetto = f"{prefisso} {nome.replace('-', ' ').title()}"
    else:
        soggetto = corpo.replace("-", " ").title()
    return soggetto, canale


def pubblica_fonti(worksheet: gspread.Worksheet, conn: sqlite3.Connection) -> int:
    """Scrive il foglio `Fonti` da SQLite (12.8). `categoria` e
    `polling_diretto` sono compilati a mano dall'operatore sul foglio e
    riportati in SQLite da `pull_fonti` — qui si scrivono semplicemente i
    valori già presenti in `sources`, che dopo un pull coincidono con
    quanto l'operatore aveva scritto. `comune_riferimento`/`fascia` non
    esistono come colonne SQL: derivate qui dal `source_id` per le fonti
    `comune-*` (2026-08-28), stesso pattern già usato da
    `scheduling.fascia_da_source_id` per la coda a priorità.
    """
    fasce_per_comune = {
        r["comune"].strip().lower().replace(" ", "-"): (r["comune"], r["fascia"])
        for r in conn.execute("SELECT comune, fascia FROM comuni WHERE attivo='si'").fetchall()
    }

    cur = conn.execute("SELECT * FROM sources ORDER BY source_id ASC")
    righe = []
    for row in cur.fetchall():
        riga = dict(row)
        source_id = riga["source_id"]
        comune_riferimento = ""
        fascia = ""
        if source_id.startswith("comune-"):
            trovato = fasce_per_comune.get(source_id[len("comune-"):])
            if trovato:
                comune_riferimento, fascia = trovato

        soggetto, canale = _soggetto_e_canale(source_id, riga.get("categoria"))

        valori = []
        for col in COLONNE_FONTI:
            if col == "comune_riferimento":
                valori.append(comune_riferimento)
                continue
            if col == "fascia":
                valori.append(fascia)
                continue
            if col == "soggetto":
                valori.append(soggetto)
                continue
            if col == "canale":
                valori.append(canale)
                continue
            colonna_sqlite = _MAPPA_COLONNE_FONTI_DA_SOURCES.get(col)
            valore = riga.get(colonna_sqlite) if colonna_sqlite else None
            valori.append(valore if valore is not None else "")
        righe.append(valori)
    worksheet.clear()
    worksheet.update([COLONNE_FONTI] + righe, value_input_option="USER_ENTERED")
    return len(righe)


def pull_fonti(worksheet: gspread.Worksheet, conn: sqlite3.Connection) -> dict[str, int]:
    """Rilegge `categoria` e `polling_diretto` dal foglio `Fonti` e li
    scrive in SQLite (03, 08.3): l'unico verso in cui questi due campi
    viaggiano è Sheets -> SQLite, l'opposto di tutto il resto del foglio
    (SQLite -> Sheets). Riga per riga tramite `source_id`: righe sul
    foglio senza `source_id` noto in SQLite vengono contate ma ignorate,
    non si inventano fonti nuove qui.
    """
    valori = worksheet.get_all_records()
    aggiornate = 0
    ignorate = 0
    for riga in valori:
        source_id = riga.get("source_id")
        if not source_id:
            continue
        esiste = conn.execute("SELECT 1 FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        if not esiste:
            ignorate += 1
            continue
        categoria = (riga.get("categoria") or "").strip() or None
        polling_diretto = (riga.get("polling_diretto") or "").strip() or None
        conn.execute(
            "UPDATE sources SET categoria = ?, polling_diretto = ? WHERE source_id = ?",
            (categoria, polling_diretto, source_id),
        )
        aggiornate += 1
    conn.commit()
    return {"aggiornate": aggiornate, "ignorate": ignorate}


COLONNE_DA_VERIFICARE = ["source_id", "piattaforma", "handle", "url", "comune", "stato", "note"]


def pubblica_da_verificare(worksheet: gspread.Worksheet, conn: sqlite3.Connection) -> int:
    """Scrive il foglio `DaVerificare` (richiesto dall'utente 2026-08-28):
    solo le voci di `coda_follow` in stato 'quarantena', isolate dal resto
    di CodaFollow (che mescola anche seguiti/da_seguire) così l'operatore
    vede in un colpo solo cosa richiede una verifica manuale — handle non
    riconosciuti dal sync, url che si sono rivelati non essere un profilo.

    Nessuna colonna preservata qui in scrittura: `comune`/`stato` che
    l'operatore modifica su questo foglio viaggiano verso SQLite tramite
    `pull_da_verificare` (2026-08-29, richiesto dall'utente, stesso
    pattern di `pull_fonti`), non restano "in memoria" sul foglio —
    appena risolta, una riga con `stato` diverso da 'quarantena' non
    ricompare più qui al giro successivo.
    """
    cur = conn.execute(
        "SELECT source_id, piattaforma, handle, url, comune, stato, note FROM coda_follow "
        "WHERE stato = 'quarantena' ORDER BY comune ASC, source_id ASC"
    )
    corpo = [[row[col] or "" for col in COLONNE_DA_VERIFICARE] for row in cur.fetchall()]
    worksheet.clear()
    worksheet.update([COLONNE_DA_VERIFICARE] + corpo, value_input_option="USER_ENTERED")
    return len(corpo)


_STATI_VALIDI_COD_FOLLOW = {
    "da_seguire", "candidato_da_feed", "quarantena", "fallito", "non_valido", "seguito",
    "nessuna_fonte_trovata",
}


def pull_da_verificare(worksheet: gspread.Worksheet, conn: sqlite3.Connection) -> dict[str, int]:
    """Rilegge `comune` e `stato` dal foglio `DaVerificare` e li scrive in
    `coda_follow` (2026-08-29, richiesto dall'utente): l'operatore apre il
    link di un profilo sconosciuto, capisce di chi è, e invece di editare
    SQLite a mano scrive qui il comune e cambia lo stato (es. 'da_seguire'
    se è una fonte valida, 'non_valido' se è rumore da scartare) — poi
    lancia questo comando. Stesso pattern di `pull_fonti`: unico verso
    Sheets -> SQLite per questi due campi.
    """
    valori = worksheet.get_all_records()
    aggiornate = 0
    ignorate = 0
    for riga in valori:
        source_id = riga.get("source_id")
        if not source_id:
            continue
        esiste = conn.execute("SELECT 1 FROM coda_follow WHERE source_id = ?", (source_id,)).fetchone()
        if not esiste:
            ignorate += 1
            continue

        comune = (riga.get("comune") or "").strip()
        stato = (riga.get("stato") or "").strip()

        if comune:
            conn.execute("UPDATE coda_follow SET comune = ? WHERE source_id = ?", (comune, source_id))
        if stato and stato in _STATI_VALIDI_COD_FOLLOW:
            conn.execute("UPDATE coda_follow SET stato = ? WHERE source_id = ?", (stato, source_id))
        aggiornate += 1

    conn.commit()
    return {"aggiornate": aggiornate, "ignorate": ignorate}


COLONNE_COPERTURA_COMUNI = [
    "fascia", "comune", "sito_istituzionale", "fb_comune", "fb_proloco", "ig_proloco",
]

_SIMBOLO_VERDE = "✓"   # seguito / sito senza errori
_SIMBOLO_GRIGIO = "○"  # da_seguire / candidato_da_feed: individuato, non ancora confermato
_SIMBOLO_ROSSO = "X"        # fallito / non_valido / quarantena / sito con errori consecutivi
_SIMBOLO_VERIFICATO_ASSENTE = "—"  # cercato con esito negativo esplicito, non solo "mai censito"
# vuoto: non censito / mai processato


def _simbolo_social(conn: sqlite3.Connection, source_id: str) -> str:
    """Traduce lo stato di una riga coda_follow nel simbolo richiesto
    dall'utente (2026-08-28): verde solo se realmente seguito, grigio se
    individuato ma non ancora confermato, rosso se il tentativo è fallito
    o si è rivelato un url non valido, vuoto se non è mai stato censito."""
    riga = conn.execute("SELECT stato FROM coda_follow WHERE source_id = ?", (source_id,)).fetchone()
    if not riga:
        return ""
    stato = riga["stato"]
    if stato == "seguito":
        return _SIMBOLO_VERDE
    if stato in ("da_seguire", "candidato_da_feed"):
        return _SIMBOLO_GRIGIO
    if stato in ("fallito", "non_valido", "quarantena"):
        return _SIMBOLO_ROSSO
    return ""


def _simbolo_sito_istituzionale(conn: sqlite3.Connection, source_id: str) -> str:
    """Sito comunale: verde se ha un endpoint reale e nessun errore
    consecutivo, rosso se l'endpoint c'è ma ha errori, vuoto se la fonte
    non esiste o esiste senza endpoint (bug trovato nel collaudo
    2026-08-28: i comuni hanno sempre un endpoint, ma le fonti censite
    senza URL — es. i 27 teatri aggiunti prima di trovarne il sito —
    risultavano 'verde' solo perché la riga in sources esisteva, senza
    controllare che ci fosse davvero un sito da controllare)."""
    riga = conn.execute("SELECT endpoint, consecutive_errors FROM sources WHERE source_id = ?", (source_id,)).fetchone()
    if not riga or not riga["endpoint"]:
        return ""
    return _SIMBOLO_ROSSO if (riga["consecutive_errors"] or 0) > 0 else _SIMBOLO_VERDE


def pubblica_copertura_comuni(worksheet: gspread.Worksheet, conn: sqlite3.Connection) -> int:
    """Scrive il foglio `CoperturaComuni` (richiesto dall'utente 2026-08-28):
    una riga per comune del perimetro con lo stato di 4 canali (sito
    istituzionale, FB comune, FB/IG Pro Loco), per capire a colpo d'occhio
    dove manca ancora una fonte social. 'ig_comune' rimossa il 2026-08-28
    (richiesto dall'utente): trovata a 0/683 nel collaudo, nessun sito
    comunale ha mai un Instagram cercato/collegato — colonna senza
    contenuto informativo oggi. Nessuna colonna utente da preservare: è un
    cruscotto di sola lettura, ricostruito da SQLite ad ogni publish.

    'fb_proloco'/'ig_proloco' vuote distinguono ora due casi (2026-08-30,
    trovato dopo un caso reale — Cunico risultava "mai cercato" quando in
    realtà una ricerca web precedente aveva concluso, erroneamente,
    "nessuna Pro Loco trovata" senza lasciarne traccia): se esiste una
    riga `nessuna_fonte_trovata` per il comune, la cella mostra '—'
    (cercato, nessun esito) invece di restare vuota (mai cercato) — utile
    per sapere se serve una prima ricerca o solo un secondo tentativo più
    attento, senza però fidarsi ciecamente: quell'esito può comunque
    essere un falso negativo, come dimostrato da Cunico.
    """
    comuni_con_ricerca_negativa = {
        r["comune"]
        for r in conn.execute(
            "SELECT comune FROM coda_follow WHERE stato = 'nessuna_fonte_trovata'"
        ).fetchall()
    }

    comuni = conn.execute(
        "SELECT comune, fascia FROM comuni WHERE attivo='si' ORDER BY fascia ASC, comune ASC"
    ).fetchall()

    corpo = []
    for riga in comuni:
        comune = riga["comune"]
        slug = comune.strip().lower().replace(" ", "-")
        fb_proloco = _simbolo_social(conn, f"proloco-{slug}-facebook")
        ig_proloco = _simbolo_social(conn, f"proloco-{slug}-instagram")
        if comune in comuni_con_ricerca_negativa:
            fb_proloco = fb_proloco or _SIMBOLO_VERIFICATO_ASSENTE
            ig_proloco = ig_proloco or _SIMBOLO_VERIFICATO_ASSENTE
        corpo.append([
            riga["fascia"],
            comune,
            _simbolo_sito_istituzionale(conn, f"comune-{slug}"),
            _simbolo_social(conn, f"comune-{slug}-facebook"),
            fb_proloco,
            ig_proloco,
        ])

    worksheet.clear()
    worksheet.update([COLONNE_COPERTURA_COMUNI] + corpo, value_input_option="USER_ENTERED")
    _scrivi_legenda_copertura(worksheet, colonna="H")
    return len(corpo)


_LEGENDA_COPERTURA = [
    ["Legenda"],
    [f"{_SIMBOLO_VERDE}  seguito / sito raggiungibile senza errori"],
    [f"{_SIMBOLO_GRIGIO}  individuato ma non ancora confermato (da seguire, o candidato dal feed)"],
    [f"{_SIMBOLO_ROSSO}  tentativo fallito, url non valido, in quarantena, o sito con errori"],
    [f"{_SIMBOLO_VERIFICATO_ASSENTE}  cercato con esito negativo esplicito (non solo \"mai censito\")"],
    ["(vuoto)  mai cercato"],
]


def _scrivi_legenda_copertura(worksheet: gspread.Worksheet, colonna: str) -> None:
    """Legenda dei simboli (richiesta dall'utente 2026-08-31), scritta a
    fianco dei dati invece che sotto: i due fogli di copertura crescono
    per righe (un comune/entità per riga), non per colonne — una legenda
    sotto verrebbe riscritta sopra ai dati veri al prossimo giro se la
    lista si allunga."""
    worksheet.update(
        _LEGENDA_COPERTURA,
        f"{colonna}1:{colonna}{len(_LEGENDA_COPERTURA)}",
        value_input_option="USER_ENTERED",
    )


COLONNE_COPERTURA_ALTRE_ENTITA = ["tipologia", "nome", "sito", "facebook", "instagram"]

_SUFFISSI_CANALE = ("-sito", "-facebook", "-instagram")


def _nome_entita(source_id: str) -> str:
    """Toglie il suffisso canale (-sito/-facebook/-instagram) da un
    source_id, per raggruppare più fonti dello stesso soggetto (es.
    'aggregatore-teatro-del-rimbombo-facebook' e '...-instagram') sotto lo
    stesso nome. Se non c'è suffisso noto, il source_id è già il nome."""
    for suffisso in _SUFFISSI_CANALE:
        if source_id.endswith(suffisso):
            return source_id[: -len(suffisso)]
    return source_id


def pubblica_copertura_altre_entita(worksheet: gspread.Worksheet, conn: sqlite3.Connection) -> int:
    """Scrive il foglio `CoperturaAltreEntita` (richiesto dall'utente
    2026-08-28): stesso check di `CoperturaComuni` ma per le fonti che non
    sono un comune del perimetro — teatri, compagnie/progetti itineranti,
    aggregatori, e le Pro Loco il cui comune NON è nel perimetro (quelle
    con comune in perimetro sono già visibili in CoperturaComuni, non
    duplicate qui). Escluse anche le fonti sintetiche 'feed-{piattaforma}-
    {handle}' generate da feed_social.py: sono un artefatto tecnico, non
    un'entità reale (il soggetto è già censito altrove con lo slug
    corretto, bug trovato dall'utente 2026-08-28). 'tipologia' al posto di
    'fascia' (i comuni hanno una fascia di distanza, queste entità no);
    poi sito/facebook/instagram per ciascuna. Nessuna colonna utente da
    preservare: sola lettura, ricostruito ad ogni publish.
    """
    comuni_perimetro = {
        r["comune"].strip().lower().replace(" ", "-")
        for r in conn.execute("SELECT comune FROM comuni WHERE attivo='si'").fetchall()
    }

    entita: dict[str, str] = {}  # nome -> categoria/tipologia

    # 'feed-{piattaforma}-{handle_autore}' (feed_social.py) non è
    # un'entità: è un artefatto tecnico creato per tracciare i post letti
    # dal feed di un handle già seguito. Il vero soggetto (comune o Pro
    # Loco) è già censito altrove in coda_follow con lo slug corretto —
    # 'feed-facebook-comunechieri' e 'comune-chieri-facebook' sono la
    # stessa entità, la seconda è quella giusta da mostrare qui (bug
    # trovato dall'utente 2026-08-28: comparivano come righe fantasma).
    for row in conn.execute(
        "SELECT source_id, categoria FROM sources "
        "WHERE source_id NOT LIKE 'comune-%' AND source_id NOT LIKE 'feed-%'"
    ).fetchall():
        source_id, categoria = row["source_id"], row["categoria"]
        nome = _nome_entita(source_id)
        if nome.startswith("proloco-") and nome[len("proloco-"):] in comuni_perimetro:
            continue
        entita.setdefault(nome, categoria or "")

    for row in conn.execute(
        "SELECT source_id, categoria FROM coda_follow "
        "WHERE source_id NOT LIKE 'comune-%' AND source_id NOT LIKE 'sconosciuto-%' "
        "AND stato != 'nessuna_fonte_trovata'"
    ).fetchall():
        source_id, categoria = row["source_id"], row["categoria"]
        nome = _nome_entita(source_id)
        if nome.startswith("proloco-") and nome[len("proloco-"):] in comuni_perimetro:
            continue
        entita.setdefault(nome, categoria or "")

    corpo = []
    for nome in sorted(entita):
        # Il sito vive in sources con due pattern diversi: le fonti T0/T1
        # dirette (teatro-*, aggregatore-visitlmr) usano il nome nudo come
        # source_id, le Pro Loco con sito proprio usano il suffisso
        # esplicito '-sito' (proloco-{comune}-sito). Si prova prima il nome
        # nudo, poi il suffisso — mai entrambi per la stessa entità.
        sito = _simbolo_sito_istituzionale(conn, nome) or _simbolo_sito_istituzionale(conn, f"{nome}-sito")
        corpo.append([
            entita[nome],
            nome,
            sito,
            _simbolo_social(conn, f"{nome}-facebook"),
            _simbolo_social(conn, f"{nome}-instagram"),
        ])

    worksheet.clear()
    worksheet.update([COLONNE_COPERTURA_ALTRE_ENTITA] + corpo, value_input_option="USER_ENTERED")
    _scrivi_legenda_copertura(worksheet, colonna="G")
    return len(corpo)


COLONNE_LOG = [
    "run_id", "tipo", "inizio", "fine", "durata_min", "fonti_tentate", "fonti_ok",
    "fonti_errore", "artefatti", "chiamate_llm", "eventi_nuovi", "eventi_aggiornati",
    "in_quarantena", "archiviati", "note",
]


def pubblica_log(worksheet: gspread.Worksheet, conn: sqlite3.Connection, limite: int = 200) -> int:
    """Scrive il foglio `Log` (M11): storico dei run.py run, più recenti
    prima. Nessuna colonna utente da preservare, sola lettura per l'utente."""
    cur = conn.execute(f"SELECT * FROM runs ORDER BY inizio DESC LIMIT {int(limite)}")
    corpo = [[dict(row).get(col, "") or "" for col in COLONNE_LOG] for row in cur.fetchall()]
    worksheet.clear()
    worksheet.update([COLONNE_LOG] + corpo, value_input_option="USER_ENTERED")
    return len(corpo)


COLONNE_STATO = ["indicatore", "valore", "semaforo"]


def pubblica_stato(worksheet: gspread.Worksheet, indicatori) -> int:
    """Scrive il foglio `Stato` (M11): un cruscotto di sola lettura, nessuna
    colonna utente da preservare (a differenza di Eventi/Serie)."""
    corpo = [[i.nome, i.valore, i.semaforo] for i in indicatori]
    worksheet.clear()
    worksheet.update([COLONNE_STATO] + corpo, value_input_option="USER_ENTERED")
    return len(corpo)


def righe_da_sqlite(conn: sqlite3.Connection) -> list[dict]:
    """Tutti gli eventi attivi (non archiviati), con la fascia del comune
    già risolta (03: `Eventi` = vista sui prossimi giorni/fasce A-B,
    `Eventi_estesi` = tutto il resto — serve la fascia per separarli,
    2026-08-31, richiesto dall'utente dopo aver notato che entrambi i
    fogli 'estesi' risultavano vuoti). `events` non ha una colonna
    fascia propria: risolta con un JOIN su `comuni.comune`, la stessa
    chiave già usata altrove nel progetto per collegare un evento al suo
    comune (nessuna colonna comune_id in events, il nome resta la fonte
    di verità)."""
    cur = conn.execute(
        """
        SELECT e.event_id AS id, e.titolo, e.descrizione, e.tipologia, e.data_inizio,
               e.ora_inizio, e.data_fine, e.ora_fine, e.serie_id, e.occorrenza, e.comune,
               e.luogo, e.km, e.minuti, e.prezzo, e.organizzatore, e.url, e.url_immagine,
               e.confidenza, e.stato, e.note, e.primo_visto, e.ultimo_visto,
               e.bloccato, e.soppressa, c.fascia
        FROM events e
        LEFT JOIN comuni c ON c.comune = e.comune AND c.attivo = 'si'
        WHERE e.archiviato = 'no'
        ORDER BY e.data_inizio ASC, e.km ASC
        """
    )
    righe = [dict(row) for row in cur.fetchall()]

    fonti_per_evento: dict[str, list[str]] = {}
    for r in conn.execute("SELECT event_id, source_id FROM event_sources").fetchall():
        fonti_per_evento.setdefault(r["event_id"], []).append(r["source_id"])
    for riga in righe:
        riga["fonti"] = ", ".join(fonti_per_evento.get(riga["id"], []))

    return righe


def righe_eventi_vista_principale(righe: list[dict], config) -> list[dict]:
    """03/12: il foglio `Eventi` è una vista, non tutto l'elenco — solo i
    prossimi `vista_principale_giorni` giorni, nelle fasce
    `vista_principale_fasce` (default 21 giorni, A/B). Un evento con
    fascia non risolvibile (comune fuori perimetro/non attivo) non entra
    mai nella vista principale: non è né A né B."""
    oggi = date.today().isoformat()
    limite = (date.today() + timedelta(days=config.vista_principale_giorni)).isoformat()
    fasce = set(config.vista_principale_fasce)
    return [
        r for r in righe
        if r["fascia"] in fasce and oggi <= (r["data_inizio"] or "") <= limite
    ]


def righe_eventi_estesi(righe: list[dict], config) -> list[dict]:
    """03: `Eventi_estesi` è il complemento della vista principale — tutto
    ciò che non rientra nei prossimi `vista_principale_giorni` giorni o
    nelle fasce `vista_principale_fasce`. Include anche gli eventi con
    fascia non risolvibile: 'il resto' li deve comunque contenere da
    qualche parte, non far sparire silenziosamente un evento reale."""
    principali = {r["id"] for r in righe_eventi_vista_principale(righe, config)}
    return [r for r in righe if r["id"] not in principali]


def righe_quarantena_da_sqlite(conn: sqlite3.Connection) -> list[dict]:
    """07.3.6: la quarantena è solo uno stato del ciclo di vita di un evento,
    non un'entità diversa — stesse colonne di Eventi (COLONNE_EVENTI),
    filtrate su stato='quarantena'."""
    return [riga for riga in righe_da_sqlite(conn) if riga["stato"] == "quarantena"]


def righe_archivio_da_sqlite(conn: sqlite3.Connection) -> list[dict]:
    """03: `Archivio` riceve gli eventi con `archiviato='si'` (spostati da
    `archivia_eventi_conclusi`, mai finora pubblicati su questo foglio —
    2026-08-31, richiesto dall'utente dopo aver notato il foglio sempre
    vuoto). Stesse colonne base di Eventi, senza `fascia` (Archivio ha un
    proprio set di colonne più ridotto, COLONNE_ARCHIVIO)."""
    cur = conn.execute(
        """
        SELECT event_id AS id, titolo, descrizione, tipologia, data_inizio,
               data_fine, comune, luogo, organizzatore, url, serie_id,
               stato, note
        FROM events
        WHERE archiviato = 'si'
        ORDER BY data_fine DESC
        """
    )
    righe = [dict(row) for row in cur.fetchall()]

    fonti_per_evento: dict[str, list[str]] = {}
    for r in conn.execute("SELECT event_id, source_id FROM event_sources").fetchall():
        fonti_per_evento.setdefault(r["event_id"], []).append(r["source_id"])
    for riga in righe:
        riga["fonti"] = ", ".join(fonti_per_evento.get(riga["id"], []))

    return righe


COLONNE_ARCHIVIO = [
    "id", "titolo", "descrizione", "tipologia", "data_inizio", "data_fine",
    "comune", "luogo", "organizzatore", "url", "fonti", "serie_id",
    "stato", "note",
]


def pubblica_archivio(worksheet: gspread.Worksheet, righe: list[dict]) -> int:
    """Scrive il foglio `Archivio` (03, 2026-08-31): eventi con
    `archiviato='si'`, mai pubblicati finora. Sola lettura, nessuna
    colonna utente da preservare — una volta archiviato, un evento non
    torna più modificabile dall'operatore."""
    corpo = [[r.get(col, "") or "" for col in COLONNE_ARCHIVIO] for r in righe]
    worksheet.clear()
    worksheet.update([COLONNE_ARCHIVIO] + corpo, value_input_option="USER_ENTERED")
    return len(corpo)


def righe_eventi_per_mappa(conn: sqlite3.Connection) -> list[dict]:
    """16 (webapp mappa): eventi attivi (non archiviati) con le coordinate
    del comune, per il marker sulla mappa. Un JOIN dedicato invece di
    riusare `righe_da_sqlite` perché qui serve lat/lon, non fascia — e un
    evento senza comune risolvibile in perimetro viene escluso, mai
    piazzato a 0,0 (04.7: 'vuoto non è un errore, mai un valore
    indovinato'). Solo Eventi + Eventi_estesi (non Archivio, 16.6): la
    mappa serve a decidere dove andare, non a consultare lo storico."""
    cur = conn.execute(
        """
        SELECT e.event_id AS id, e.titolo, e.tipologia, e.data_inizio, e.data_fine,
               e.ora_inizio, e.comune, e.url, c.lat, c.lon, c.km
        FROM events e
        JOIN comuni c ON c.comune = e.comune AND c.attivo = 'si'
        WHERE e.archiviato = 'no' AND c.lat IS NOT NULL AND c.lon IS NOT NULL
        ORDER BY e.data_inizio ASC
        """
    )
    return [dict(row) for row in cur.fetchall()]


def scrivi_eventi_mappa_json(righe: list[dict], percorso: str | Path) -> int:
    """16 (webapp mappa): serializza gli eventi con coordinate in un JSON
    statico, letto dalla webapp `mappa.html` (nessun server, coerente col
    resto del progetto). L'array è scritto vuoto, non omesso, se non ci
    sono eventi con coordinate — così la pagina mostra 'nessun evento',
    non un errore di caricamento."""
    corpo = {
        "generato_il": date.today().isoformat() + "T00:00:00",
        "eventi": [
            {
                "id": r["id"],
                "titolo": r["titolo"],
                "comune": r["comune"],
                "lat": r["lat"],
                "lon": r["lon"],
                "km": r["km"],
                "data_inizio": r["data_inizio"],
                "data_fine": r["data_fine"] or r["data_inizio"],
                "tipologia": r["tipologia"],
                "url": r["url"] or "",
            }
            for r in righe
        ],
    }
    percorso = Path(percorso)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(json.dumps(corpo, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(corpo["eventi"])


COLONNE_SERIE = [
    "serie_id", "titolo", "tipologia", "comune", "luogo", "rrule",
    "regola_leggibile", "valida_dal", "valida_al", "eccezioni",
    "ultima_conferma", "stato", "fonti", "bloccata",
]

# 06.6-simile per le Serie: 'bloccata' è l'unica colonna che l'operatore
# imposta a mano sul foglio (sospende l'espansione automatica) — mai
# sovrascritta da un run, stesso principio di COLONNE_UTENTE per Eventi.
COLONNE_UTENTE_SERIE = {"bloccata"}


def pubblica_serie(worksheet: gspread.Worksheet, conn: sqlite3.Connection) -> int:
    valori = worksheet.get_all_records()
    overrides = {r["serie_id"]: r.get("bloccata", "") for r in valori if r.get("serie_id")}

    cur = conn.execute("SELECT * FROM series ORDER BY titolo ASC")
    corpo = []
    for row in cur.fetchall():
        riga = dict(row)
        bloccata_utente = overrides.get(riga["serie_id"], "")
        if bloccata_utente:
            riga["bloccata"] = bloccata_utente
        corpo.append([riga.get(col, "") or "" for col in COLONNE_SERIE])

    worksheet.clear()
    worksheet.update([COLONNE_SERIE] + corpo, value_input_option="USER_ENTERED")
    return len(corpo)
