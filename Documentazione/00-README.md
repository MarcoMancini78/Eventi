# Aggregatore Eventi Locali — Documentazione di progetto

Sistema personale per costruire e mantenere aggiornato un elenco di eventi
(feste, sagre, serate gastronomiche, degustazioni, concerti, teatro, cinema, ecc.)
in un raggio definito da casa, raccogliendo dati da siti istituzionali, portali
aggregatori e canali social.

**Stato:** in produzione. Pipeline attiva su 703 fonti, pubblicazione su Google
Sheets, due webapp pubbliche (mappa ed elenco) su GitHub Pages. Per lo stato
aggiornato giorno per giorno vedi [STATO-PROGETTO.md](../STATO-PROGETTO.md)
nella cartella radice — questa cartella descrive l'architettura, non lo stato
corrente.
**Vincolo principale:** budget zero (o quasi), esecuzione su PC personale.

---

## Indice dei documenti

| # | Documento | Contenuto |
|---|---|---|
| 01 | [Requisiti](01-requisiti.md) | Obiettivi, scope, requisiti funzionali e non funzionali, KPI |
| 02 | [Architettura](02-architettura.md) | Pipeline a stadi, componenti, flusso dati |
| 03 | [Modello dati](03-modello-dati.md) | Schema Google Sheet + DB locale |
| 04 | [Fonti e ingestione](04-fonti-ingestione.md) | Classificazione fonti, discovery automatica, tecniche di fetch |
| 05 | [Social e locandine](05-social-locandine.md) | Il problema principale: opzioni valutate e strategia |
| 06 | [Estrazione LLM](06-estrazione-llm.md) | Prompt, schema di output, gestione locandine, confidenza |
| 07 | [Normalizzazione, geo, dedup](07-normalizzazione-geo-dedup.md) | Date, luoghi, distanze, deduplica |
| 08 | [Orchestrazione e operatività](08-orchestrazione-operativita.md) | Scheduling, incrementalità, budget di tempo, monitoraggio |
| 09 | [Stack e costi](09-stack-costi.md) | Scelte tecnologiche a costo zero e alternative |
| 10 | [Roadmap](10-roadmap.md) | Fasi incrementali, con Fase 0 di validazione |
| 11 | [Rischi e decisioni aperte](11-rischi-decisioni.md) | Limiti legali/ToS, punti da decidere prima di partire |
| **12** | **[Scala e copertura](12-scala-e-copertura.md)** | **~2.000 comuni, migliaia di fonti: la strategia di raccolta. Leggere subito dopo il 02** |
| **13** | **[Audit del dataset esistente](13-audit-fonti.md)** | **Difetti sistematici del workbook attuale e cosa esportarne** |
| **14** | **[Account social dedicato](14-account-social.md)** | **Creazione, riscaldamento, coda di follow. Da avviare per primo** |
| **15** | **[Guida all'implementazione](15-guida-implementazione.md)** | **Cosa scrivere, in che ordine, con criteri di accettazione. Il documento operativo** |
| 16 | [Webapp mappa ed elenco](16-webapp-mappa.md) | Le due interfacce pubbliche: mappa filtrabile per data ed elenco tabellare |
| **17** | **[Lavoro residuo](17-lavoro-residuo.md)** | **Audit doc vs codice: cosa manca ancora, in ordine di priorità (da ripetere periodicamente, non un'istantanea definitiva)** |

Cronaca dettagliata di bug/collaudi/decisioni prese in corsa: [CRONACA.md](../CRONACA.md)
nella cartella radice (append-only, non serve leggerla per capire lo stato attuale).

---

## Da dove si comincia

**Se devi iniziare a sviluppare:** [15 — Guida all'implementazione](15-guida-implementazione.md).
Contiene l'ordine di lavoro, le tappe M0-M11 e i criteri di accettazione.

**Le tre cose da avviare oggi**, prima di scrivere codice, perché hanno tempi di
calendario propri:
1. Creazione dei due account social ([14](14-account-social.md)) — 2 settimane di
   riscaldamento prima di poter seguire chiunque
2. Casella email dedicata
3. Verifica di PiemonteItalia e VisitLMR: se espongono dati strutturati, cambia
   l'ordine di tutto il resto

**Percorso di lettura consigliato:** 02 (architettura) → 12 (scala) → 15 (guida) →
il resto come riferimento.

### Parametri fissati

| | |
|---|---|
| Casa | Calosso (AT) |
| Perimetro | ≤ 100 km, ~1.200-1.400 comuni |
| Fasce | A ≤ 50 km · B ≤ 75 · C ≤ 100 |
| Polling diretto | insieme chiuso, ~100 fonti |
| Regime massivo | comuni e Pro Loco, esaustivo |
| Regime curato | feste, teatri, locali, cantine — max ~200, manuali |
| Vista principale | tutte le righe attive in `Eventi` (dal 2026-09-10; in origine 21 giorni/fasce A-B) |
| Esclusi | sport, bambini, programmazione cinematografica ordinaria |
| LLM | cloud, nessuna GPU locale |

---

## Sintesi: perché il tentativo precedente è fallito e cosa cambia

Il problema segnalato — *"ogni sito ha una struttura diversa"* e *"sui social pubblicano
solo la locandina"* — non è un problema di implementazione, è un problema di
**architettura**. Un parser per sito non scala e si rompe di continuo.

Le cinque decisioni che ribaltano l'impostazione:

### 1. Separare la raccolta dalla comprensione
Nessun componente deve capire *contemporaneamente* come navigare un sito e cosa
significa il contenuto. Gli adattatori di fonte producono solo **artefatti grezzi**
(testo ripulito, immagini, metadati). Un **unico estrattore basato su LLM** trasforma
qualsiasi artefatto in un evento strutturato. Aggiungere una fonte diventa aggiungere
una riga a un foglio, non scrivere codice.

### 2. Gerarchia di fonti a costo crescente (T0→T3)
Prima di scrapare, si cerca sempre un canale strutturato: calendario iCal, feed RSS,
JSON-LD `schema.org/Event`, API di dati aperti. Molti siti comunali e teatrali ne
hanno uno e nessuno lo cerca. Ogni fonte che scende da T2 a T0 è un problema in meno
per sempre. Vedi [04](04-fonti-ingestione.md).

### 3. La locandina non è un ostacolo, è il formato principale
Non OCR + regole. **Modello visuale multimodale** che legge l'immagine e restituisce
JSON direttamente. Con l'hashing percettivo, la stessa locandina ripubblicata su 5
canali viene analizzata una volta sola. Vedi [06](06-estrazione-llm.md).

### 4. I social si leggono al contrario
Non si visitano 2.350 profili: **un account dedicato li segue tutti e si legge il
proprio feed cronologico**. Una sessione invece di duemila, con un fattore di
riduzione di circa 20× — e un profilo di rischio molto più basso, perché scorrere il
feed è ciò che fa un utente normale. È questa leva che rende Instagram sostenibile.
Vedi [12](12-scala-e-copertura.md#123-l1--inversione-del-feed-social-).

### 5. A 1.000 comuni non tutte le fonti valgono uguale
Il perimetro è stratificato in **fasce di distanza** con livelli di servizio diversi:
copertura piena entro 50 km, solo aggregatori e T0 fino a 100. Ed è l'unica parte del
progetto dove scrivere parser specifici conviene — non per sito, ma per **famiglia di
CMS**: mille siti comunali sono una decina di piattaforme ripetute.
Vedi [12](12-scala-e-copertura.md).

Ciò che **non** si fa mai è disattivare una fonte perché tace: una Pro Loco che
pubblica solo per la sagra di luglio è silenziosa undici mesi e poi produce l'evento
più importante del suo comune. Il silenzio allunga l'intervallo di controllo — e
l'intento è farlo attivare una **finestra di attenzione stagionale** derivata da
quando quella fonte ha pubblicato negli anni scorsi, non ancora implementata
(rimossa dal foglio Fonti il 2026-08-28 per assenza di un dato sorgente reale,
vedi [03-modello-dati.md §3.1.4](03-modello-dati.md#314-fonti)). Solo l'errore
persistente sospende, ed è reversibile.
Vedi [04](04-fonti-ingestione.md#47-fonti-dormienti--fonti-inutili).

### 6. Sheets è l'interfaccia, non il database
Lo stato operativo (cache, hash, cronologia, deduplica) sta in un SQLite locale.
Il Google Sheet è la vista pubblicata e il pannello di controllo umano — e con questi
volumi la vista principale va deliberatamente **limitata**, o l'elenco diventa
illeggibile. Vedi [03](03-modello-dati.md).

---

## Prerequisito non negoziabile

La [Fase 0](10-roadmap.md#fase-0--validazione-empirica-1-2-settimane) è uno **spike di
misurazione su 10-15 fonti reali**, senza costruire il sistema. Serve a rispondere a:
quante fonti hanno un feed T0? Facebook risponde ancora senza login? Che accuratezza
dà un modello visuale sulle locandine vere della tua zona?

Costruire prima di aver misurato è esattamente ciò che ha fatto fallire il primo
tentativo. Se i numeri della Fase 0 sono negativi, il progetto va ridimensionato
(meno fonti, più qualità) — non riprovato con più codice.
