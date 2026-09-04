"""M10: logica pura del feed social (attribuzione, separazione follow/lettura,
parsing selettori) — nessun browser reale, 15.1 regola 8."""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import feed_social, store
from src.config import Config
from src.extractor.client import ExtractorClient
from src.extractor.providers import ProviderLLM


def _conn_di_prova() -> sqlite3.Connection:
    """PRAGMA foreign_keys=ON: bug reale (2026-08-27) mai intercettato dai
    test perché store.connect() lo attiva ma i test usavano una connessione
    diretta senza — elabora_post falliva con IntegrityError solo in
    produzione (artifacts.source_id ha una foreign key su sources, mai
    popolata per gli artefatti del feed prima del fix)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(store.SCHEMA_SQL)
    return conn


def test_verifica_separazione_passa_senza_follow_precedente():
    conn = _conn_di_prova()
    feed_social.verifica_separazione_da_follow(conn, "facebook")  # non deve sollevare


def test_verifica_separazione_fallisce_se_follow_recente():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO app_state (chiave, valore) VALUES ('ultimo_lotto_follow_facebook', ?)",
        (datetime.now().isoformat(),),
    )
    conn.commit()

    try:
        feed_social.verifica_separazione_da_follow(conn, "facebook", minuti_minimi=60)
        assert False, "doveva sollevare SessioneTroppoVicinaAlFollowError"
    except feed_social.SessioneTroppoVicinaAlFollowError:
        pass


def test_verifica_separazione_passa_se_follow_abbastanza_vecchio():
    conn = _conn_di_prova()
    vecchio = (datetime.now() - timedelta(hours=2)).isoformat()
    conn.execute(
        "INSERT INTO app_state (chiave, valore) VALUES ('ultimo_lotto_follow_facebook', ?)", (vecchio,)
    )
    conn.commit()
    feed_social.verifica_separazione_da_follow(conn, "facebook", minuti_minimi=60)  # non deve sollevare


def test_attribuisci_post_handle_noto_ritorna_riga():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('proloco-calosso-facebook', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()

    riga = feed_social.attribuisci_post(conn, "facebook", "ProLocoCalosso")
    assert riga is not None
    assert riga["comune"] == "Calosso"


def test_attribuisci_post_handle_sconosciuto_crea_candidato_e_ritorna_none():
    conn = _conn_di_prova()
    riga = feed_social.attribuisci_post(conn, "instagram", "prolocosconosciuta")
    assert riga is None

    candidato = conn.execute(
        "SELECT * FROM coda_follow WHERE piattaforma='instagram' AND handle='prolocosconosciuta'"
    ).fetchone()
    assert candidato is not None
    assert candidato["stato"] == "candidato_da_feed"
    assert candidato["comune"] == ""  # mai scartato, ma mai un comune inventato


def test_attribuisci_post_handle_noto_ma_senza_comune_non_pubblica():
    """Un handle già in coda_follow ma senza comune assegnato (es. in
    quarantena) non deve produrre un'attribuzione valida — nessun evento
    va pubblicato senza un comune attendibile."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'handlesenzacomune', '', 'quarantena')"
    )
    conn.commit()

    riga = feed_social.attribuisci_post(conn, "facebook", "handlesenzacomune")
    assert riga is None


def test_handle_da_href_profilo_facebook():
    assert feed_social._handle_da_href_profilo("/prolococalosso/", "facebook") == "prolococalosso"
    assert feed_social._handle_da_href_profilo("/prolococalosso?ref=x", "facebook") == "prolococalosso"


def test_handle_da_href_profilo_url_assoluto():
    """Bug reale (2026-08-27): nel feed reale l'href dell'autore è un URL
    assoluto con parametri di tracking, non relativo come nella pagina
    'seguiti' — split manuale su '/' produceva 'https:' come falso handle."""
    href = "https://www.facebook.com/ProLocoBUBBIO?__cft__[0]=AZZabc123&__tn__=-UC%2CP-R"
    assert feed_social._handle_da_href_profilo(href, "facebook") == "prolocobubbio"


def test_handle_da_href_profilo_instagram():
    assert feed_social._handle_da_href_profilo("/eventi.langa/", "instagram") == "eventi.langa"


def test_post_id_da_permalink_facebook():
    assert feed_social._post_id_da_permalink("/prolococalosso/posts/1234567890") == "1234567890"
    assert feed_social._post_id_da_permalink("/watch/videos/999888777") == "999888777"


def test_post_id_usa_hash_del_testo_se_url_senza_id_riconoscibile():
    """Bug reale (2026-08-27): nel feed principale l'unico link disponibile
    è quello dell'autore, con parametri di tracking (__cft__) diversi ad
    ogni caricamento — usarlo come ID romperebbe la change detection."""
    url_con_tracking_variabile = "/prolococalosso?__cft__[0]=AZYxyzABC123&__tn__=-UC"
    id1 = feed_social._post_id_da_permalink(url_con_tracking_variabile, testo="Sagra del Tartufo il 12 settembre")

    url_con_tracking_diverso = "/prolococalosso?__cft__[0]=DIVERSO999&__tn__=-UC"
    id2 = feed_social._post_id_da_permalink(url_con_tracking_diverso, testo="Sagra del Tartufo il 12 settembre")

    assert id1 == id2  # stesso testo, stesso id, nonostante l'URL cambi

    id3 = feed_social._post_id_da_permalink(url_con_tracking_variabile, testo="Un testo completamente diverso")
    assert id3 != id1


