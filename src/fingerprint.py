"""M8 — Fingerprinting per famiglia di piattaforma (12.5).

A poche decine di fonti scrivere un parser dedicato non conviene (04.3);
a centinaia di siti comunali sì, perché non sono siti diversi: sono una
decina di piattaforme ripetute molte volte. Questo modulo classifica una
homepage per firma (meta generator, percorsi caratteristici, CSS
ricorrenti), e la classificazione batch su tutti i comuni del perimetro
(`fingerprint_batch`) — la scrittura di un adattatore per famiglia resta
il passo successivo di M8, da fare quando la classificazione avrà
rivelato quali famiglie meritano un adattatore dedicato.

Firme verificate empiricamente (2026-08-25, comuni reali del perimetro):
- comune.cuneo.it: 'wp-content' + commento HTML "Yoast SEO" -> wordpress
- comune.asti.it, comune.alessandria.it: <meta name="Generator"
  content="Drupal 9..."> -> drupal
- comune.alba.cn.it: 'bootstrap-italia' + 'agid.css' -> pa_design_system
  (il template istituzionale AGID diffuso dopo le linee guida di design
  per la PA, citato in 12.5 come "modelli ricorrenti")
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

_TIMEOUT_SECONDI = 15
# Un semplice httpx.get senza User-Agent da browser riceve spesso 403 da
# siti comunali reali (verificato empiricamente su comune.cuneo.it: 403 con
# lo user-agent di default, 200 con questo) — coerente con 15-guida punto
# M8.4: "il dato attuale (HTTPStatusError quasi ovunque) non è credibile
# ed è probabilmente un blocco".
_USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_PATTERN_URL_COMUNE = re.compile(r"comune\.[a-z-]+\.[a-z]{2}\.it", re.IGNORECASE)


@dataclass
class Fingerprint:
    piattaforma: str  # 'wordpress' | 'drupal' | 'pa_design_system' | 'sconosciuta'
    indizi: list[str]  # segnali trovati, per debug/verifica manuale


_FIRME = [
    # (piattaforma, funzione che ritorna l'indizio trovato o None)
    ("wordpress", lambda html: "wp-content nel markup" if "wp-content" in html else None),
    (
        "drupal",
        lambda html: (
            "meta generator Drupal"
            if re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']Drupal', html, re.I)
            else None
        ),
    ),
    (
        "pa_design_system",
        lambda html: (
            "bootstrap-italia + agid.css"
            if "bootstrap-italia" in html and "agid" in html.lower()
            else None
        ),
    ),
]


def classifica_html(html: str) -> Fingerprint:
    """Funzione pura (nessuna rete): classifica un HTML già scaricato.

    L'ordine delle firme in _FIRME è la priorità di match: la prima che
    trova un indizio vince (un sito potrebbe teoricamente avere più
    indizi residui, es. plugin WordPress che include Bootstrap)."""
    for piattaforma, rileva in _FIRME:
        indizio = rileva(html)
        if indizio:
            return Fingerprint(piattaforma=piattaforma, indizi=[indizio])
    return Fingerprint(piattaforma="sconosciuta", indizi=[])


def url_prevedibile_comune(nome_comune: str, provincia: str) -> str:
    """Pattern noto (15-guida M8.1): comune.NOME.PROV.it. Solo un tentativo
    plausibile, non una garanzia — molti comuni usano domini diversi
    (verificato: comune.cuneo.it segue il pattern, ma non è l'unico
    formato esistente in Italia). Il chiamante deve verificare con una
    richiesta HTTP reale, non fidarsi del pattern da solo."""
    nome_slug = re.sub(r"[^a-z]+", "", nome_comune.lower().replace(" ", ""))
    return f"https://www.comune.{nome_slug}.{provincia.lower()}.it/"


def fingerprint_sito(url: str) -> Fingerprint:
    """Scarica la homepage con uno User-Agent da browser (necessario:
    verificato che molti siti comunali rispondono 403 senza) e la
    classifica. Nessun try/except qui: l'isolamento per-fonte è
    responsabilità del chiamante (15.1 regola 4), come negli adapter."""
    with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
        risposta = client.get(url, headers={"User-Agent": _USER_AGENT_BROWSER})
        risposta.raise_for_status()
    return classifica_html(risposta.text)


@dataclass
class RisultatoFingerprintComune:
    istat: str
    comune: str
    url: str
    piattaforma: str | None
    indizi: list[str]
    http_status: int | None
    errore: str | None


def fingerprint_batch(comuni: list[dict], pausa_secondi: float = 0.0) -> list[RisultatoFingerprintComune]:
    """Fingerprinting di più comuni in sequenza (12.5: "operazione batch da
    fare una volta"). Isolamento totale per comune (15.1 regola 4): un
    sito irraggiungibile o lento non deve fermare l'intero censimento.

    `comuni` è una lista di dict con almeno 'istat', 'comune', 'url'.
    `pausa_secondi` (default 0, nessuna pausa) è per gentilezza verso i
    siti target su un batch di centinaia di richieste — nessun requisito
    documentale lo impone, ma è buona pratica non martellare 683 domini
    diversi senza alcuna pausa tra una richiesta e l'altra."""
    import time

    risultati: list[RisultatoFingerprintComune] = []
    for riga in comuni:
        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDI, follow_redirects=True) as client:
                risposta = client.get(riga["url"], headers={"User-Agent": _USER_AGENT_BROWSER})
                status = risposta.status_code
                risposta.raise_for_status()
            fp = classifica_html(risposta.text)
            risultati.append(
                RisultatoFingerprintComune(
                    istat=riga["istat"], comune=riga["comune"], url=riga["url"],
                    piattaforma=fp.piattaforma, indizi=fp.indizi, http_status=status, errore=None,
                )
            )
        except Exception as exc:
            risultati.append(
                RisultatoFingerprintComune(
                    istat=riga["istat"], comune=riga["comune"], url=riga["url"],
                    piattaforma=None, indizi=[],
                    http_status=getattr(getattr(exc, "response", None), "status_code", None),
                    errore=str(exc),
                )
            )
        if pausa_secondi:
            time.sleep(pausa_secondi)
    return risultati
