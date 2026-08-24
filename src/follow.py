"""M9 — Follow semiautomatico (14.4, 14.5).

L'unica automazione del progetto che compie un'azione invece di limitarsi a
leggere: è quindi la più rischiosa, e i parametri sono conservativi apposta.

Separazione voluta: la logica di stato/circuito/precondizioni (testabile
senza browser) sta qui in funzioni pure; l'interazione vera con Playwright è
isolata in _apri_e_segui, così i test non toccano mai un browser reale.
"""
from __future__ import annotations

import random
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import Config


class CircuitoApertoError(Exception):
    """Il circuito di sicurezza è aperto: nessun follow finché non si riapre (14.5)."""


class SegnaleDiBloccoRilevato(Exception):
    """Captcha, azione bloccata, richiesta di verifica: apre il circuito (14.5)."""

    def __init__(self, messaggio: str, ore_apertura: int):
        super().__init__(messaggio)
        self.ore_apertura = ore_apertura


class IdentitaPaginaNonAttivaError(Exception):
    """14.2 opzione A: il login Facebook è personale, ma i follow devono
    partire dalla Pagina dedicata, mai dal profilo personale (14.1: 'ti
    inonda il feed personale con centinaia di pagine'). Se non si riesce a
    verificare o attivare l'identità Pagina, ci si ferma: non si procede
    mai sotto l'identità sbagliata."""


class IdentitaInstagramNonVerificataError(Exception):
    """Bug reale osservato (2026-08-24): la sessione salvata risultava
    loggata sul profilo Instagram personale dell'utente invece
    dell'account dedicato eventi.langa (probabile scelta errata durante
    il login manuale). Senza una verifica esplicita dello username attivo,
    ogni lettura/azione procede silenziosamente sull'identità sbagliata."""


@dataclass
class EsitoFollow:
    source_id: str
    esito: str  # 'seguito' | 'gia_seguito' | 'non_valido' | 'fallito'
    dettaglio: str = ""


def verifica_precondizioni(conn: sqlite3.Connection, piattaforma: str, config: Config, oggi: date | None = None) -> None:
    """14.4: se una precondizione fallisce, esce senza fare nulla. Solleva CircuitoApertoError."""
    oggi = oggi or date.today()

    riga_circuito = conn.execute(
        "SELECT valore FROM app_state WHERE chiave = ?", (f"circuito_aperto_fino_{piattaforma}",)
    ).fetchone()
    if riga_circuito and riga_circuito["valore"]:
        fino_a = datetime.fromisoformat(riga_circuito["valore"])
        if datetime.now() < fino_a:
            raise CircuitoApertoError(f"Circuito aperto fino a {fino_a.isoformat()} per {piattaforma}")

    ultimo_lotto = conn.execute(
        "SELECT valore FROM app_state WHERE chiave = ?", (f"ultimo_lotto_follow_{piattaforma}",)
    ).fetchone()
    if ultimo_lotto and ultimo_lotto["valore"]:
        ultimo = datetime.fromisoformat(ultimo_lotto["valore"])
        minuti_trascorsi = (datetime.now() - ultimo).total_seconds() / 60
        if minuti_trascorsi < config.follow_intervallo_lotti_min:
            raise CircuitoApertoError(
                f"Ultimo lotto {piattaforma} lanciato {minuti_trascorsi:.0f} minuti fa, "
                f"servono almeno {config.follow_intervallo_lotti_min} minuti"
            )

    totale_oggi = conn.execute(
        """
        SELECT COUNT(*) FROM coda_follow_log
        WHERE piattaforma = ? AND substr(data_follow, 1, 10) = ? AND esito = 'seguito'
        """,
        (piattaforma, oggi.isoformat()),
    ).fetchone()[0]
    if totale_oggi >= config.follow_max_giornalieri:
        raise CircuitoApertoError(
            f"Limite giornaliero raggiunto per {piattaforma}: {totale_oggi}/{config.follow_max_giornalieri}"
        )


def apri_circuito(conn: sqlite3.Connection, piattaforma: str, ore: int) -> None:
    """14.5: apre il circuito per `ore`. Nessun modo di forzarlo se non modificando Config a mano."""
    fino_a = (datetime.now() + timedelta(hours=ore)).isoformat()
    conn.execute(
        "INSERT INTO app_state (chiave, valore) VALUES (?, ?) ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore",
        (f"circuito_aperto_fino_{piattaforma}", fino_a),
    )
    conn.commit()