def test_post_id_da_permalink_instagram():
    assert feed_social._post_id_da_permalink("/p/ABC123xyz/") == "ABC123xyz"
    assert feed_social._post_id_da_permalink("/reel/XYZ987/") == "XYZ987"


class _ProviderFinto(ProviderLLM):
    def __init__(self, risposte):
        self._risposte = list(risposte)
        self.chiamate_con_immagini = []
        self.chiamate_prompt_utente = []

    def estrai(self, prompt_sistema, prompt_utente, immagini=None):
        self.chiamate_con_immagini.append(immagini)
        self.chiamate_prompt_utente.append(prompt_utente)
        return self._risposte.pop(0)


def _risposta_json(comune="Calosso", confidenza=92):
    return (
        '{"eventi": [{"titolo": "Sagra del Tartufo", "descrizione": "Degustazioni", "tipologia": "sagra", '
        '"data_inizio": "2026-09-12", "data_fine": "2026-09-12", "ora_inizio": "21:00", "ora_fine": null, '
        '"ricorrenza": {"e_ricorrente": false}, "luogo_testuale": "Piazza Roma", "comune_testuale": "%s", '
        '"indirizzo": null, "prezzo": null, "organizzatore": null, "anno_esplicito": true, '
        '"confidenza": %d, "campi_incerti": [], "note_estrazione": null}], '
        '"non_e_un_evento": false, "motivo": null}'
    ) % (comune, confidenza)


def _risposta_non_evento():
    return '{"eventi": [], "non_e_un_evento": true, "motivo": "nessun evento nel testo"}'


def _conn_con_comune() -> sqlite3.Connection:
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'Calosso', 'AT', 44.74, 8.23, 0.0, 0, 'A', 'si')"
    )
    return conn


def test_elabora_post_handle_sconosciuto_ritorna_candidato():
    conn = _conn_con_comune()
    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolocosconosciuta", post_id="1",
        url="https://www.facebook.com/prolocosconosciuta/posts/1", testo="Sagra del tartufo sabato 12 settembre",
    )
    esito = feed_social.elabora_post(post, conn, Config())
    assert esito == "candidato"


def test_elabora_post_senza_testo_ritorna_senza_testo():
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()
    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1", testo=None,
    )
    assert feed_social.elabora_post(post, conn, Config()) == "senza_testo"


def test_elabora_post_pubblica_evento_con_estrattore():
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1",
        testo="Sagra del Tartufo sabato 12 settembre in Piazza Roma a Calosso, degustazioni e musica.",
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)
    assert esito == "pubblicato"

    riga = conn.execute("SELECT titolo, comune FROM events").fetchone()
    assert riga["titolo"] == "Sagra del Tartufo"
    assert riga["comune"] == "Calosso"


def test_elabora_post_senza_url_approfondimento_usa_url_immagine_remoto(tmp_path):
    """Richiesto dall'utente 2026-09-04: se l'LLM non trova un link
    esplicito 'scopri di più' nel testo, url_approfondimento deve comunque
    puntare all'URL remoto originale dell'immagine (non al solo path
    locale, che resta in url_immagine) — un link navigabile è meglio di
    niente."""
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])  # senza url_approfondimento nel JSON
    extractor = ExtractorClient(Config(), conn, provider=provider)

    immagine = tmp_path / "locandina.jpg"
    immagine.write_bytes(b"\xff\xd8\xff\xe0finto-jpeg")

    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1",
        testo="Sagra del Tartufo sabato 12 settembre in Piazza Roma a Calosso, degustazioni e musica.",
        image_paths=[str(immagine)],
        image_urls=["https://scontent.cdninstagram.com/locandina-originale.jpg"],
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)
    assert esito == "pubblicato"

    riga = conn.execute("SELECT url_immagine, url_approfondimento FROM events").fetchone()
    assert riga["url_immagine"] == str(immagine)
    assert riga["url_approfondimento"] == "https://scontent.cdninstagram.com/locandina-originale.jpg"


def test_elabora_post_senza_testo_con_immagine_usa_vlm(tmp_path):
    """Post senza didascalia utile ma con locandina allegata: deve passare
    per estrai_da_immagine (VLM) invece di essere scartato come
    'senza_testo' — collegamento mancante segnalato in STATO-PROGETTO.md."""
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    immagine = tmp_path / "locandina.jpg"
    immagine.write_bytes(b"\xff\xd8\xff\xe0finto-jpeg")

    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1",
        testo=None, image_paths=[str(immagine)],
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)
    assert esito == "pubblicato"
    assert provider.chiamate_con_immagini[0] is not None
    assert provider.chiamate_con_immagini[0][0] == immagine.read_bytes()


def test_elabora_post_con_testo_e_immagine_manda_entrambi_al_vlm(tmp_path):
    """2026-09-01, richiesto dall'utente dopo due casi reali (San Damiano,
    Valfenera): un post con testo breve ma un'immagine allegata con il
    dettaglio vero (programma con le date corrette) veniva letto SOLO dal
    testo — l'immagine non veniva mai nemmeno scaricata. Ora entrambi
    vanno all'estrattore nella stessa chiamata (VLM con caption)."""
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    immagine = tmp_path / "locandina.jpg"
    immagine.write_bytes(b"\xff\xd8\xff\xe0finto-jpeg")

    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1",
        testo="Stasera ultima serata, vedi programma allegato.",
        image_paths=[str(immagine)],
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)

    assert esito == "pubblicato"
    assert provider.chiamate_con_immagini[0] is not None  # è passata l'immagine
    assert "programma allegato" in provider.chiamate_prompt_utente[0]  # ed è passata la caption


