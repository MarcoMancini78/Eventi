# 16 — Interfacce pubbliche: webapp mappa, elenco e perimetro

**Stato:** tutte e tre implementate, collaudate e pubblicate online.
**Mappa:** https://marcomancini78.github.io/Eventi/
**Elenco (tabellare):** https://marcomancini78.github.io/Eventi/elenco.html —
nata il 2026-09-10, condivide lo stesso file dati della mappa.
**Perimetro (elenco comuni):** https://marcomancini78.github.io/Eventi/perimetro.html —
nata il 2026-09-11, un comune per riga con tutti i link collegati.
**Uso quotidiano:** dopo `run.py publish`/`run.py run-publish` (che scrivono
anche `docs/eventi_mappa.json` e `docs/perimetro.json` in locale), i **dati**
si aggiornano online da soli (commit automatico schedulato). Una modifica al
**codice** delle pagine richiede invece un `git push` manuale dalla cartella
del progetto.
**Richiesta originale (2026-08-31):** una seconda interfaccia, oltre al workbook
Sheets, che mostri gli eventi su una mappa: filtro per data di osservazione, e sulla
mappa tutti i punti (comuni) con almeno un evento quel giorno. L'elenco
tabellare e la pagina perimetro sono nati in seguito, come viste alternative.

---

## 16.1 Cosa esiste già e cosa manca

