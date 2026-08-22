"""Contratto comune degli adattatori (04.3, M2.1).

Ogni adattatore produce solo artefatti grezzi: testo, immagini, metadati.
Non decide nulla sul dominio (00-README §1): l'estrazione e la
normalizzazione restano fuori.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Artefatto:
    source_id: str
    url: str
    kind: str  # 'ical' | 'rss' | 'jsonld' | 'html' | 'social' | 'email'
    text: str | None = None
    context_date: str | None = None  # data di pubblicazione, se disponibile (04.3 rss)
    image_paths: list[str] = field(default_factory=list)
    raw_hash: str | None = None
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Campi già strutturati quando l'adattatore è T0 puro (ical/jsonld): se
    # presenti, l'estrattore LLM viene saltato del tutto (04.3).
    titolo: str | None = None
    data_inizio: str | None = None
    data_fine: str | None = None
    ora_inizio: str | None = None
    luogo_testuale: str | None = None
    descrizione: str | None = None


class Adapter:
    """Interfaccia: fetch(fonte) -> list[Artefatto]."""

    def fetch(self, fonte: dict) -> list[Artefatto]:
        raise NotImplementedError