def test_data_da_iso_converte_datetime_instagram():
    """2026-09-02, richiesto dall'utente (caso Valfenera f39bb10a29e1): un
    post letto giorni dopo la pubblicazione con testo relativo ('stasera')
    va ancorato alla data di PUBBLICAZIONE, non a quella di lettura —
    formato reale collaudato dal vivo su Instagram."""
    from datetime import date

    assert feed_social._data_da_iso("2026-08-27T07:03:46.000Z") == date(2026, 8, 27)


def test_data_da_iso_formato_inatteso_ritorna_none():
    """Isolamento totale (15.1 regola 4): un formato inatteso non deve
    sollevare, solo far ricadere sul default date.today() a valle."""
    assert feed_social._data_da_iso("non-una-data") is None
    assert feed_social._data_da_iso(None) is None


def test_elabora_post_usa_data_pubblicazione_come_riferimento():
    """2026-09-02: post.data_pubblicazione deve arrivare all'estrattore
    come data_riferimento, non il default date.today() — verificato
    guardando il prompt costruito (DATA_RIFERIMENTO: ...)."""
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'instagram', 'prolocovalfenera', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    from datetime import date

    post = feed_social.PostFeed(
        piattaforma="instagram", handle_autore="prolocovalfenera", post_id="1",
        url="https://www.instagram.com/p/abc123/",
        testo="Sagra del Tartufo stasera dalle 19.30 in Piazza Roma a Calosso, degustazioni e musica dal vivo.",
        data_pubblicazione=date(2026, 8, 27),
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)

    assert esito == "pubblicato"
    assert "DATA_RIFERIMENTO: 2026-08-27" in provider.chiamate_prompt_utente[0]


def test_elabora_post_carosello_manda_tutte_le_immagini_al_vlm(tmp_path):
    """2026-09-02, richiesto dall'utente (caso Valfenera f39bb10a29e1): un
    carosello Instagram di più immagini deve arrivare all'estrattore
    TUTTO insieme in una chiamata, non solo la prima — il dettaglio utile
    (le date dell'evento) era solo nella terza immagine."""
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'instagram', 'prolocovalfenera', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    img1 = tmp_path / "1.jpg"
    img1.write_bytes(b"\xff\xd8\xff\xe0prima-immagine")
    img2 = tmp_path / "2.jpg"
    img2.write_bytes(b"\xff\xd8\xff\xe0seconda-immagine")
    img3 = tmp_path / "3.jpg"
    img3.write_bytes(b"\xff\xd8\xff\xe0terza-immagine-con-le-date")

    post = feed_social.PostFeed(
        piattaforma="instagram", handle_autore="prolocovalfenera", post_id="1",
        url="https://www.instagram.com/p/abc123/",
        testo="Stasera vi aspettiamo dalle 19.30!",
        image_paths=[str(img1), str(img2), str(img3)],
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)

    assert esito == "pubblicato"
    immagini_passate = provider.chiamate_con_immagini[0]
    assert len(immagini_passate) == 3
    assert immagini_passate[2] == img3.read_bytes()


def test_scarica_immagine_post_popola_image_paths(tmp_path, monkeypatch):
    """2026-09-01: post.image_urls (letto dal DOM del feed) deve essere
    scaricato e trasformato in file locali prima dell'elaborazione."""
    import httpx

    class _RispostaFinta:
        status_code = 200
        content = b"\xff\xd8\xff\xe0contenuto-immagine-finta"

        def raise_for_status(self):
            pass

    class _ClientFinto:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return _RispostaFinta()

    monkeypatch.setattr(feed_social, "_CARTELLA_IMMAGINI_FEED", tmp_path)
    monkeypatch.setattr(httpx, "Client", _ClientFinto)

    post = feed_social.PostFeed(
        piattaforma="instagram", handle_autore="prolocotest", post_id="abc123",
        url="https://www.instagram.com/p/abc123/",
        image_urls=["https://cdninstagram.com/finta.jpg"],
    )
    percorsi = feed_social._scarica_immagine_post(post)

    assert len(percorsi) == 1
    assert Path(percorsi[0]).exists()
    assert Path(percorsi[0]).read_bytes() == b"\xff\xd8\xff\xe0contenuto-immagine-finta"


def test_scarica_immagine_post_carosello_scarica_tutte_le_immagini(tmp_path, monkeypatch):
    """2026-09-02: caso Valfenera f39bb10a29e1, il dettaglio utile (le
    date) era solo nella terza immagine del carosello — tutte le immagini
    di post.image_urls vanno scaricate, non solo la prima."""
    import httpx

    class _RispostaFinta:
        status_code = 200

        def __init__(self, contenuto):
            self.content = contenuto

        def raise_for_status(self):
            pass

    class _ClientFinto:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return _RispostaFinta(f"contenuto-{url}".encode())

    monkeypatch.setattr(feed_social, "_CARTELLA_IMMAGINI_FEED", tmp_path)
    monkeypatch.setattr(httpx, "Client", _ClientFinto)

    post = feed_social.PostFeed(
        piattaforma="instagram", handle_autore="prolocotest", post_id="carosello1",
        url="https://www.instagram.com/p/carosello1/",
        image_urls=[
            "https://cdninstagram.com/1.jpg",
            "https://cdninstagram.com/2.jpg",
            "https://cdninstagram.com/3.jpg",
        ],
    )
    percorsi = feed_social._scarica_immagine_post(post)

    assert len(percorsi) == 3
    for p in percorsi:
        assert Path(p).exists()


