"""Adattatore Telegram via API bot ufficiale (M7, 04.3): canali dei soggetti.

Il bot legge i messaggi pubblicati dai canali/gruppi Telegram gestiti da
terzi (Pro Loco, comuni) di cui è membro/amministratore — non manda alcun
messaggio all'utente (08: "niente notifiche push, la diagnostica vive nel
foglio"). `fonte["endpoint"]` è il chat_id (o @username) del canale da
isolare tra gli update ricevuti dal bot.
"""
from __future__ import annotations

import hashlib

import httpx

from .base import Adapter, Artefatto

_TIMEOUT_SECONDI = 15
_URL_BASE = "https://api.telegram.org/bot{token}/{metodo}"


def _testo_messaggio(messaggio: dict) -> str:
    return (messaggio.get("text") or messaggio.get("caption") or "").strip()


def _chat_id_messaggio(messaggio: dict) -> str:
    chat = messaggio.get("chat") or {}
    return str(chat.get("username") or chat.get("id") or "")


def parse_updates(updates: list[dict], source_id: str, canale_atteso: str) -> list[Artefatto]:
    """Funzione pura (nessuna chiamata di rete): filtra gli update Telegram
    per canale e li trasforma in artefatti grezzi. `canale_atteso` è
    confrontato senza il prefisso '@', case-insensitive."""
    atteso = canale_atteso.lstrip("@").strip().lower()
    artefatti: list[Artefatto] = []

    for update in updates:
        messaggio = update.get("channel_post") or update.get("message")
        if not messaggio:
            continue

        chat_id = _chat_id_messaggio(messaggio).lstrip("@").lower()
        if atteso and atteso != chat_id:
            continue

        testo = _testo_messaggio(messaggio)
        if not testo:
            continue

        message_id = messaggio.get("message_id", "")
        url = f"https://t.me/{chat_id}/{message_id}" if chat_id else ""
        artefatti.append(
            Artefatto(
                source_id=source_id,
                url=url,
                kind="telegram",
                text=testo,
                raw_hash=hashlib.sha1(testo.encode("utf-8")).hexdigest(),
            )
        )

    return artefatti


class TelegramAdapter(Adapter):
    """getUpdates in polling semplice (04.3: nessuna infrastruttura webhook
    per un progetto a scala personale). Il bot deve essere già stato
    aggiunto come membro/admin del canale del soggetto — passo manuale,
    fuori dal codice, come l'iscrizione alle newsletter (14.4 stesso
    principio: mai automazione dove basta un'azione umana una tantum)."""

    def __init__(self, config) -> None:
        self._config = config

    def fetch(self, fonte: dict) -> list[Artefatto]:
        canale_atteso = fonte.get("endpoint") or ""
        source_id = fonte["source_id"]

        url = _URL_BASE.format(token=self._config.telegram_bot_token, metodo="getUpdates")
        with httpx.Client(timeout=_TIMEOUT_SECONDI) as client:
            risposta = client.get(url)
            risposta.raise_for_status()
        corpo = risposta.json()
        if not corpo.get("ok"):
            return []

        return parse_updates(corpo.get("result", []), source_id, canale_atteso)
