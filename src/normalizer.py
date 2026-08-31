"""Normalizzazione deterministica: titolo, date, comune (07.1-07.3). Nessun LLM, nessun costo."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata

from .perimetro import risolvi_comune

_STOPWORD = {
    "la", "il", "lo", "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "e", "ed", "festa", "sagra", "edizione", "annuale",
}
_ORDINALE_EDIZIONE = re.compile(r"\b\d+[ªº°]|\bX{0,3}(IX|IV|V?I{0,3})\b", re.IGNORECASE)
_PUNTEGGIATURA_RIPETUTA = re.compile(r"([!?.]){2,}")
_SPAZI_MULTIPLI = re.compile(r"\s+")

_MINUSCOLE_INTERNE = {"di", "della", "dello", "delle", "dei", "degli", "e", "a", "in", "per", "del"}


def titolo_visualizzato(titolo_grezzo: str) -> str:
    """Rimuove emoji/decorazioni, applica Title Case italiano, taglia a 120 caratteri (07.1)."""
    if not titolo_grezzo:
        return ""

    senza_emoji = "".join(
        c for c in titolo_grezzo if unicodedata.category(c)[0] != "So"
    )
    compresso = _SPAZI_MULTIPLI.sub(" ", senza_emoji).strip()
    ripulito = _PUNTEGGIATURA_RIPETUTA.sub(r"\1", compresso)

    if ripulito.isupper():
        parole = ripulito.lower().split(" ")
        parole = [
            p if p in _MINUSCOLE_INTERNE and i > 0 else p.capitalize()
            for i, p in enumerate(parole)
        ]
        ripulito = " ".join(parole)

    if len(ripulito) > 120:
        troncato = ripulito[:120]
        ultimo_spazio = troncato.rfind(" ")
        ripulito = troncato[:ultimo_spazio] if ultimo_spazio > 0 else troncato

    return ripulito


def titolo_normalizzato(titolo_grezzo: str, comune: str | None = None) -> str:
    """Solo per il matching interno: minuscolo, senza accenti, stopword rimosse, token ordinati (07.1)."""
    if not titolo_grezzo:
        return ""

    testo = unicodedata.normalize("NFKD", titolo_grezzo.lower())
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    testo = _ORDINALE_EDIZIONE.sub("", testo)

    if comune:
        comune_norm = unicodedata.normalize("NFKD", comune.lower())
        comune_norm = "".join(c for c in comune_norm if not unicodedata.combining(c))
        testo = testo.replace(comune_norm, "")

    testo = re.sub(r"[^\w\s]", " ", testo)
    token = [t for t in testo.split() if t and t not in _STOPWORD]
    return " ".join(sorted(token))


def normalizza_orario(valore: str | None) -> str | None:
    """'21' -> '21:00'; '21.30' -> '21:30' (07.2)."""
    if not valore:
        return None
    valore = valore.strip().replace(".", ":")
    if ":" not in valore:
        valore = f"{valore}:00"
    ore, _, minuti = valore.partition(":")
    ore = ore.zfill(2)
    minuti = (minuti or "00").zfill(2)
    return f"{ore}:{minuti}"


def risolvi_comune_evento(comune_testuale: str | None, comune_fonte: str | None, conn: sqlite3.Connection):
    """Cascata 07.3, livelli 1-2-5: match esatto/alias, poi comune_riferimento della fonte.

    Ritorna (riga_comune | None, confidenza_penalita). I livelli 3/4/6/7
    (testo del luogo, dizionario dei luoghi, geocoding, quarantena) si
    aggiungono quando i moduli relativi esistono (M5+).
    """
    if comune_testuale:
        riga = risolvi_comune(comune_testuale, conn)
        if riga:
            return riga, 0

    if comune_fonte:
        riga = risolvi_comune(comune_fonte, conn)
        if riga:
            return riga, -10  # inferenza dal comune di riferimento della fonte (07.3.5)

    return None, 0


def dedup_key(titolo_norm: str, data_inizio: str, comune_norm: str) -> str:
    """sha1(slug(titolo)[:20] | data_inizio | comune) — identità dell'evento (03.3)."""
    slug = titolo_norm.replace(" ", "-")[:20]
    base = f"{slug}|{data_inizio}|{comune_norm}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def event_id(chiave: str) -> str:
    return chiave[:12]