def test_scarica_immagine_post_nessun_url_ritorna_lista_vuota():
    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="x", post_id="1", url="https://x.it/1",
    )
    assert feed_social._scarica_immagine_post(post) == []


def test_elabora_post_immagine_scartata_dal_prefiltro_grafico_non_chiama_vlm(tmp_path):
    """M4 collegato (2026-08-28): un'immagine troppo piccola (chiaramente
    non una locandina) deve essere scartata PRIMA di spendere una chiamata
    VLM, non dopo — verifica che il provider non venga mai invocato."""
    import io

    from PIL import Image

    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([])  # nessuna risposta pronta: se venisse chiamato, il test fallirebbe con IndexError
    extractor = ExtractorClient(Config(), conn, provider=provider)

    piccola = Image.new("RGB", (50, 50), color=(200, 200, 200))
    buf = io.BytesIO()
    piccola.save(buf, format="PNG")
    immagine = tmp_path / "troppo_piccola.png"
    immagine.write_bytes(buf.getvalue())

    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1",
        testo=None, image_paths=[str(immagine)],
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)
    assert esito == "scartato"
    assert provider.chiamate_con_immagini == []


def _locandina_reale_come_bytes():
    """Immagine reale (non finta) che supera tutte le regole del pre-filtro
    grafico: dimensioni valide, aspect ratio plausibile, molti bordi/testo
    simulati con righe ad alto contrasto."""
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 1000), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    for y in range(50, 950, 15):
        draw.line([(50, y), (750, y)], fill=(0, 0, 0), width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_elabora_post_riusa_cache_pHash_senza_richiamare_il_provider(tmp_path):
    """M4 (12.10 'la leva più efficace di tutte'): la stessa locandina letta
    una seconda volta (stesso pHash, es. ripubblicata da un altro canale)
    non deve chiamare di nuovo il VLM — riusa l'estrazione già in cache."""
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()

    immagine_bytes = _locandina_reale_come_bytes()
    immagine1 = tmp_path / "locandina1.png"
    immagine1.write_bytes(immagine_bytes)
    immagine2 = tmp_path / "locandina2.png"
    immagine2.write_bytes(immagine_bytes)  # bytes identici -> stesso pHash

    provider = _ProviderFinto([_risposta_json(confidenza=92)])  # una sola risposta pronta
    extractor = ExtractorClient(Config(), conn, provider=provider)

    post1 = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1",
        testo=None, image_paths=[str(immagine1)],
    )
    esito1 = feed_social.elabora_post(post1, conn, Config(), extractor)
    assert esito1 == "pubblicato"
    assert len(provider.chiamate_con_immagini) == 1  # prima chiamata reale

    post2 = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="2",
        url="https://www.facebook.com/prolococalosso/posts/2",
        testo=None, image_paths=[str(immagine2)],
    )
    # provider ha una sola risposta pronta: se venisse richiamato solleverebbe IndexError
    esito2 = feed_social.elabora_post(post2, conn, Config(), extractor)
    assert esito2 == "pubblicato"
    assert len(provider.chiamate_con_immagini) == 1  # nessuna seconda chiamata, riusata la cache


def test_elabora_post_gruppo_senza_comune_esplicito_non_pubblica():
    """14.6: per i gruppi il comune non va mai inferito dall'autore del
    post — un evento senza comune_testuale esplicito non deve pubblicare."""
    conn = _conn_con_comune()
    provider = _ProviderFinto([_risposta_json(comune="")])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="sagrepiemonte", post_id="1",
        url="https://www.facebook.com/groups/12345/posts/1",
        testo="Sagra del Tartufo sabato 12 settembre, degustazioni e musica.",
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)
    assert esito == "gruppo_comune_non_inferito"

    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_elabora_post_non_evento_scartato():
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([_risposta_non_evento()])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1",
        testo="Buongiorno a tutti, oggi splende il sole su Calosso!",
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)
    assert esito == "scartato"


def test_pulisci_testo_post_rimuove_righe_facebook_ripetute():
    """Bug reale (2026-08-27): il contenitore del post include 'Facebook'
    ripetuto (alt-text di icone in un carosello) prima del vero testo,
    in numero variabile a ogni caricamento — va rimosso per non rompere
    la change detection basata sull'hash del testo."""
    testo = "Facebook\nFacebook\nFacebook\nPro Loco Roddino\n \n·\nGrazie \n \n \nTesto del post reale."
    pulito = feed_social._pulisci_testo_post(testo)
    assert "Facebook" not in pulito
    assert "Pro Loco Roddino" in pulito
    assert "Testo del post reale." in pulito