def prossimi_n_da_seguire(conn: sqlite3.Connection, piattaforma: str, n: int) -> list[sqlite3.Row]:
    """Legge i primi N in stato 'da_seguire' dalla coda, ordinati per priorità già applicata in bonifica."""
    return conn.execute(
        """
        SELECT rowid, * FROM coda_follow
        WHERE piattaforma = ? AND stato = 'da_seguire' AND tentativi < 3
        ORDER BY rowid ASC LIMIT ?
        """,
        (piattaforma, n),
    ).fetchall()


def pausa_casuale(config: Config, indice_nel_lotto: int) -> float:
    """14.4: pausa 25-70s, pausa lunga 2-4 minuti ogni 3-4 follow. Ritorna i secondi (per i test)."""
    if indice_nel_lotto > 0 and indice_nel_lotto % config.follow_pausa_lunga_ogni == 0:
        return random.uniform(config.follow_pausa_lunga_min_sec, config.follow_pausa_lunga_max_sec)
    return random.uniform(config.follow_pausa_min_sec, config.follow_pausa_max_sec)


def follow_batch(
    conn: sqlite3.Connection,
    config: Config,
    piattaforma: str,
    n: int | None = None,
    dry_run: bool = False,
    sessione_dir: Path | None = None,
) -> list[EsitoFollow]:
    """14.4: la procedura follow_batch. dry_run stampa/ritorna cosa farebbe, senza agire.

    Le precondizioni sono verificate una volta sola all'inizio: se falliscono,
    esce subito senza toccare nulla (14.4). Ogni singolo follow è isolato: un
    segnale di blocco apre il circuito e interrompe il lotto immediatamente,
    senza propagare l'eccezione oltre follow_batch stesso.
    """
    n = n or config.follow_per_lotto
    verifica_precondizioni(conn, piattaforma, config)

    candidati = prossimi_n_da_seguire(conn, piattaforma, n)
    if not candidati:
        return []

    if dry_run:
        return [EsitoFollow(c["source_id"], "dry_run", c["handle"]) for c in candidati]

    esiti: list[EsitoFollow] = []
    try:
        contesto = _apri_sessione_browser(piattaforma, sessione_dir)
    except Exception as exc:
        raise CircuitoApertoError(f"Impossibile aprire la sessione browser: {exc}") from exc

    try:
        if piattaforma == "facebook":
            _assicura_identita_pagina(contesto, config)
        else:
            verifica_identita_instagram(contesto, config)

        for indice, candidato in enumerate(candidati):
            try:
                esito = _apri_e_segui(contesto, candidato)
            except SegnaleDiBloccoRilevato as segnale:
                apri_circuito(conn, piattaforma, segnale.ore_apertura)
                _registra_esito(conn, candidato, "fallito", str(segnale))
                # Il tentativo va comunque riportato: senza questo, un
                # blocco al primo candidato produce esiti=[] e nasconde
                # completamente l'evento a chi legge l'output del comando
                # (14.5 richiede che il blocco sia visibile, non silenzioso).
                esiti.append(EsitoFollow(candidato["source_id"], "bloccato_da_circuito", str(segnale)))
                break  # 14.5: si ferma immediatamente, non continua il lotto

            _registra_esito(conn, candidato, esito.esito, esito.dettaglio)
            esiti.append(esito)

            if indice < len(candidati) - 1:
                time.sleep(pausa_casuale(config, indice + 1))
    finally:
        _chiudi_sessione_browser(contesto)

    conn.execute(
        "INSERT INTO app_state (chiave, valore) VALUES (?, ?) ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore",
        (f"ultimo_lotto_follow_{piattaforma}", datetime.now().isoformat()),
    )
    conn.commit()
    return esiti


def _registra_esito(conn: sqlite3.Connection, candidato: sqlite3.Row, esito: str, dettaglio: str) -> None:
    oggi = datetime.now().isoformat()
    if esito == "seguito":
        conn.execute(
            "UPDATE coda_follow SET stato='seguito', data_follow=? WHERE rowid=?",
            (oggi, candidato["rowid"]),
        )
    elif esito == "non_valido":
        conn.execute("UPDATE coda_follow SET stato='non_valido', note=? WHERE rowid=?", (dettaglio, candidato["rowid"]))
    else:
        conn.execute(
            "UPDATE coda_follow SET tentativi = tentativi + 1, note=? WHERE rowid=?",
            (dettaglio, candidato["rowid"]),
        )
        nuovo_tentativi = conn.execute("SELECT tentativi FROM coda_follow WHERE rowid=?", (candidato["rowid"],)).fetchone()[0]
        if nuovo_tentativi >= 3:
            conn.execute("UPDATE coda_follow SET stato='fallito' WHERE rowid=?", (candidato["rowid"],))

    conn.execute(
        "INSERT INTO coda_follow_log (source_id, piattaforma, esito, data_follow) VALUES (?, ?, ?, ?)",
        (candidato["source_id"], candidato["piattaforma"], esito, oggi),
    )
    conn.commit()