_SOGLIA_OVERLAP_TITOLI = 0.8
_MIN_TOKEN_CONDIVISI = 3

# Parole troppo generiche perché un titolo composto da una sola di esse
# basti a identificare un evento specifico (bug trovato nel collaudo
# 2026-08-30: "Evento culturale" — placeholder frequente dell'LLM per
# estrazioni a bassa confidenza — matchava per errore qualunque altro
# titolo che contenesse la parola "evento"). Non sono le stesse di
# _STOPWORD: quelle sono articoli/preposizioni sempre rimossi dal
# confronto, queste sono sostantivi validi che però da soli non bastano.
_PAROLE_TROPPO_GENERICHE_PER_MATCH_SINGOLO = {
    "evento", "eventi", "iniziativa", "manifestazione", "appuntamento",
    "serata", "giornata", "incontro", "attivita",
}


def titoli_simili(titolo_norm_a: str, titolo_norm_b: str) -> bool:
    """Dedup livello 3 (07.6, 'fuzzy'): due titoli già normalizzati sono
    lo stesso evento se condividono abbastanza token, indipendentemente
    dall'ordine o da parole aggiunte/tolte tra un giro e l'altro.

    Trovato con 3 casi reali (2026-08-28, segnalati dall'utente):
    dedup_key tronca lo slug (token ordinati alfabeticamente) a 20
    caratteri — un titolo con anche una sola parola in più cambia
    l'ordinamento e produce uno slug completamente diverso, mancando la
    corrispondenza esatta pur essendo lo stesso evento ("Fiorinchiostro"
    vs "Fiorinchiostro - Mostra Mercato Florovivaismo di qualità").

    Coefficiente di overlap (intersezione / token del titolo più corto)
    invece di Jaccard: un titolo-frammento interamente contenuto in uno
    più lungo (caso reale sopra) ha overlap 1.0 ma Jaccard bassa (i token
    extra del titolo lungo gonfiano l'unione) — Jaccard avrebbe mancato
    esattamente il caso che questo controllo deve prendere.

    L'overlap puro da solo è però troppo permissivo su titoli brevi:
    'concerto piazza' vs 'concerto piazza rock comune' avrebbe overlap 1.0
    pur essendo probabilmente due eventi diversi (un concerto generico e
    uno specifico). Il vincolo `>= 3 token condivisi` filtra questo caso
    (anche 2 parole generiche condivise non bastano) senza esigere
    overlap più basso — ma renderebbe falso anche
    'fiorinchiostro' da solo: quando il titolo più corto ha un unico
    token (non un caso generico a 2+ parole come 'concerto piazza', ma un
    vero titolo-frammento monoparola), quel singolo token è l'intero
    contenuto informativo del titolo breve, non un termine ambiguo tra
    tanti — trattato come match se coincide."""
    token_a = set(titolo_norm_a.split())
    token_b = set(titolo_norm_b.split())
    if not token_a or not token_b:
        return False

    intersezione = token_a & token_b
    piu_corto = min(len(token_a), len(token_b))
    overlap = len(intersezione) / piu_corto

    if overlap < _SOGLIA_OVERLAP_TITOLI:
        return False
    if piu_corto == 1:
        (unica_parola,) = token_a if len(token_a) == 1 else token_b
        if unica_parola in _PAROLE_TROPPO_GENERICHE_PER_MATCH_SINGOLO:
            return False
        return len(intersezione) == 1  # il titolo breve è un'unica parola, e coincide
    return len(intersezione) >= _MIN_TOKEN_CONDIVISI