def test_pulisci_testo_post_rimuove_caratteri_offuscati():
    """Bug reale (2026-08-27): alcuni post hanno la data offuscata
    carattere per carattere con un marcatore Unicode invisibile
    (categoria Mark, es. U+034F) appiccicato a ogni lettera — righe
    illeggibili, vanno scartate."""
    riga_offuscata_1 = "t" + "͏"
    riga_offuscata_2 = "g" + "́"  # combining acute accent, altro caso plausibile
    testo = f"Pro Loco BUBBIO\n{riga_offuscata_1}\n{riga_offuscata_2}\n͏"
    pulito = feed_social._pulisci_testo_post(testo)
    assert pulito == "Pro Loco BUBBIO"


def test_e_carattere_offuscato_non_scarta_testo_normale():
    assert feed_social._e_carattere_offuscato("Grazie") is False
    assert feed_social._e_carattere_offuscato("Un'estate intensa") is False


def test_post_id_stabile_dopo_pulizia_nonostante_ripetizioni_variabili():
    """Lo stesso post, con un numero diverso di righe 'Facebook' residue
    (che varia a ogni caricamento reale della pagina), deve produrre lo
    stesso post_id una volta ripulito — altrimenti la change detection
    non riconoscerebbe mai un post già visto."""
    testo_a = "Facebook\n" * 15 + "Pro Loco Roddino\nGrazie per tutto."
    testo_b = "Facebook\n" * 22 + "Pro Loco Roddino\nGrazie per tutto."

    pulito_a = feed_social._pulisci_testo_post(testo_a)
    pulito_b = feed_social._pulisci_testo_post(testo_b)
    assert pulito_a == pulito_b

    id_a = feed_social._post_id_da_permalink("/prolocoroddino?__cft__=X", testo=pulito_a)
    id_b = feed_social._post_id_da_permalink("/prolocoroddino?__cft__=Y", testo=pulito_b)
    assert id_a == id_b


def test_handle_da_href_profilo_facebook_profile_php_con_id():
    """Stesso bug già risolto in bonifica_social.py per il follow: i
    profili senza username personalizzato usano profile.php?id=NNN — va
    identificato dall'id, non dal segmento letterale 'profile.php' (che
    collasserebbe profili diversi sullo stesso handle-fasullo)."""
    href = "https://www.facebook.com/profile.php?id=100087914714647&__cft__[0]=AZY5uj9Ai1EP"
    assert feed_social._handle_da_href_profilo(href, "facebook") == "profile.php?id=100087914714647"


class _TabFinta:
    def __init__(self, testo: str, selezionata: bool):
        self._testo = testo
        self._selezionata = selezionata
        self.click_chiamato = False

    def inner_text(self) -> str:
        return self._testo

    def get_attribute(self, nome: str) -> str | None:
        if nome == "aria-selected":
            return "true" if self._selezionata else "false"
        return None

    def click(self) -> None:
        self.click_chiamato = True
        self._selezionata = True


class _PaginaFinta:
    def __init__(self, tabs: list[_TabFinta]):
        self._tabs = tabs
        self.wait_calls = 0

    def query_selector_all(self, selettore: str):
        return self._tabs if selettore == 'div[role="tab"]' else []

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_calls += 1


def test_seleziona_tab_seguiti_clicca_se_non_selezionata():
    """Bug reale trovato dall'utente (2026-08-29): la home Instagram apre
    di default su 'Per te' (algoritmo misto), non sui soli seguiti."""
    tab_per_te = _TabFinta("Per te", selezionata=True)
    tab_seguiti = _TabFinta("Seguiti", selezionata=False)
    pagina = _PaginaFinta([tab_per_te, tab_seguiti])

    feed_social._seleziona_tab_seguiti_instagram(pagina)

    assert tab_seguiti.click_chiamato is True


def test_seleziona_tab_seguiti_non_clicca_se_gia_selezionata():
    tab_seguiti = _TabFinta("Seguiti", selezionata=True)
    pagina = _PaginaFinta([tab_seguiti])

    feed_social._seleziona_tab_seguiti_instagram(pagina)

    assert tab_seguiti.click_chiamato is False


def test_seleziona_tab_seguiti_non_solleva_errore_se_tab_assente():
    """UI cambiata o tab non trovata: il giro deve proseguire comunque
    (isolamento totale degli errori), non bloccarsi."""
    pagina = _PaginaFinta([])
    feed_social._seleziona_tab_seguiti_instagram(pagina)  # non deve sollevare


class _PaginaScrollFinta:
    """Simula pagina.evaluate() alternando lo script di espansione 'Vedi
    altro' (ignorato, ritorna solo un conteggio) e lo script di raccolta
    post (ritorna la lista grezza dell'iterazione corrente)."""

    def __init__(self, script_espandi_atteso: str, iterazioni: list[list[dict]]):
        self._script_espandi_atteso = script_espandi_atteso
        self._iterazioni = iterazioni
        self.chiamate_espandi = 0
        self.chiamate_raccogli = 0
        self.mouse = self
        self._indice = 0

    def evaluate(self, script: str):
        if script == self._script_espandi_atteso:
            self.chiamate_espandi += 1
            return 0
        self.chiamate_raccogli += 1
        if self._indice >= len(self._iterazioni):
            return []
        risultato = self._iterazioni[self._indice]
        self._indice += 1
        return risultato

    def wheel(self, x, y):
        pass

    def wait_for_timeout(self, ms):
        pass