# --- Interazione browser reale: isolata qui, mai chiamata dai test automatici ---

def _cartella_profilo(piattaforma: str, sessione_dir: Path | None) -> Path:
    sessione_dir = sessione_dir or (Path(__file__).resolve().parent.parent / "data" / "sessions")
    sessione_dir.mkdir(parents=True, exist_ok=True)
    return sessione_dir / f"{piattaforma}_profile"


def _apri_sessione_browser(piattaforma: str, sessione_dir: Path | None):
    """Sessione persistente Playwright (14.5b): nessun re-login automatico.

    launch_persistent_context salva l'intero profilo del browser (cookie,
    storage) nella cartella indicata: dopo il primo login manuale, i lanci
    successivi riaprono la stessa sessione senza richiederlo di nuovo.
    Nessuna credenziale in chiaro nel codice o in config/.env.
    """
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch_persistent_context(
        user_data_dir=str(_cartella_profilo(piattaforma, sessione_dir)),
        headless=False,  # visibile: un login/interazione headless è più sospetto (14.3)
    )
    return {"playwright": playwright, "browser": browser, "piattaforma": piattaforma}


def _chiudi_sessione_browser(contesto: dict) -> None:
    if contesto is None:
        return
    contesto["browser"].close()
    contesto["playwright"].stop()


_URL_LOGIN = {
    "facebook": "https://www.facebook.com/login",
    "instagram": "https://www.instagram.com/accounts/login/",
}


def login_manuale(piattaforma: str, sessione_dir: Path | None = None) -> None:
    """Apre il browser sulla pagina di login e attende che l'utente lo chiuda a mano.

    Non fa altro: nessuna azione, nessuna verifica. Serve solo a fare il
    primo login una tantum su un profilo Chromium vuoto (14.3), prima di
    lanciare qualunque follow_batch. Va lanciata dal terminale locale
    dell'utente, mai da un ambiente senza display.
    """
    contesto = _apri_sessione_browser(piattaforma, sessione_dir)
    pagina = contesto["browser"].new_page()
    pagina.goto(_URL_LOGIN[piattaforma], timeout=30000)
    print(f"Fai login con l'account dedicato, poi chiudi la finestra del browser per continuare.")
    contesto["browser"].wait_for_event("close", timeout=0)
    contesto["playwright"].stop()


def _assicura_identita_pagina(contesto: dict, config: Config) -> None:
    """14.2 opzione A: verifica di essere 'loggati come Pagina', non come profilo personale.

    Naviga alla Pagina dedicata e controlla se compare l'indicatore che la
    identifica come identità attiva (il pulsante "Gestisci" o l'assenza del
    pulsante "Segui/Mi piace" sulla propria Pagina sono segnali affidabili:
    solo il gestore vede "Gestisci", un visitatore vede "Segui"). Se non è
    attiva, prova a cambiarla dal menu identità; se non riesce, si ferma —
    non si procede mai sotto l'identità sbagliata (14.1).
    """
    pagina = contesto["browser"].new_page()
    try:
        pagina.goto(config.facebook_page_url, timeout=20000)
        pagina.wait_for_timeout(1500)

        if _identita_pagina_attiva(pagina):
            return

        _tenta_cambio_a_pagina(pagina)
        pagina.wait_for_timeout(2000)

        if not _identita_pagina_attiva(pagina):
            raise IdentitaPaginaNonAttivaError(
                "Impossibile confermare l'identità Pagina dopo il tentativo di cambio. "
                "Nel browser aperto dalla sessione salvata, passa manualmente a "
                "'Usa Facebook come Pagina' sulla Pagina dedicata, poi rilancia."
            )
    finally:
        pagina.close()


def _identita_pagina_attiva(pagina) -> bool:
    contenuto = pagina.content().lower()
    return "gestisci" in contenuto or "manage" in contenuto