> Le sezioni 16.1-16.4 descrivono l'analisi originale del 2026-08-31, quando
> esisteva ancora la divisione `Eventi`/`Eventi_estesi` (unificata il
> 2026-09-10, vedi [03-modello-dati.md](03-modello-dati.md#31-struttura-del-google-sheet)).
> Lasciate invariate come contesto storico della richiesta; per lo stato
> implementativo attuale vedi [16.5](#165-come-funziona-oggi-v1-riassunto) e
> [16.7](#167-webapp-elenco-tabellare).

Il sistema ha già tutto il necessario tranne il rendering:

| Dato richiesto | Fonte già esistente |
|---|---|
| Elenco eventi con data_inizio/data_fine, comune, titolo, ecc. | `events` in SQLite ([03.2](03-modello-dati.md#32-schema-sqlite-locale)), già pubblicato su `Eventi`/`Eventi_estesi`/`Archivio` |
| Coordinate del comune (lat/lon) | `Perimetro` / tabella `comuni` ([03.1.4](03-modello-dati.md#314-perimetro-io--il-foglio-più-importante)) |
| Distanza da casa | `km`, già calcolato per ogni comune |

Manca solo un **livello di presentazione**: nessuna riga di codice del progetto
oggi produce HTML o disegna una mappa. Non è un gap di dati, è una funzionalità
nuova, indipendente dalla pipeline di raccolta.

---

## 16.2 Decisioni prese

Tre scelte già fatte con l'utente, non riaperte in questa analisi:

### 16.2.1 Dati: snapshot statico, non un servizio sempre attivo
Ad ogni `run.py publish` viene generato **anche** un file dati (JSON) accanto
all'aggiornamento di Sheets, con lo stesso ritmo di aggiornamento di tutto il resto
del sistema. Il file HTML della webapp è statico e carica quel JSON: nessun server
da tenere acceso, nessuna dipendenza di rete oltre al caricamento iniziale della
pagina e delle tile mappa. Coerente con il vincolo di budget zero e con l'unico
computer coinvolto ([00 — Parametri fissati](00-README.md#parametri-fissati)).

Scartate: lettura diretta da Google Sheets (richiede il foglio pubblico o un proxy
con credenziali, più complessità e un problema di sicurezza) e un piccolo server
Flask locale (richiede tenere un processo attivo, non consultabile da un link Drive
puro).

**Aggiornamento post-collaudo (T8, 2026-08-31):** il piano di leggere entrambi i
file *direttamente da Drive* (fetch remoto o esecuzione della pagina dal link di
condivisione) si è rivelato non praticabile — Drive non esegue un `.html`
condiviso come pagina web e blocca il `fetch()` del JSON con CORS (dettagli in
16.5, T8). Non risolvibile lato client: nessuna impostazione di Google Cloud
Console o di condivisione del file abilita CORS su quell'endpoint.

**Aggiornamento finale (T10, 2026-08-31):** invece di restare sul solo
caricamento manuale locale, la pagina è stata pubblicata su **GitHub Pages**
(`docs/index.html` + `docs/eventi_mappa.json`, stesso dominio, nessun problema
di CORS per costruzione). Resta comunque "nessun server da mantenere" nel senso
stretto del vincolo originale (Pages è hosting statico gratuito, non un
servizio da tenere acceso), ma introduce una dipendenza in più rispetto al
piano iniziale: un `git push` manuale dopo ogni `run.py publish` perché i dati
online si aggiornino. Dettagli completi in 16.5, T10.

### 16.2.2 Libreria mappa: Google Maps JavaScript API
Non Leaflet/OpenStreetMap (che non avrebbe richiesto alcuna API key). Scelto per
coerenza con l'ecosistema Google già in uso nel progetto (Sheets, Drive, OAuth).
Implicazione diretta: serve una API key di Google Cloud, e quella key finisce nel
sorgente HTML pubblicato su Drive — vedi 16.2.3 per come si limita l'esposizione.

### 16.2.3 Mitigazione della API key esposta: restrizioni HTTP referrer
La key viene ristretta in Google Cloud Console (Credenziali → la key → *Restrizioni
applicazione*) ai soli referrer da cui la pagina verrà effettivamente aperta:

```
Restrizioni applicazione → HTTP referrer (siti web):
  https://drive.google.com/*
  https://*.googleusercontent.com/*

Restrizioni API:
  Limita la key solo a "Maps JavaScript API"
```

Se qualcuno copia la key dal sorgente e la usa da un altro dominio, Google la
rifiuta. Non elimina il rischio (un referrer può essere falsificato da chi chiama
l'API direttamente, non da browser), ma è la mitigazione standard per una key
lato client e riduce l'abuso casuale a costo di configurazione quasi nullo. Non è
stata scelta anche una quota giornaliera bassa come ulteriore rete di sicurezza:
può essere aggiunta in un secondo momento senza toccare il codice della webapp,
in Google Cloud Console.

---

## 16.3 Architettura proposta

```
run.py publish
    │
    ├── (come oggi) scrive Eventi / Eventi_estesi / Quarantena / Archivio /
    │   Serie / Fonti / CoperturaComuni / CoperturaAltreEntita / Stato / Log
    │
    └── (nuovo) genera eventi_mappa.json
            │
            ▼
    Caricato a mano su Drive accanto al file Sheets
    (stessa cartella, nessuna automazione di upload richiesta — vedi 16.6)
            │
            ▼
    mappa.html (statico, generato una volta, non cambia più a ogni publish)
    apre eventi_mappa.json con fetch() se serve dallo stesso Drive,
    oppure l'utente lo incolla/aggiorna manualmente — vedi 16.4.2 per il trade-off
```

### 16.3.1 Formato di `eventi_mappa.json`

Un array piatto, un elemento per evento attivo (stessa fonte di `Eventi` +
`Eventi_estesi`, **non** `Archivio` — la mappa serve a decidere dove andare, non a
consultare lo storico):

```json
{
  "generato_il": "2026-08-31T06:00:00",
  "eventi": [
    {
      "id": "a1b2c3d4e5f6",
      "titolo": "Sagra della Nocciola",
      "comune": "Cortemilia",
      "lat": 44.6198,
      "lon": 8.2988,
      "km": 32.1,
      "data_inizio": "2026-09-05",
      "data_fine": "2026-09-07",
      "tipologia": "sagra",
      "url": "https://..."
    }
  ]
}
```

Campi ridotti al minimo utile per la mappa (niente `descrizione`/`fonti`/`note` —
chi vuole il dettaglio apre `url` o consulta il foglio Sheets, che resta la fonte
completa). `lat`/`lon` vengono dal JOIN già usato altrove nel progetto
(`comuni.comune` → coordinate), stesso pattern di
[`righe_da_sqlite`](03-modello-dati.md#32-schema-sqlite-locale) esteso con fascia.

### 16.3.2 Logica di filtro nella webapp

Un solo controllo: **data di osservazione** (default: oggi). Per ogni comune con
almeno un evento tale che `data_inizio <= data_osservazione <= data_fine`, un
marker sulla mappa. Click sul marker → elenco degli eventi di quel comune in quel
giorno (titolo, tipologia, orario se presente, link). Nessun altro filtro richiesto
esplicitamente — tipologia/fascia possono essere aggiunte in un secondo giro se
servono nell'uso reale (vedi 16.5, fuori scope della v1).

---

## 16.4 Punti aperti da decidere prima di scrivere codice

Non bloccanti per iniziare la v1 (16.5), ma da tenere presenti:

### 16.4.1 Un comune con più eventi lo stesso giorno
Un solo marker per comune (non uno per evento — a 100km di raggio e ~683 comuni,
un marker per evento rischia di sovrapporsi illeggibilmente nei giorni di sagra
diffusa). Il popup elenca tutti gli eventi di quel comune in quel giorno.

### 16.4.2 Come il JSON arriva dal PC a Drive
`run.py publish` scrive il file in locale (`data/eventi_mappa.json`, stesso posto
di `eventi.db`). L'upload su Drive resta manuale finché non si decide se vale la
pena automatizzarlo con l'API Drive già usata per Sheets — il progetto ha già le
credenziali OAuth necessarie ([03.2](03-modello-dati.md#32-schema-sqlite-locale)),
quindi l'automazione futura è un'estensione naturale, non un nuovo prerequisito.
Per la v1: upload manuale, stesso ritmo con cui oggi si ricontrolla il foglio.

### 16.4.3 Aggiornamento del JSON senza ripubblicare l'HTML
Il file `mappa.html` è generato una volta e non cambia più a ogni publish; solo
`eventi_mappa.json` viene rigenerato. Risolto implementando entrambi i percorsi
fin dalla v1 (vedi T3 in 16.5): un `fetch()` automatico opzionale se in futuro si
configura un URL Drive stabile, e sempre disponibile un caricamento manuale del
file nella pagina (`<input type="file">`), che non dipende da CORS o dalla
stabilità del link di condivisione di Drive per un file sovrascritto. Il secondo
percorso è quello verificato funzionante nel collaudo T7; il primo resta da
verificare in T8 una volta autorizzati i referrer Drive sulla API key.

---

## 16.5 Come funziona oggi (v1, riassunto)

Sviluppo cronaca completa (10 tappe T1-T10, poi 3 giri di fix/miglioramenti):
[CRONACA.md](../CRONACA.md#webapp-mappa--cronaca-dettagliata-di-sviluppo-e-collaudo-2026-08-31).
Qui solo l'esito finale:

- `publisher.righe_eventi_per_mappa` (JOIN `events`×`comuni` per lat/lon/km,
  un comune senza coordinate è escluso, mai forzato a 0,0) e
  `publisher.scrivi_eventi_mappa_json` scrivono `data/eventi_mappa.json` e una
  copia in `docs/eventi_mappa.json`, ad ogni `run.py publish`.
- `docs/index.html` (webapp mappa) carica quel JSON con path relativo — stesso
  dominio, nessun CORS possibile per costruzione. Google Maps JavaScript API,
  key pubblica per design (protezione reale: restrizioni HTTP referrer su
  `https://marcomancini78.github.io/*`, vedi [16.2.3](#1623-mitigazione-della-api-key-esposta-restrizioni-http-referrer)).
- Filtro per data (selettore custom in italiano con navigazione ◀ ▶ e
  pulsante "Oggi", calendario nativo apribile via `showPicker()`), un marker
  per comune (non per evento), popup con titolo/tipologia/descrizione/periodo/
  distanza/fonte/link. Badge giallo "⚠️ Da verificare" se l'evento è in
  quarantena (`stato == 'quarantena'` nel JSON).
- Percorso di fallback ancora presente: pulsante "Carica eventi_mappa.json…"
  per caricamento manuale, utile se il fetch automatico non è disponibile
  (era l'unico percorso funzionante prima della pubblicazione su GitHub
  Pages, vedi cronaca T3/T8).

---

## 16.7 Webapp elenco (tabellare)

Nata il 2026-09-10 come vista alternativa sugli stessi dati, non richiesta
formalmente ma sviluppata rapidamente (9 commit in 24 ore). Cronaca completa:
[CRONACA.md](../CRONACA.md#webapp-elenco-eventi--sviluppo-2026-09-1011).

- **File**: `eventi/webapp/elenco.template.html` (sorgente) e
  `eventi/docs/elenco.html` (pubblicato) — mantenuti identici a mano, nessuna
  generazione automatica: **non esiste alcun modulo Python che scrive o
  processa `elenco.html`**, è puramente statico. Va tenuto sincronizzato
  manualmente con la copia sorgente ad ogni modifica (un fix applicato solo a
  una delle due copie è già successo, vedi cronaca punto 10).
- **Dati**: stesso `eventi_mappa.json` della mappa — nessun file separato,
  nessuna duplicazione di logica di raccolta dati.
- **Filtri**: data singola (preimpostata a oggi), comune, tipologia
  (popolati dinamicamente dai valori distinti presenti nei dati).
- **Colonne**: numero progressivo, titolo (badge quarantena se applicabile),
  tipologia, comune, data inizio/fine, km, descrizione, link alla fonte.
  Ordinamento cliccabile su ogni colonna, default km crescente.
- **Vista a schede** alternativa su mobile, stessi dati.
- **Collegamento con la mappa**: solo un link statico `<a href="elenco.html">`
  in `mappa.template.html`/`docs/index.html` — nessuna integrazione più
  profonda (nessuno stato condiviso tra le due pagine).

## 16.8 Webapp perimetro (elenco comuni)

Richiesta esplicita dell'utente (2026-09-11): una pagina con un comune per
riga (numero, nome, provincia, distanza km/minuti) e tutti i link collegati —
sito del comune, social del comune, sito Pro Loco, social Pro Loco, "Altro"
per teatri/altre attività collegate al comune.

**Dati**: `publisher.righe_perimetro_completo` fa un JOIN a tre vie:
- `comuni` — base (istat, nome, provincia, km, minuti).
- `sources` — sito web di comune/Pro Loco (`categoria` + `endpoint`),
  collegato al comune tramite lo stesso slug con cui `run.py import-fonti`
  costruisce i `source_id` (`comune-{slug}`, `proloco-{slug}-sito`:
  `nome.lower().replace(' ', '-')`).
- `coda_follow` — social di comune/Pro Loco/altro, già collegato per
  `comune` esplicito.

**"Altro" (teatri e attività)**: `coda_follow` con `categoria='teatro'` aveva
sempre `comune=NULL` — il nome del comune era scritto solo nel testo di
`soggetto` ("Cambiano - Teatro Comunale"). Deduzione fatta con
`src/collega_teatri.py` (`run.py collega-teatri`, comando manuale, non
schedulato) e **persistita** in `coda_follow.comune`, non ricalcolata ad
ogni publish — così resta correggibile a mano come ogni altro campo del
progetto. Collaudato sui dati reali: 31/33 teatri collegati automaticamente
(2 non risolti perché il comune, Savona, è fuori dal perimetro dei 683 —
comportamento corretto, non un bug). Un soggetto seguito su Facebook e
Instagram compare una sola volta in "Altro" con entrambi i link, non due
righe duplicate.

**Pagina**: `webapp/perimetro.template.html` → `webapp/perimetro.html` +
`docs/perimetro.html` (stesso pattern statico delle altre due webapp, dati
da `perimetro.json`). Ricerca testuale sul nome comune, filtro per provincia,
ordinamento per colonna (default km crescente), vista a schede su mobile.
Link icona 🌐 per i siti, "f"/"ig" per i social, chip cliccabili per "Altro".

Collaudato con Playwright: 683 comuni caricati, filtri e ordinamento
funzionanti, navigazione incrociata con mappa ed elenco verificata, zero
errori JavaScript.

## 16.6 Cosa resta esplicitamente fuori scope (v1)

Per evitare di costruire più del richiesto:

- **Filtri aggiuntivi** (tipologia, fascia, raggio) — la richiesta esplicita è
  solo il filtro per data di osservazione. Aggiungerli ora sarebbe design
  speculativo su un uso non ancora osservato.
- **Automazione dell'upload su Drive** — manuale per la v1 (16.4.2); l'automazione
  è un'estensione naturale ma non richiesta ora.
- **Editing dallo stato (`stato`/`note`/`bloccato`)** — resta responsabilità
  esclusiva del foglio Sheets, che è già lo strumento operativo per quello.
- **Vista storica (`Archivio`)** — la mappa mostra solo eventi presenti/futuri,
  stessa filosofia del foglio `Eventi`/`Eventi_estesi` ([03.1](03-modello-dati.md#31-struttura-del-google-sheet)).
