"""Adattatore email via IMAP (M7, 04.3): newsletter come fonte di ingestione.

L'email è una fonte come le altre (04.3 "email... vedi [05]"), non un canale
di notifica in uscita: si legge una casella dedicata a cui ci si è iscritti
manualmente alle newsletter dei soggetti. Ogni email diventa un artefatto
grezzo (testo + eventuali immagini allegate), coerente col ramo T1 della
pipeline: nessun campo strutturato precompilato qui, passa dall'estrattore.

`fonte["endpoint"]` è il mittente atteso (case-insensitive, sottostringa
dell'header From) per isolare la newsletter di un soggetto specifico dalle
altre email nella stessa casella — la casella e le credenziali sono uniche
e vengono da `Config`, non dalla singola fonte.
"""
from __future__ import annotations

import email
import hashlib
import imaplib
from email.header import decode_header
from email.message import Message
from pathlib import Path

from .base import Adapter, Artefatto

_TIMEOUT_SECONDI = 15
_CARTELLA_IMMAGINI = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "images"


def _decodifica_header(valore: str | None) -> str:
    if not valore:
        return ""
    parti = decode_header(valore)
    pezzi = []
    for testo, encoding in parti:
        if isinstance(testo, bytes):
            pezzi.append(testo.decode(encoding or "utf-8", errors="replace"))
        else:
            pezzi.append(testo)
    return "".join(pezzi)


def _testo_corpo(msg: Message) -> str:
    """Preferisce text/plain; se assente, usa text/html grezzo (l'estrattore
    LLM tollera markup residuo, coerente con l'html.py esistente che passa
    testo pulito ma non richiede purezza assoluta)."""
    if msg.is_multipart():
        corpo_html = ""
        for parte in msg.walk():
            content_type = parte.get_content_type()
            disposizione = str(parte.get("Content-Disposition") or "")
            if "attachment" in disposizione:
                continue
            if content_type == "text/plain":
                payload = parte.get_payload(decode=True)
                if payload:
                    return payload.decode(parte.get_content_charset() or "utf-8", errors="replace")
            elif content_type == "text/html" and not corpo_html:
                payload = parte.get_payload(decode=True)
                if payload:
                    corpo_html = payload.decode(parte.get_content_charset() or "utf-8", errors="replace")
        return corpo_html
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return str(msg.get_payload() or "")


def _salva_allegati_immagine(msg: Message, source_id: str, message_id: str) -> list[str]:
    """Estrazione da immagini allegate (10-roadmap.md: 'già usa il VLM') —
    salva solo su disco qui, l'interpretazione visiva è compito
    dell'estrattore multimodale a valle, non di questo adattatore (04.3:
    'non decide nulla sul dominio')."""
    percorsi: list[str] = []
    if not msg.is_multipart():
        return percorsi

    cartella = _CARTELLA_IMMAGINI / source_id
    for indice, parte in enumerate(msg.walk()):
        content_type = parte.get_content_type()
        if not content_type.startswith("image/"):
            continue
        payload = parte.get_payload(decode=True)
        if not payload:
            continue
        estensione = content_type.split("/")[-1].split(";")[0] or "bin"
        nome_file = f"{message_id}_{indice}.{estensione}"
        cartella.mkdir(parents=True, exist_ok=True)
        percorso = cartella / nome_file
        percorso.write_bytes(payload)
        percorsi.append(str(percorso))
    return percorsi


def parse_email(msg: Message, source_id: str, fetch_url: str, message_id: str) -> Artefatto | None:
    """Funzione pura (nessuna connessione IMAP): trasforma un messaggio email
    già scaricato in un Artefatto grezzo. Ritorna None se non c'è testo utile."""
    oggetto = _decodifica_header(msg.get("Subject"))
    corpo = _testo_corpo(msg).strip()
    if not oggetto and not corpo:
        return None

    testo = f"{oggetto}\n{corpo}".strip()
    immagini = _salva_allegati_immagine(msg, source_id, message_id)

    return Artefatto(
        source_id=source_id,
        url=fetch_url,
        kind="email",
        text=testo,
        image_paths=immagini,
        raw_hash=hashlib.sha1(testo.encode("utf-8")).hexdigest(),
    )


class EmailImapAdapter(Adapter):
    """Legge le email non ancora processate dal mittente atteso (04.3), le
    trasforma in artefatti grezzi. Non elimina né marca le email come lette
    sul server: l'idempotenza è affidata al raw_hash + dedup a valle (M2),
    coerente con l'adattatore RSS che rilegge sempre l'intero feed."""

    def __init__(self, config) -> None:
        self._config = config

    def fetch(self, fonte: dict) -> list[Artefatto]:
        mittente_atteso = (fonte.get("endpoint") or "").strip().lower()
        source_id = fonte["source_id"]

        artefatti: list[Artefatto] = []
        connessione = imaplib.IMAP4_SSL(self._config.imap_host, timeout=_TIMEOUT_SECONDI)
        try:
            connessione.login(self._config.imap_user, self._config.imap_password)
            connessione.select("INBOX", readonly=True)

            _, dati = connessione.search(None, "ALL")
            id_messaggi = dati[0].split() if dati and dati[0] else []

            for id_messaggio in id_messaggi:
                _, dati_messaggio = connessione.fetch(id_messaggio, "(RFC822)")
                if not dati_messaggio or not dati_messaggio[0]:
                    continue
                grezzo = dati_messaggio[0][1]
                msg = email.message_from_bytes(grezzo)

                mittente = _decodifica_header(msg.get("From")).lower()
                if mittente_atteso and mittente_atteso not in mittente:
                    continue

                artefatto = parse_email(
                    msg, source_id, self._config.imap_user, id_messaggio.decode("ascii", errors="replace")
                )
                if artefatto:
                    artefatti.append(artefatto)
        finally:
            try:
                connessione.logout()
            except Exception:
                pass

        return artefatti