def verifica_identita_instagram(contesto: dict, config: Config) -> None:
    """Verifica che la sessione salvata sia loggata sull'account dedicato,
    non su un profilo personale (bug reale osservato: il login manuale può
    finire sull'account sbagliato se il browser ne propone più di uno).

    instagram.com/accounts/edit/ mostra sempre lo username reale in un
    campo di input "Nome utente", indipendentemente da lingua/interfaccia:
    più affidabile di un testo di menu. Se non corrisponde, si ferma senza
    eseguire alcuna lettura o azione — mai procedere sotto l'identità
    sbagliata (stesso principio di _assicura_identita_pagina per Facebook).
    """
    atteso = (config.instagram_username or "").strip().lower().lstrip("@")
    if not atteso:
        return  # nessun username configurato: nulla da verificare

    pagina = contesto["browser"].new_page()
    try:
        pagina.goto("https://www.instagram.com/accounts/edit/", timeout=20000)
        pagina.wait_for_timeout(2000)

        campo_username = pagina.query_selector('input[name="username"]')
        username_attivo = (campo_username.input_value() if campo_username else "").strip().lower()

        if not username_attivo:
            raise IdentitaInstagramNonVerificataError(
                "Impossibile leggere lo username della sessione attiva su Instagram. "
                "Verifica manualmente di essere loggato con l'account dedicato prima di rilanciare."
            )
        if username_attivo != atteso:
            raise IdentitaInstagramNonVerificataError(
                f"Sessione loggata come '{username_attivo}', atteso '{atteso}'. "
                "Elimina data/sessions/instagram_profile e rifai il login con l'account corretto "
                "('python run.py login --platform=instagram')."
            )
    finally:
        pagina.close()


def _tenta_cambio_a_pagina(pagina) -> None:
    """Il menu 'Cambia' / 'Sfoglia come Pagina' di Facebook cambia spesso
    struttura: qui si tenta i selettori più stabili (ruolo + testo), senza
    pretendere di coprire ogni variante dell'interfaccia. Se fallisce, la
    verifica successiva in _assicura_identita_pagina se ne accorge e ferma
    tutto invece di procedere alla cieca."""
    try:
        selettore_profilo = pagina.get_by_role("button", name=re.compile("account|profilo", re.IGNORECASE))
        if selettore_profilo.count() > 0:
            selettore_profilo.first.click()
            pagina.wait_for_timeout(800)
        link_cambia = pagina.get_by_text(re.compile("cambia", re.IGNORECASE))
        if link_cambia.count() > 0:
            link_cambia.first.click()
    except Exception:
        pass  # la verifica esplicita dopo la chiamata è l'unica fonte di verità


_SEGNALI_BLOCCO = {
    "captcha": 72,
    "checkpoint": 72,
    "riprova più tardi": 168,
    "azione bloccata": 168,
    "conferma la tua identità": None,  # None = blocco definitivo, richiede decisione umana
}


def _apri_e_segui(contesto: dict, candidato: sqlite3.Row) -> EsitoFollow:
    """14.4, ciclo del singolo follow. Solleva SegnaleDiBloccoRilevato su ogni segnale di 14.5."""
    pagina = contesto["browser"].new_page()
    try:
        pagina.goto(candidato["url"], timeout=20000)
        contenuto = pagina.content().lower()

        for segnale, ore in _SEGNALI_BLOCCO.items():
            if segnale in contenuto:
                if ore is None:
                    raise SegnaleDiBloccoRilevato(f"Richiesta di verifica identità: fermata definitiva", 24 * 365)
                raise SegnaleDiBloccoRilevato(f"Segnale di blocco rilevato: {segnale}", ore)

        handle_atteso = (candidato["handle"] or "").lower()
        if handle_atteso and handle_atteso not in pagina.url.lower() and handle_atteso not in contenuto:
            return EsitoFollow(candidato["source_id"], "non_valido", "handle non corrisponde alla pagina aperta")

        pulsante_segui = pagina.get_by_role("button", name=re.compile("segui", re.IGNORECASE))
        if pulsante_segui.count() == 0:
            return EsitoFollow(candidato["source_id"], "gia_seguito", "nessun pulsante Segui trovato")

        pulsante_segui.first.click()
        pagina.wait_for_timeout(1500)
        return EsitoFollow(candidato["source_id"], "seguito", candidato["handle"])
    finally:
        pagina.close()