def test_scroll_feed_espande_vedi_altro_prima_di_leggere():
    """2026-09-01, richiesto dall'utente: un evento reale (Festival Contro,
    Castagnole delle Lanze) è finito in quarantena a bassa confidenza
    perché il post letto dal feed era troncato ('...Altro...') — l'LLM
    vedeva solo un frammento. Verificato dal vivo (Playwright, sessione
    reale) che cliccare i pulsanti 'Vedi altro' prima di leggere il testo
    espande davvero il contenuto (292→979 caratteri su un post reale)."""
    grezzi = [{
        "href": "/prolococastagnole",
        "permalink": "/prolococastagnole/posts/123",
        "testo": "Festival Contro. Castagnole delle Lanze. Lunedì 31 agosto.",
    }]
    pagina = _PaginaScrollFinta(
        feed_social._JS_ESPANDI_VEDI_ALTRO["facebook"],
        [grezzi, []],
    )

    risultato = feed_social._scroll_feed_e_raccogli(
        pagina, feed_social._JS_RACCOGLI_POST_FACEBOOK, "facebook", ultimo_visto=None, max_scroll=2
    )

    assert pagina.chiamate_espandi >= 1
    assert pagina.chiamate_espandi <= pagina.chiamate_raccogli
    assert len(risultato) == 1


class _PaginaScrollInstagramFinta:
    """Come _PaginaScrollFinta ma distingue anche lo script di espansione
    caroselli (solo Instagram, 2026-09-02) — ritorna 0 bottoni cliccati
    per fermare subito il ciclo interno di _scroll_feed_e_raccogli."""

    def __init__(self, iterazioni: list[list[dict]]):
        self._iterazioni = iterazioni
        self.mouse = self
        self._indice = 0

    def evaluate(self, script: str):
        if script == feed_social._JS_ESPANDI_VEDI_ALTRO["instagram"]:
            return 0
        if script == feed_social._JS_ESPANDI_CAROSELLI_INSTAGRAM:
            return 0  # nessun bottone "Avanti" da cliccare in questo test
        if self._indice >= len(self._iterazioni):
            return []
        risultato = self._iterazioni[self._indice]
        self._indice += 1
        return risultato

    def wheel(self, x, y):
        pass

    def wait_for_timeout(self, ms):
        pass


def test_scroll_feed_instagram_legge_data_pubblicazione_dal_time_element():
    """2026-09-02, richiesto dall'utente (caso Valfenera f39bb10a29e1): il
    post grezzo raccolto dallo script JS espone dataPubblicazione (dal
    datetime dell'elemento <time>, collaudato dal vivo) — verifica che
    _scroll_feed_e_raccogli lo converta in PostFeed.data_pubblicazione."""
    grezzi = [{
        "href": "/prolocovalfenera",
        "permalink": "/p/DciNQZaFZUO/",
        "testo": "Stasera vi aspettiamo dalle 19.30!",
        "immagineUrls": ["https://cdninstagram.com/1.jpg"],
        "dataPubblicazione": "2026-08-27T07:03:46.000Z",
    }]
    pagina = _PaginaScrollInstagramFinta([grezzi, []])

    risultato = feed_social._scroll_feed_e_raccogli(
        pagina, feed_social._JS_RACCOGLI_POST_INSTAGRAM, "instagram", ultimo_visto=None, max_scroll=2
    )

    assert len(risultato) == 1
    from datetime import date
    assert risultato[0].data_pubblicazione == date(2026, 8, 27)


# --- riprocessa_eventi_instagram (2026-09-03, richiesto dall'utente dopo
# i casi Valfenera/carosello e Vaglio Serra): un post già letto non viene
# mai riletto dal giro normale, serve una utility esplicita di correzione. ---

class _PaginaCorreggiFinta:
    """Simula pagina.goto/evaluate/wait_for_timeout/close per un singolo
    permalink Instagram — nessun browser reale (15.1 regola 8)."""

    def __init__(self, grezzo: dict, ha_bottone_avanti: bool = False):
        self._grezzo = grezzo
        self._ha_bottone_avanti = ha_bottone_avanti
        self.chiusa = False
        self.url_visitato = None

    def goto(self, url, timeout=None):
        self.url_visitato = url

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        if "Avanti" in script and "return 1" in script:
            if self._ha_bottone_avanti:
                self._ha_bottone_avanti = False  # solo un giro
                return 1
            return 0
        return self._grezzo

    def close(self):
        self.chiusa = True


def _contesto_correggi_finto(pagina):
    class _Browser:
        def new_page(self_inner):
            return pagina

    return {"browser": _Browser()}


