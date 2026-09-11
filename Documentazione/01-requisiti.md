# 01 — Requisiti

## 1.1 Obiettivo

Costruire e mantenere aggiornato un elenco di eventi locali (feste, sagre,
serate gastronomiche, degustazioni, concerti, teatro, cinema fuori
programmazione ordinaria) in un raggio definito da casa, raccogliendo dati da
siti istituzionali, portali aggregatori e canali social — per uso personale,
non ridistribuito su larga scala.

## 1.2 Scope

Dentro:
- Comuni e Pro Loco entro 100 km da Calosso (AT), stratificati in fasce A/B/C.
- Teatri, cinema (solo proiezioni-evento, non programmazione ordinaria di
  sala), locali, compagnie teatrali, portali aggregatori regionali.
- Raccolta da siti (T0/T1), social (Facebook/Instagram via account dedicato),
  email/newsletter, Telegram.

Fuori scope (esclusioni esplicite, vedi
[00-README.md §Parametri fissati](00-README.md#parametri-fissati)):
- Eventi sportivi, per bambini, programmazione cinematografica ordinaria.
- Ridistribuzione pubblica promossa attivamente (le webapp pubblicate su
  GitHub Pages sono accessibili ma non pubblicizzate — vedi
  [11-rischi-decisioni.md §11.2](11-rischi-decisioni.md#112-aspetti-legali-e-di-conformità)).

## 1.3 Requisiti funzionali (sintesi)

- RF-1: raccogliere eventi da fonti eterogenee senza scrivere un parser per
  sito (vedi [00-README.md §Sintesi](00-README.md#sintesi-perché-il-tentativo-precedente-è-fallito-e-cosa-cambia)).
- RF-2: distinguere eventi con confidenza sufficiente (pubblicati) da
  candidati incerti (quarantena), mai perdere silenziosamente un candidato.
- RF-3: deduplicare lo stesso evento riportato da più fonti.
- RF-4: gestire eventi ricorrenti come regole, non come righe duplicate.
- RF-5: mostrare l'elenco in almeno due forme di consultazione (foglio
  Sheets per l'editing, webapp per la consultazione rapida — mappa ed
  elenco tabellare, vedi [16-webapp-mappa.md](16-webapp-mappa.md)).
- RF-6: mai disattivare automaticamente una fonte silenziosa (vedi
  [04-fonti-ingestione.md §4.7](04-fonti-ingestione.md#47-fonti-dormienti--fonti-inutili)).
- RF-10: le modifiche manuali dell'utente (stato, note, blocco) non vengono
  mai sovrascritte da un run successivo.

## 1.4 Requisiti non funzionali

- **Budget zero** (o quasi): nessun servizio a pagamento obbligatorio, solo
  quote gratuite. Vedi [09-stack-costi.md](09-stack-costi.md).
- **Esecuzione su PC personale**, non sempre acceso: il sistema deve
  recuperare le esecuzioni saltate senza duplicare lavoro (vedi
  [08-orchestrazione-operativita.md §8.7](08-orchestrazione-operativita.md#87-scheduling-sul-pc)).
- **Nessuna GPU locale**: l'estrazione usa un provider LLM cloud (vedi
  [11-rischi-decisioni.md](11-rischi-decisioni.md), decisione D11).
- **Basso rischio di blocco sui social**: mai un comportamento distinguibile
  da un utente umano (vedi [14-account-social.md](14-account-social.md) e
  [05-social-locandine.md §5.7](05-social-locandine.md#57-piano-di-degradazione)).
- **Isolamento totale degli errori**: il fallimento di una fonte non deve mai
  fermare l'intero run (vedi [15-guida-implementazione.md](15-guida-implementazione.md)).

## 1.5 KPI da misurare (non opzionali)

Non un traguardo teorico: numeri concreti da poter verificare guardando il
foglio `Stato` o `Log` ([08-orchestrazione-operativita.md §8.9](08-orchestrazione-operativita.md#89-monitoraggio-senza-notifiche)).

| KPI | Obiettivo | Come si misura |
|---|---|---|
| Copertura fascia A | ≥ 60% dei comuni con almeno una fonte attiva | `sources`/`fingerprint_comuni` filtrati per fascia |
| Eventi nuovi per settimana | > 0, stabilmente | Foglio `Log`, colonna `eventi_nuovi` |
| Tasso di quarantena | Minoranza degli eventi totali (indicativo, non un tetto rigido) | `Quarantena` / (`Eventi` + `Quarantena`) |
| Durata run principale | Sotto il budget configurato (`budget_run_minuti`) | Foglio `Log`, colonna `durata_min` |
| Fonti in stato `rotta` | Sotto controllo, non in crescita settimana su settimana | Foglio `Stato` |

**L'indicatore critico resta "eventi nuovi negli ultimi 7 giorni = 0"**: su
questo perimetro è statisticamente impossibile in condizioni normali, quindi
segnala sempre un guasto a monte (vedi
[08-orchestrazione-operativita.md §8.9](08-orchestrazione-operativita.md#89-monitoraggio-senza-notifiche)).

## 1.6 Assunzioni

- I siti istituzionali comunali cambiano poco nel tempo una volta
  classificati per famiglia CMS (base della strategia di
  [12-scala-e-copertura.md](12-scala-e-copertura.md)).
- Gran parte degli eventi minori (sagre, feste locali) vive solo sui social,
  spesso come locandina immagine, non come testo strutturato — assunzione
  alla base di [05-social-locandine.md](05-social-locandine.md).
- Un account social dedicato che segue tutte le fonti rilevanti riduce il
  lavoro di raccolta di un ordine di grandezza rispetto a visitare ogni
  fonte singolarmente (vedi [05-social-locandine.md §5.2](05-social-locandine.md#52-la-leva-inversione-del-feed)).
- Il perimetro geografico (100 km da Calosso) è stabile: non è previsto un
  secondo punto di riferimento o un perimetro dinamico.
