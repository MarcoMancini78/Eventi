"""M7: adattatori email (IMAP) e Telegram su fixture, nessuna rete/IMAP reale (15.1 regola 8)."""
import email as email_stdlib
import sys
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.email_imap import parse_email
from src.adapters.telegram import parse_updates


def _email_semplice(oggetto: str, corpo: str, mittente: str = "newsletter@prolocoprova.it") -> email_stdlib.message.Message:
    msg = MIMEText(corpo, "plain", "utf-8")
    msg["Subject"] = oggetto
    msg["From"] = mittente
    return msg


def _email_con_immagine(oggetto: str, corpo: str) -> email_stdlib.message.Message:
    msg = MIMEMultipart()
    msg["Subject"] = oggetto
    msg["From"] = "newsletter@prolocoprova.it"
    msg.attach(MIMEText(corpo, "plain", "utf-8"))
    immagine = MIMEImage(b"contenuto-finto-jpeg", _subtype="jpeg")
    immagine.add_header("Content-Disposition", "attachment", filename="locandina.jpg")
    msg.attach(immagine)
    return msg


def test_parse_email_estrae_oggetto_e_corpo():
    msg = _email_semplice("Sagra del Tartufo", "Vi aspettiamo il 12 settembre in Piazza Roma.")
    artefatto = parse_email(msg, source_id="proloco-prova", fetch_url="mailbox", message_id="1")

    assert artefatto is not None
    assert artefatto.kind == "email"
    assert "Sagra del Tartufo" in artefatto.text
    assert "12 settembre" in artefatto.text
    assert artefatto.titolo is None  # T1-like: nessun campo strutturato precompilato (04.3)
    assert artefatto.image_paths == []


def test_parse_email_vuota_ritorna_none():
    msg = _email_semplice("", "")
    assert parse_email(msg, source_id="proloco-prova", fetch_url="mailbox", message_id="2") is None


def test_parse_email_salva_allegato_immagine(tmp_path, monkeypatch):
    import src.adapters.email_imap as modulo

    monkeypatch.setattr(modulo, "_CARTELLA_IMMAGINI", tmp_path)
    msg = _email_con_immagine("Locandina evento", "In allegato la locandina.")
    artefatto = parse_email(msg, source_id="proloco-prova", fetch_url="mailbox", message_id="3")

    assert artefatto is not None
    assert len(artefatto.image_paths) == 1
    percorso = Path(artefatto.image_paths[0])
    assert percorso.exists()
    assert percorso.read_bytes() == b"contenuto-finto-jpeg"


def test_parse_updates_filtra_per_canale_e_ignora_altri():
    updates = [
        {"channel_post": {"message_id": 10, "text": "Sagra del Tartufo il 12/09", "chat": {"username": "prolocoprova"}}},
        {"channel_post": {"message_id": 11, "text": "Post di un altro canale", "chat": {"username": "altro_canale"}}},
        {"message": {"message_id": 12, "text": "Messaggio privato", "chat": {"id": 555}}},
    ]
    artefatti = parse_updates(updates, source_id="proloco-prova", canale_atteso="@prolocoprova")

    assert len(artefatti) == 1
    assert artefatti[0].kind == "telegram"
    assert "Sagra del Tartufo" in artefatti[0].text
    assert artefatti[0].url == "https://t.me/prolocoprova/10"


def test_parse_updates_usa_caption_se_manca_text():
    updates = [{"channel_post": {"message_id": 20, "caption": "Locandina Sagra", "chat": {"username": "prolocoprova"}}}]
    artefatti = parse_updates(updates, source_id="proloco-prova", canale_atteso="prolocoprova")

    assert len(artefatti) == 1
    assert artefatti[0].text == "Locandina Sagra"


def test_parse_updates_ignora_messaggi_senza_testo():
    updates = [{"channel_post": {"message_id": 30, "chat": {"username": "prolocoprova"}}}]
    artefatti = parse_updates(updates, source_id="proloco-prova", canale_atteso="prolocoprova")
    assert artefatti == []