def test_riprocessa_eventi_instagram_sostituisce_evento_sbagliato(tmp_path, monkeypatch):
    """Caso reale Valfenera: un evento con data sbagliata (bug ormai
    corretto nel codice) viene sostituito da uno corretto, ri-leggendo il
    post dal vivo — solo qui, non nel giro normale (change detection)."""
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'instagram', 'prolocotest', 'Calosso', 'seguito')"
    )
    conn.commit()

    # Evento vecchio, sbagliato, da sostituire.
    provider_vecchio = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor_vecchio = ExtractorClient(Config(), conn, provider=provider_vecchio)
    post_vecchio = feed_social.PostFeed(
        piattaforma="instagram", handle_autore="prolocotest", post_id="abc123",
        url="https://www.instagram.com/p/abc123/",
        testo="Sagra del Tartufo sabato 12 settembre in Piazza Roma a Calosso, degustazioni e musica.",
    )
    feed_social.elabora_post(post_vecchio, conn, Config(), extractor_vecchio)
    vecchio = conn.execute("SELECT event_id FROM events WHERE archiviato='no'").fetchone()
    assert vecchio is not None

    # Ri-processo: nuova estrazione con titolo diverso (simula il fix che
    # ora legge correttamente il contenuto).
    grezzo = {
        "testo": "Sagra della Nocciola domenica 20 settembre in Piazza Roma a Calosso.",
        "immagineUrls": [],
        "dataPubblicazione": "2026-09-01T10:00:00.000Z",
    }
    pagina = _PaginaCorreggiFinta(grezzo)
    monkeypatch.setattr(feed_social, "_apri_sessione_browser", lambda piattaforma, sessione_dir: _contesto_correggi_finto(pagina))
    monkeypatch.setattr(feed_social, "_chiudi_sessione_browser", lambda contesto: None)
    monkeypatch.setattr(feed_social, "verifica_identita_instagram", lambda contesto, config: None)

    # Titolo E data diversi dal vecchio evento (non "Sagra del Tartufo",
    # 12/09): la stessa fixture standard produrrebbe la stessa dedup_key
    # (comune+data), facendo aggiornare la riga esistente invece di
    # crearne una nuova — il caso reale (Valfenera) aveva titolo/data
    # diversi tra la vecchia estrazione sbagliata e quella corretta.
    risposta_nuova = (
        '{"eventi": [{"titolo": "Sagra della Nocciola", "descrizione": "Degustazioni", "tipologia": "sagra", '
        '"data_inizio": "2026-09-20", "data_fine": "2026-09-20", "ora_inizio": "21:00", "ora_fine": null, '
        '"ricorrenza": {"e_ricorrente": false}, "luogo_testuale": "Piazza Roma", "comune_testuale": "Calosso", '
        '"indirizzo": null, "prezzo": null, "organizzatore": null, "anno_esplicito": true, '
        '"confidenza": 90, "campi_incerti": [], "note_estrazione": null}], '
        '"non_e_un_evento": false, "motivo": null}'
    )
    provider_nuovo = _ProviderFinto([risposta_nuova])
    extractor_nuovo = ExtractorClient(Config(), conn, provider=provider_nuovo)

    risultati = feed_social.riprocessa_eventi_instagram([vecchio["event_id"]], conn, Config(), extractor_nuovo)

    assert len(risultati) == 1
    assert risultati[0]["esito"] == "pubblicato"
    assert pagina.url_visitato == "https://www.instagram.com/p/abc123/"

    vecchia_riga = conn.execute("SELECT archiviato FROM events WHERE event_id=?", (vecchio["event_id"],)).fetchone()
    assert vecchia_riga["archiviato"] == "si"

    nuovi = conn.execute("SELECT titolo FROM events WHERE archiviato='no'").fetchall()
    assert len(nuovi) == 1


def test_riprocessa_eventi_instagram_rifiuta_facebook():
    """Per Facebook l'URL salvato non è un permalink riapribile (link
    della pagina autore con parametri di tracking) — investigato a fondo
    (2026-09-03): anche il timestamp è offuscato deliberatamente. Deve
    fallire con un messaggio chiaro, non tentare di aprire un URL sbagliato."""
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato, url) "
        "VALUES ('ev1', 'Evento', '2026-09-12', '2026-09-12', 'Calosso', 'no', 'https://www.facebook.com/pagina?__cft__=x')"
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) "
        "VALUES ('ev1', 'feed-facebook-pagina', 'https://www.facebook.com/pagina?__cft__=x', '2026-08-27')"
    )
    conn.commit()

    risultati = feed_social.riprocessa_eventi_instagram(["ev1"], conn, Config(), extractor=None)

    assert len(risultati) == 1
    assert risultati[0]["esito"] == "errore"
    assert "Facebook" in risultati[0]["dettaglio"] or "facebook" in risultati[0]["dettaglio"]

    riga = conn.execute("SELECT archiviato FROM events WHERE event_id='ev1'").fetchone()
    assert riga["archiviato"] == "no"  # non toccato


def test_riprocessa_eventi_instagram_event_id_inesistente():
    conn = _conn_con_comune()
    risultati = feed_social.riprocessa_eventi_instagram(["non-esiste"], conn, Config(), extractor=None)
    assert len(risultati) == 1
    assert risultati[0]["esito"] == "errore"
    assert "non trovato" in risultati[0]["dettaglio"]


