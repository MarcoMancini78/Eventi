# 02 — Architettura

> Le decisioni di fondo che guidano questa architettura sono riassunte in
> [00-README.md §Sintesi](00-README.md#sintesi-perché-il-tentativo-precedente-è-fallito-e-cosa-cambia).
> Questo documento descrive **come sono organizzati i moduli oggi** e il
> flusso end-to-end reale, non le motivazioni originarie.

## 2.1 Flusso end-to-end

```
sources (SQLite)              webapp pubbliche
   │  censite da                  ▲
   │  import-fonti /              │ eventi_mappa.json
   │  populate-coda-follow        │ (docs/, GitHub Pages)
   ▼                              │
run.py run / run-publish          │
   │  (scheduling.py: priorità)   │
   ▼                              │
pipeline.esegui_fonte()           │
   │  dispatch per tier ──────────┼─── adapters/*.py (T0 puri)
   │                              │    feed_social.py / follow.py (social)
   ▼                              │
artifacts (grezzi)                │
   │  prefilter*.py               │
   ▼                              │
extractor/client.py (LLM/VLM)     │
   │  normalizer.py                │
   │  series.py / recurrence.py    │
   │  dedup.py                     │
   ▼                              │
events (SQLite) ───────────────── publisher.py ─── Google Sheets
                                        │
                                        └─── docs/eventi_mappa.json
```

## 2.2 Moduli (`eventi/src/`)

| Modulo | Ruolo |
|---|---|
| `config.py` | Carica `Config` da env/`.env` (credenziali Google, LLM, IMAP, Telegram, social) |
| `store.py` | Schema e connessione SQLite — la verità operativa; Sheets è solo vista |
| `perimetro.py` | Import/gestione del perimetro comuni (tabella `comuni`) |
| `prefilter.py` / `prefilter_immagini.py` | Filtro pre-LLM su testo/immagini, scarta artefatti non promettenti prima di spendere quota LLM |
| `fingerprint.py` | Fingerprinting batch dei siti comunali per famiglia CMS |
| `prober.py` | Discovery della vera pagina eventi/feed a partire dalla homepage già scaricata |
| `bonifica_social.py` | Bonifica/import fonti social da CSV grezzi verso `coda_follow` |
| `follow.py` | Automazione di follow semiautomatico Facebook/Instagram — unica automazione che *agisce*, login manuale, circuito di sicurezza |
| `sync_seguiti.py` | Lettura passiva della lista "seguiti" reale per riconciliare `coda_follow` |
| `feed_social.py` | Lettura cronologica passiva dei feed social già seguiti, attribuzione ed estrazione eventi |
| `adapters/` | Un adattatore per tier/canale — vedi [04-fonti-ingestione.md](04-fonti-ingestione.md) |
| `extractor/` (`client.py`, `schema.py`, `prompts/`) | Client LLM/VLM per estrazione strutturata da artefatti grezzi |
| `normalizer.py` | Normalizzazione campi estratti (date, comuni, ecc.) |
| `series.py` / `recurrence.py` | Gestione serie ricorrenti e generazione occorrenze (RRULE) |
| `dedup.py` | Deduplica eventi (`dedup_key`), archiviazione eventi conclusi |
| `scheduling.py` | Priorità dinamica della coda fonti |
| `pipeline.py` | Orchestratore per-fonte: dispatch al tier/adapter giusto, gestione quarantena, funzioni di ricorrezione mirata |
| `lockfile.py` | Lock file per evitare run sovrapposti |
| `stato_sistema.py` | Calcolo indicatori/semafori per il foglio Stato |
| `drive_backup.py` | Backup dello spreadsheet principale su Drive |
| `publisher.py` | Scrittura verso Google Sheets e verso `eventi_mappa.json` |
| `sheets_client.py` | Client gspread/OAuth verso Google Sheets |

## 2.3 Orchestrazione (`run.py`)

Elenco comandi reale (vedi anche [08-orchestrazione-operativita.md](08-orchestrazione-operativita.md)
per la logica di scheduling/budget):

| Comando | Cosa fa |
|---|---|
| `init` | Crea fogli Google e database SQLite |
| `doctor` | Diagnostica configurazione e stato |
| `import-fonti` | Import base di Comuni/ProLoco in `sources` |
| `fingerprint-comuni` | Fingerprinting batch dei siti comunali per famiglia CMS |
| `prober` | Discovery della vera pagina eventi/feed per le fonti già importate |
| `promuovi-jsonld` | Verifica e promuove a `T0_jsonld` le fonti `T1_html` che espongono già `schema.org/Event` |
| `promuovi-pa-design-system` | Verifica e promuove a `T0_pa_design_system` le fonti `/Eventi` con markup `.card-wrapper` |
| `run` | Esegue la raccolta sulle fonti T0/T1 note |
| `run-publish` | Esegue il giro multi-fonte e poi pubblica su Google Sheets in un solo comando |
| `publish` | Elabora lo stato eventi (archiviazione) e pubblica su Google Sheets |
| `pull-fonti` | Rilegge da Sheets verso SQLite le modifiche manuali (categoria/comune/azioni quarantena) |
| `correggi-fonte-html` | Rilancia una o più fonti T1_html/aggregatore con l'adapter aggiornato |
| `correggi-post` | Ricorregge uno o più eventi social (Instagram): riapre il post e ri-estrae |
| `riprocessa-quarantena` | Ricorregge tutti gli eventi in quarantena, smistando da solo per tipo fonte |
| `populate-coda-follow` | Bonifica ed importa le fonti social nella coda di follow |
| `login` | Apre il browser per il login manuale una tantum (`--platform facebook|instagram`) |
| `sync-seguiti` | Legge la lista "seguiti" reale e aggiorna `coda_follow` (sola lettura) |
| `follow` | Esegue un lotto di follow social (`--platform`, `--n`, `--dry-run`) |
| `feed-social` | Lettura cronologica del feed, attribuzione ed estrazione eventi (sola lettura) |
| `backup-sheets` | Copia lo spreadsheet principale in una cartella Drive dedicata |
| `cleanup` | Rimuove backup di `eventi.db` e file scratch/debug più vecchi di N giorni in `data/` (elenco di default, `--esegui` per rimuoverli davvero) |
| `discover`, `reprocess` | Placeholder, non ancora implementati |

## 2.4 Interfacce di consultazione

- **Google Sheets**: pannello di controllo umano, editing manuale (vedi
  [03-modello-dati.md](03-modello-dati.md)).
- **Webapp mappa ed elenco**: statiche, pubblicate su GitHub Pages, leggono lo
  stesso `eventi_mappa.json` (vedi [16-webapp-mappa.md](16-webapp-mappa.md)).

## 2.5 Perché questa separazione

Nessun componente capisce *contemporaneamente* come navigare una fonte e cosa
significa il contenuto: gli adapter producono solo artefatti grezzi, un unico
estrattore LLM li trasforma in eventi strutturati. Aggiungere una fonte T0/T1
generica è aggiungere una riga a un foglio, non scrivere codice — solo le
famiglie di CMS più diffuse (`pa_design_system`, `wordpress`) giustificano un
adattatore dedicato, per l'economia di scala (una decina di famiglie coprono
migliaia di siti comunali). Dettagli in
[12-scala-e-copertura.md](12-scala-e-copertura.md).