def _overlap_token(testo_a: str | None, testo_b: str | None) -> float:
    """Coefficiente di overlap grezzo (intersezione / token più corto) su
    testo libero non normalizzato con `titolo_normalizzato` — usato per
    descrizione, dove le stopword vanno mantenute (a differenza del
    titolo, qui non serve un matching esatto tollerante all'ordine, solo
    una stima di quanto le due frasi si somigliano)."""
    a = (testo_a or "").strip().lower()
    b = (testo_b or "").strip().lower()
    if not a or not b:
        return 0.0
    token_a, token_b = set(a.split()), set(b.split())
    if not token_a or not token_b:
        return 0.0
    return len(token_a & token_b) / min(len(token_a), len(token_b))


_SOGLIA_OVERLAP_DESCRIZIONE = 0.7


def eventi_duplicati(
    titolo_norm_a: str,
    titolo_norm_b: str,
    descrizione_a: str | None,
    descrizione_b: str | None,
    fonti_a: set[str],
    fonti_b: set[str],
) -> bool:
    """Dedup livello 3 esteso (07.6, richiesto dall'utente 2026-08-30):
    `titoli_simili` da sola manca duplicati reali dove il titolo aggiunge
    solo un dettaglio organizzativo breve — caso reale più frequente
    trovato nell'analisi: 'Gruppi di Cammino' vs 'Gruppi di Cammino
    promossi dall'A.S.L. CN1' a Envie (17 coppie, stesso comune/data,
    overlap titolo 1.0 ma solo 2 token nel titolo corto, sotto la soglia
    di `titoli_simili` che li esige >=3 per non confondere titoli brevi
    genuinamente diversi come 'Concerto in piazza' vs 'Concerto rock in
    piazza del comune').

    Criterio deciso dall'utente dopo un falso positivo trovato nel
    collaudo ('Evento culturale' vs 'Evento culturale al Parco Storico
    Bricherasio', stessa fonte comunale ma un pranzo e un evento serale
    diversi, descrizioni completamente diverse): la sola combinazione
    'stessa fonte + titolo contenuto nell'altro' NON basta più da sola —
    serve anche che titolo E descrizione siano simili insieme. Due
    descrizioni entrambe vuote (caso reale di Envie, dove né l'uno né
    l'altro "Gruppi di Cammino" ha descrizione) non sono un segnale
    contrario: nessuna delle due parti smentisce l'altra, quindi non
    bloccano il match quando fonte e titolo già lo confermano.

    Non sostituisce `titoli_simili` (chiamata per prima, più economica e
    già sufficiente da sola nei casi con titoli più lunghi): la estende
    per il caso di overlap titolo perfetto ma con pochi token.

    Un secondo caso reale ('Serata alla Vineria' vs 'Domani sera alla
    Vineria', descrizione IDENTICA in entrambi) non ha overlap titolo
    perfetto — 'serata' e 'sera' restano parole diverse dopo la
    normalizzazione. Una descrizione IDENTICA carattere per carattere
    (dopo solo strip/lower, non l'intera normalizzazione del titolo) è
    un segnale sufficiente da sola, indipendente dal titolo: due eventi
    diversi non hanno mai la stessa descrizione esatta per puro caso."""
    if titoli_simili(titolo_norm_a, titolo_norm_b):
        return True

    descr_a = (descrizione_a or "").strip().lower()
    descr_b = (descrizione_b or "").strip().lower()
    if descr_a and descr_a == descr_b:
        return True

    token_a = set(titolo_norm_a.split())
    token_b = set(titolo_norm_b.split())
    if not token_a or not token_b:
        return False
    overlap_titolo = len(token_a & token_b) / min(len(token_a), len(token_b))
    if overlap_titolo < 1.0:
        return False  # senza un titolo perfettamente contenuto, serve titoli_simili o descrizione identica

    if not (fonti_a & fonti_b):
        return False  # stessa fonte è un prerequisito, non basta da sola (vedi docstring)

    entrambe_vuote = not descr_a and not descr_b
    return entrambe_vuote or _overlap_token(descrizione_a, descrizione_b) >= _SOGLIA_OVERLAP_DESCRIZIONE
