"""M9: logica di stato/circuito del follow (14.4, 14.5), nessun browser reale nei test."""
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import follow, store
from src.config import Config


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def _inserisci_candidato(conn: sqlite3.Connection, source_id: str, piattaforma: str = "facebook") -> None:
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, url, soggetto, comune, fascia, categoria, stato) "
        "VALUES (?, ?, ?, ?, ?, 'Calosso', 'A', 'proloco', 'da_seguire')",
        (source_id, piattaforma, source_id, f"https://facebook.com/{source_id}", source_id),
    )
    conn.commit()


def test_verifica_precondizioni_passa_su_coda_pulita():
    conn = _conn_di_prova()
    follow.verifica_precondizioni(conn, "facebook", Config())  # non deve sollevare


def test_verifica_precondizioni_fallisce_se_circuito_aperto():
    conn = _conn_di_prova()
    follow.apri_circuito(conn, "facebook", ore=72)

    try:
        follow.verifica_precondizioni(conn, "facebook", Config())
        assert False, "doveva sollevare CircuitoApertoError"
    except follow.CircuitoApertoError:
        pass


def test_verifica_precondizioni_fallisce_se_intervallo_lotti_troppo_corto():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO app_state (chiave, valore) VALUES ('ultimo_lotto_follow_facebook', ?)",
        (datetime.now().isoformat(),),
    )
    conn.commit()

    try:
        follow.verifica_precondizioni(conn, "facebook", Config(follow_intervallo_lotti_min=45))
        assert False, "doveva sollevare CircuitoApertoError"
    except follow.CircuitoApertoError:
        pass


def test_verifica_precondizioni_fallisce_se_limite_giornaliero_raggiunto():
    conn = _conn_di_prova()
    oggi = datetime.now().isoformat()
    for i in range(5):
        conn.execute(
            "INSERT INTO coda_follow_log (source_id, piattaforma, esito, data_follow) VALUES (?, 'facebook', 'seguito', ?)",
            (f"fonte-{i}", oggi),
        )
    conn.commit()

    try:
        follow.verifica_precondizioni(conn, "facebook", Config(follow_max_giornalieri=5))
        assert False, "doveva sollevare CircuitoApertoError"
    except follow.CircuitoApertoError:
        pass


def test_verifica_precondizioni_conta_solo_oggi_non_ieri():
    conn = _conn_di_prova()
    ieri = (datetime.now() - timedelta(days=1)).isoformat()
    for i in range(10):
        conn.execute(
            "INSERT INTO coda_follow_log (source_id, piattaforma, esito, data_follow) VALUES (?, 'facebook', 'seguito', ?)",
            (f"fonte-{i}", ieri),
        )
    conn.commit()

    follow.verifica_precondizioni(conn, "facebook", Config(follow_max_giornalieri=5))  # non deve sollevare


def test_prossimi_n_da_seguire_rispetta_lo_stato_e_i_tentativi():
    conn = _conn_di_prova()
    _inserisci_candidato(conn, "fonte-1")
    _inserisci_candidato(conn, "fonte-2")
    conn.execute("UPDATE coda_follow SET stato='seguito' WHERE source_id='fonte-2'")
    conn.execute("UPDATE coda_follow SET tentativi=3 WHERE source_id='fonte-1'")
    _inserisci_candidato(conn, "fonte-3")
    conn.commit()

    candidati = follow.prossimi_n_da_seguire(conn, "facebook", 10)
    source_ids = [c["source_id"] for c in candidati]

    assert source_ids == ["fonte-3"]  # fonte-1 ha troppi tentativi, fonte-2 è già seguita


def test_pausa_casuale_nel_range_atteso():
    config = Config(follow_pausa_min_sec=25, follow_pausa_max_sec=70, follow_pausa_lunga_ogni=4)
    for _ in range(50):
        p = follow.pausa_casuale(config, indice_nel_lotto=1)
        assert 25 <= p <= 70


def test_pausa_lunga_ogni_n_follow():
    config = Config(follow_pausa_lunga_ogni=4, follow_pausa_lunga_min_sec=120, follow_pausa_lunga_max_sec=240)
    for _ in range(50):
        p = follow.pausa_casuale(config, indice_nel_lotto=4)
        assert 120 <= p <= 240


def test_dry_run_non_modifica_lo_stato_della_coda():
    conn = _conn_di_prova()
    _inserisci_candidato(conn, "fonte-1")

    esiti = follow.follow_batch(conn, Config(), "facebook", n=5, dry_run=True)

    assert len(esiti) == 1
    assert esiti[0].esito == "dry_run"
    riga = conn.execute("SELECT stato FROM coda_follow WHERE source_id='fonte-1'").fetchone()
    assert riga["stato"] == "da_seguire"  # nessuna modifica