def test_riprocessa_eventi_instagram_isola_errori_tra_piu_id(monkeypatch):
    """15.1 regola 4: un event_id sbagliato non deve bloccare gli altri."""
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'instagram', 'prolocotest', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor = ExtractorClient(Config(), conn, provider=provider)
    post = feed_social.PostFeed(
        piattaforma="instagram", handle_autore="prolocotest", post_id="abc123",
        url="https://www.instagram.com/p/abc123/",
        testo="Sagra del Tartufo sabato 12 settembre in Piazza Roma a Calosso, degustazioni e musica.",
    )
    feed_social.elabora_post(post, conn, Config(), extractor)
    valido = conn.execute("SELECT event_id FROM events WHERE archiviato='no'").fetchone()

    grezzo = {"testo": "Sagra della Nocciola domenica 20 settembre in Piazza Roma a Calosso.", "immagineUrls": [], "dataPubblicazione": None}
    pagina = _PaginaCorreggiFinta(grezzo)
    monkeypatch.setattr(feed_social, "_apri_sessione_browser", lambda piattaforma, sessione_dir: _contesto_correggi_finto(pagina))
    monkeypatch.setattr(feed_social, "_chiudi_sessione_browser", lambda contesto: None)
    monkeypatch.setattr(feed_social, "verifica_identita_instagram", lambda contesto, config: None)

    provider2 = _ProviderFinto([_risposta_json(comune="Calosso", confidenza=90)])
    extractor2 = ExtractorClient(Config(), conn, provider=provider2)

    risultati = feed_social.riprocessa_eventi_instagram(
        ["non-esiste", valido["event_id"]], conn, Config(), extractor2
    )

    assert len(risultati) == 2
    assert risultati[0]["esito"] == "errore"
    assert risultati[1]["esito"] == "pubblicato"


# --- Timestamp Facebook via hover + tooltip (2026-09-03, richiesto
# dall'utente): il timestamp relativo ("N min/h/g") ha i caratteri
# deliberatamente mescolati nel DOM (verificato confrontando innerText e
# textContent con l'HTML grezzo reale — anti-scraping intenzionale). La
# data assoluta è leggibile solo tramite il tooltip DOM che compare al
# passaggio del mouse sopra il link, collaudato dal vivo 3/3 volte. ---

def test_data_da_tooltip_facebook_formato_reale():
    """Formato reale osservato dal vivo 2026-09-03."""
    from datetime import date
    assert feed_social._data_da_tooltip_facebook(
        "Giovedì 3 settembre 2026 alle ore 15:52"
    ) == date(2026, 9, 3)


def test_data_da_tooltip_facebook_altro_mese():
    from datetime import date
    assert feed_social._data_da_tooltip_facebook(
        "Lunedì 31 agosto 2026 alle ore 22:34"
    ) == date(2026, 8, 31)


def test_data_da_tooltip_facebook_formato_inatteso_ritorna_none():
    """Isolamento totale (15.1 regola 4): mai sollevare, ricade sul
    default date.today() in client.py."""
    assert feed_social._data_da_tooltip_facebook("qualcosa di diverso") is None
    assert feed_social._data_da_tooltip_facebook("") is None
    assert feed_social._data_da_tooltip_facebook(None) is None


class _LocatorFinto:
    def __init__(self, box, tooltip_testo):
        self._box = box
        self._tooltip_testo = tooltip_testo

    def bounding_box(self, timeout=None):
        return self._box


class _PaginaHoverFinta:
    """Simula pagina.locator/.mouse.move/.evaluate per testare l'hover
    sul link timestamp senza un browser reale (15.1 regola 8)."""

    def __init__(self, box, tooltip_testo):
        self._box = box
        self._tooltip_testo = tooltip_testo
        self.mosse = []

    def locator(self, selettore):
        return _LocatorFinto(self._box, self._tooltip_testo)

    class _Mouse:
        def __init__(self, pagina):
            self._pagina = pagina

        def move(self, x, y):
            self._pagina.mosse.append((x, y))

    @property
    def mouse(self):
        return _PaginaHoverFinta._Mouse(self)

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        return [self._tooltip_testo] if self._tooltip_testo else []


def test_leggi_data_pubblicazione_hover_facebook_successo():
    from datetime import date
    pagina = _PaginaHoverFinta(
        box={"x": 100, "y": 50, "width": 30, "height": 17},
        tooltip_testo="Giovedì 3 settembre 2026 alle ore 15:52",
    )
    risultato = feed_social._leggi_data_pubblicazione_hover_facebook(pagina, idx_timestamp=1)
    assert risultato == date(2026, 9, 3)
    assert len(pagina.mosse) == 2  # hover sul link + spostamento finale


def test_leggi_data_pubblicazione_hover_facebook_idx_assente():
    pagina = _PaginaHoverFinta(box=None, tooltip_testo=None)
    assert feed_social._leggi_data_pubblicazione_hover_facebook(pagina, idx_timestamp=None) is None


def test_leggi_data_pubblicazione_hover_facebook_nessun_bounding_box():
    """Isolamento totale: elemento non trovato non deve sollevare."""
    pagina = _PaginaHoverFinta(box=None, tooltip_testo=None)
    assert feed_social._leggi_data_pubblicazione_hover_facebook(pagina, idx_timestamp=1) is None


def test_leggi_data_pubblicazione_hover_facebook_nessun_tooltip():
    """Isolamento totale: hover senza tooltip (es. timing) non deve sollevare."""
    pagina = _PaginaHoverFinta(
        box={"x": 100, "y": 50, "width": 30, "height": 17}, tooltip_testo=None
    )
    assert feed_social._leggi_data_pubblicazione_hover_facebook(pagina, idx_timestamp=1) is None


def test_leggi_data_pubblicazione_hover_facebook_eccezione_isolata():
    """Isolamento totale (15.1 regola 4): un errore imprevisto durante
    l'hover (es. pagina chiusa a metà) non deve bloccare l'elaborazione
    degli altri post."""
    class _PaginaCheEsplode:
        def locator(self, selettore):
            raise RuntimeError("simulato")

    assert feed_social._leggi_data_pubblicazione_hover_facebook(_PaginaCheEsplode(), idx_timestamp=1) is None
