"""Schema di output dell'estrattore (06.2). Unico per testo e immagini."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Tipologia = Literal[
    "sagra", "gastronomia", "degustazione", "concerto", "teatro", "cinema",
    "mostra", "fiera", "sportivo", "bambini", "altro",
]


class Ricorrenza(BaseModel):
    e_ricorrente: bool = False
    frequenza: Literal["settimanale", "mensile", "annuale"] | None = None
    giorni_settimana: list[str] = Field(default_factory=list)
    ordinale: int | None = None
    mesi_inclusi: list[int] = Field(default_factory=list)
    fine_dichiarata: str | None = None
    testo_originale: str | None = None


class EventoEstratto(BaseModel):
    titolo: str
    descrizione: str | None = None
    tipologia: Tipologia
    data_inizio: str | None = None
    data_fine: str | None = None
    ora_inizio: str | None = None
    ora_fine: str | None = None
    ricorrenza: Ricorrenza = Field(default_factory=Ricorrenza)
    luogo_testuale: str | None = None
    comune_testuale: str | None = None
    indirizzo: str | None = None
    prezzo: str | None = None
    organizzatore: str | None = None
    # 2026-09-02, richiesto dall'utente: un post spesso rimanda a un sito
    # esterno per il programma completo (es. un repost di un'associazione
    # organizzatrice con "SCOPRI IL PROGRAMMA COMPLETO: www.sito.it" nel
    # testo) — 'url' nel resto della pipeline resta sempre il link del
    # POST sorgente (Facebook/Instagram), mai sovrascritto da questo
    # campo. Solo se un URL esplicito compare nel testo, mai indovinato.
    url_approfondimento: str | None = None
    anno_esplicito: bool = True
    confidenza: int = Field(ge=0, le=100)
    campi_incerti: list[str] = Field(default_factory=list)
    note_estrazione: str | None = None


class RispostaEstrazione(BaseModel):
    eventi: list[EventoEstratto] = Field(default_factory=list)
    non_e_un_evento: bool = False
    motivo: str | None = None