def test_follow_batch_con_coda_vuota_ritorna_lista_vuota():
    conn = _conn_di_prova()
    esiti = follow.follow_batch(conn, Config(), "facebook", n=5, dry_run=True)
    assert esiti == []


def test_follow_batch_rispetta_precondizioni_anche_in_dry_run():
    conn = _conn_di_prova()
    follow.apri_circuito(conn, "facebook", ore=72)
    _inserisci_candidato(conn, "fonte-1")

    try:
        follow.follow_batch(conn, Config(), "facebook", dry_run=True)
        assert False, "doveva sollevare CircuitoApertoError anche in dry-run"
    except follow.CircuitoApertoError:
        pass


def test_follow_batch_facebook_si_ferma_se_identita_pagina_non_attivabile(monkeypatch):
    """14.2 opzione A: se non si può confermare l'identità Pagina, nessun
    follow deve partire — mai procedere sotto il profilo personale (14.1)."""
    conn = _conn_di_prova()
    _inserisci_candidato(conn, "fonte-1", piattaforma="facebook")

    contesto_finto = {"piattaforma": "facebook"}
    chiuso = {"valore": False}

    def _apri_finto(piattaforma, sessione_dir):
        return contesto_finto

    def _chiudi_finto(contesto):
        chiuso["valore"] = True

    def _assicura_finto(contesto, config):
        raise follow.IdentitaPaginaNonAttivaError("simulato")

    monkeypatch.setattr(follow, "_apri_sessione_browser", _apri_finto)
    monkeypatch.setattr(follow, "_chiudi_sessione_browser", _chiudi_finto)
    monkeypatch.setattr(follow, "_assicura_identita_pagina", _assicura_finto)

    try:
        follow.follow_batch(conn, Config(), "facebook", dry_run=False)
        assert False, "doveva sollevare IdentitaPaginaNonAttivaError"
    except follow.IdentitaPaginaNonAttivaError:
        pass

    assert chiuso["valore"] is True  # la sessione va chiusa comunque
    riga = conn.execute("SELECT stato, tentativi FROM coda_follow WHERE source_id='fonte-1'").fetchone()
    assert riga["stato"] == "da_seguire"  # nessun tentativo registrato
    assert riga["tentativi"] == 0


def test_follow_batch_su_captcha_ritorna_esito_visibile_non_lista_vuota(monkeypatch):
    """Bug reale: un captcha sul primo candidato produceva esiti=[], e
    cmd_follow lo interpretava come 'nessun candidato', nascondendo
    completamente l'evento all'utente (14.5 richiede che il blocco sia
    visibile). Il circuito deve comunque aprirsi e il tentativo fallito
    deve comunque essere restituito."""
    conn = _conn_di_prova()
    _inserisci_candidato(conn, "fonte-1", piattaforma="instagram")
    _inserisci_candidato(conn, "fonte-2", piattaforma="instagram")

    contesto_finto = {"piattaforma": "instagram"}

    def _apri_finto(piattaforma, sessione_dir):
        return contesto_finto

    def _chiudi_finto(contesto):
        pass

    def _apri_e_segui_finto(contesto, candidato):
        raise follow.SegnaleDiBloccoRilevato("captcha rilevato", 72)

    monkeypatch.setattr(follow, "_apri_sessione_browser", _apri_finto)
    monkeypatch.setattr(follow, "_chiudi_sessione_browser", _chiudi_finto)
    monkeypatch.setattr(follow, "verifica_identita_instagram", lambda contesto, config: None)
    monkeypatch.setattr(follow, "_apri_e_segui", _apri_e_segui_finto)

    esiti = follow.follow_batch(conn, Config(), "instagram", n=2, dry_run=False)

    assert len(esiti) == 1  # il tentativo bloccato è comunque riportato
    assert esiti[0].esito == "bloccato_da_circuito"
    assert "captcha" in esiti[0].dettaglio.lower()

    # il circuito deve essere aperto per davvero
    try:
        follow.verifica_precondizioni(conn, "instagram", Config())
        assert False, "il circuito doveva essere aperto dopo il captcha"
    except follow.CircuitoApertoError:
        pass

    # il secondo candidato non è mai stato tentato: il lotto si è fermato subito
    riga2 = conn.execute("SELECT stato, tentativi FROM coda_follow WHERE source_id='fonte-2'").fetchone()
    assert riga2["stato"] == "da_seguire"
    assert riga2["tentativi"] == 0


# --- Bug reale (2026-08-25): Facebook non offre più uno switch esplicito
# "Usa Facebook come Pagina" — un amministratore vede sempre la vista
# pubblica quando visita la Pagina, quindi la vecchia verifica (bottone
# "Gestisci"/assenza di "Segui") è inaffidabile. Nuovo segnale: il nome
# dell'account PERSONALE loggato, letto dal blob "NAME":"{nome}" presente
# nell'HTML della pagina. ---

