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

    def estrai(self, prompt_sistema, prompt_utente, immagini=None):
        self.chiamate_con_immagini.append(immagini)
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