class _PaginaFacebookFinta:
    def __init__(self, nome_account: str | None):
        self._nome_account = nome_account

    def goto(self, url, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        if self._nome_account is None:
            return "<html>nessun nome qui</html>"
        return f'<script>{{"NAME":"{self._nome_account}"}}</script>'

    def close(self):
        pass


class _ContestoFacebookFinto:
    def __init__(self, nome_account: str | None):
        self._nome_account = nome_account

    class _Browser:
        def __init__(self, outer):
            self._outer = outer

        def new_page(self):
            return _PaginaFacebookFinta(self._outer._nome_account)

    def __getitem__(self, chiave):
        if chiave == "browser":
            return self._Browser(self)
        raise KeyError(chiave)


def test_assicura_identita_pagina_passa_se_nome_corrisponde():
    contesto = _ContestoFacebookFinto("Marco Mancini")
    config = Config(facebook_account_name="Marco Mancini")
    follow._assicura_identita_pagina(contesto, config)  # non deve sollevare


def test_assicura_identita_pagina_fallisce_su_account_sbagliato():
    contesto = _ContestoFacebookFinto("Altro Utente")
    config = Config(facebook_account_name="Marco Mancini")

    try:
        follow._assicura_identita_pagina(contesto, config)
        assert False, "doveva sollevare IdentitaPaginaNonAttivaError"
    except follow.IdentitaPaginaNonAttivaError as exc:
        assert "Altro Utente" in str(exc)
        assert "Marco Mancini" in str(exc)


def test_assicura_identita_pagina_fallisce_se_nome_non_leggibile():
    contesto = _ContestoFacebookFinto(None)
    config = Config(facebook_account_name="Marco Mancini")

    try:
        follow._assicura_identita_pagina(contesto, config)
        assert False, "doveva sollevare IdentitaPaginaNonAttivaError"
    except follow.IdentitaPaginaNonAttivaError:
        pass


def test_assicura_identita_pagina_case_insensitive():
    contesto = _ContestoFacebookFinto("marco mancini")
    config = Config(facebook_account_name="Marco Mancini")
    follow._assicura_identita_pagina(contesto, config)  # non deve sollevare


def test_assicura_identita_pagina_nessun_nome_configurato_non_verifica():
    contesto = _ContestoFacebookFinto(None)
    config = Config(facebook_account_name="")
    follow._assicura_identita_pagina(contesto, config)  # non deve sollevare


# --- Bug reale: la sessione salvata era loggata sul profilo Instagram
# personale invece dell'account dedicato eventi.langa (04.7/14.1: mai
# procedere in silenzio sotto un'identità non verificata) ---

class _ImgFinta:
    def __init__(self, alt: str):
        self._alt = alt

    def get_attribute(self, nome):
        if nome == "alt":
            return self._alt
        return None


class _PaginaInstagramFinta:
    def __init__(self, username: str | None):
        self._username = username

    def goto(self, url, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def query_selector_all(self, selettore):
        if self._username is None:
            return []  # simula 'link al profilo non trovato'
        return [
            _ImgFinta("Storia"),  # rumore: un'immagine senza alt utile
            _ImgFinta(f"Immagine del profilo di {self._username}"),
        ]

    def close(self):
        pass


class _ContestoInstagramFinto:
    def __init__(self, username: str | None):
        self._username = username

    class _Browser:
        def __init__(self, outer):
            self._outer = outer

        def new_page(self):
            return _PaginaInstagramFinta(self._outer._username)

    def __getitem__(self, chiave):
        if chiave == "browser":
            return self._Browser(self)
        raise KeyError(chiave)


def test_verifica_identita_instagram_passa_se_username_corrisponde():
    contesto = _ContestoInstagramFinto("eventi.langa")
    config = Config()  # instagram_username default 'eventi.langa'
    follow.verifica_identita_instagram(contesto, config)  # non deve sollevare


def test_verifica_identita_instagram_fallisce_su_profilo_sbagliato():
    """Bug reale osservato: la sessione era loggata come profilo personale."""
    contesto = _ContestoInstagramFinto("marco.personale")
    config = Config()

    try:
        follow.verifica_identita_instagram(contesto, config)
        assert False, "doveva sollevare IdentitaInstagramNonVerificataError"
    except follow.IdentitaInstagramNonVerificataError as exc:
        assert "marco.personale" in str(exc)
        assert "eventi.langa" in str(exc)


def test_verifica_identita_instagram_fallisce_se_username_non_leggibile():
    contesto = _ContestoInstagramFinto(None)
    config = Config()

    try:
        follow.verifica_identita_instagram(contesto, config)
        assert False, "doveva sollevare IdentitaInstagramNonVerificataError"
    except follow.IdentitaInstagramNonVerificataError:
        pass


def test_verifica_identita_instagram_case_insensitive():
    contesto = _ContestoInstagramFinto("Eventi.Langa")
    config = Config()
    follow.verifica_identita_instagram(contesto, config)  # non deve sollevare
