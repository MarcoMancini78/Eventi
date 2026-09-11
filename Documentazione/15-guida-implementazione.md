# 15 — Guida all'implementazione

Documento operativo: **cosa scrivere, in che ordine, e come sapere che funziona**.
Gli altri documenti dicono *cosa* e *perché*; questo dice *come procedere*.

Ogni tappa (M0, M1, …) è chiusa da un **criterio di accettazione verificabile**.
Non si passa alla successiva finché non è soddisfatto. La regola vale soprattutto
per le tappe noiose: sono quelle che, saltate, fanno crollare tutto tre settimane dopo.

---

## 15.0 Prima di scrivere una riga

Tre attività da avviare **oggi**, in parallelo, perché hanno tempi di calendario
propri:

| Attività | Tempo | Perché ora |
|---|---|---|
| Creazione dei due account social | 2 settimane di riscaldamento | [14.3](14-account-social.md#143-riscaldamento--2-settimane-prima-di-qualunque-follow-massivo). Senza, la Fase social slitta di due mesi |
| Casella email dedicata | 10 minuti | Serve per gli account e poi per le newsletter |
| Verifica di PiemonteItalia e VisitLMR | mezza giornata | Se espongono dati strutturati, cambia l'ordine di tutto il resto |

---

## 15.1 Convenzioni di progetto

**Regole non negoziabili**, perché ognuna corrisponde a un errore già commesso o
previsto nei documenti precedenti:

1. **Nessun numero magico nel codice.** Tutte le soglie stanno in `Config`. Se ti
   serve un valore che non c'è, aggiungi la riga al foglio, non la costante.
2. **Nessun selettore CSS specifico per un singolo sito.** Gli adattatori sono per
   *tipo di canale* o per *famiglia di piattaforma*, mai per comune.
3. **Ogni chiamata di rete ha un timeout esplicito.** Senza, una singola pagina
   appesa mangia il budget dell'intero run.
4. **Ogni fonte è isolata:** un'eccezione non deve mai propagarsi al run.
5. **Sheets si scrive solo in batch**, mai cella per cella, mai riga per riga.
6. **L'output grezzo dell'LLM si salva sempre** in `extractions`. È ciò che permette
   di riprocessare mesi di dati a costo zero quando cambi le regole.
7. **Il pre-filtro precede sempre la chiamata LLM.** Senza GPU è l'unica difesa del
   budget di quota.
8. **Ogni funzione che tocca la rete ha una fixture corrispondente** in `tests/`.
   Devi poter far girare l'intera pipeline offline.

### Struttura

```
eventi/
  config/.env                  # segreti — MAI nel repository
  src/
    orchestrator.py            # coda, budget, isolamento errori
    registry.py                # sincronizzazione con i fogli
    store.py                   # SQLite
    prober.py                  # discovery endpoint strutturati
    fingerprint.py             # famiglie di piattaforma
    prefilter.py               # ⚠️ componente critico
    adapters/
      base.py ical.py rss.py jsonld.py html.py
      platform/                # adattatori per famiglia di CMS
      feed_social.py social_polling.py follow.py
      email_imap.py telegram.py
    extractor/
      client.py                # astrazione LLM
      prompts/  schema.py
    normalizer.py recurrence.py geo.py dedup.py
    publisher.py status.py
  data/  eventi.db  cache/images/  logs/  sessions/
  tests/fixtures/
  run.py
```

`run.py` è l'unico punto d'ingresso, con sottocomandi:

```
run.py init                 # crea fogli e DB
run.py import-perimetro     # una tantum
run.py discover [--fascia]  # discovery e fingerprinting
run.py follow --platform=X  # lotto di 10 follow, lancio manuale
run.py run --profile=leggero|principale
run.py publish              # solo pubblicazione
run.py reprocess            # riestrae dal grezzo, senza rete
run.py doctor               # diagnostica
```

---

## M0 — Fondamenta (2-3 giorni)

**Obiettivo: leggere e scrivere i fogli, senza alcuna logica di dominio.**

1. Repository, `.env`, service account Google, `Config` in un modulo
2. `store.py`: schema SQLite di [03.2](03-modello-dati.md#32-schema-sqlite-locale),
   migrazioni banali (una tabella `schema_version`)
3. `registry.py`: lettura di `Config`, `Perimetro`, `Fonti`, `Tipologie` → SQLite
4. `publisher.py`: scrittura batch di un foglio, con **rilettura preventiva** delle
   colonne che modifichi tu (`stato`, `note`, `bloccato`, `soppressa`)
5. `run.py init` che crea l'intera struttura di fogli da zero

✅ **Accettazione:** `run.py init` crea il workbook completo; scrivi 500 righe finte
in `Eventi` in meno di 10 secondi; modifichi a mano la colonna `note` di una riga,
rilanci la scrittura, e **la modifica sopravvive**.

Quest'ultimo test è il più importante di M0: se non passa, perderai il tuo lavoro
manuale ogni notte e smetterai di usare il sistema entro due settimane.

---

## M1 — Perimetro (1 giorno)

1. Import del foglio `Perimetro` dal workbook esistente
   - ⚠️ decimali con **virgola** tra apici: `"5,5"` → `5.5`. Se lo dimentichi,
     ottieni silenziosamente distanze nulle
2. Filtro a 100 km, derivazione della fascia (50 / 75 / 100)
3. Popolamento di `alias` per i comuni in fascia A (frazioni)
4. Indice di ricerca comune: normalizzazione (minuscolo, senza accenti) + alias

✅ **Accettazione:** query `risolvi_comune("Calosso")`, `("CALOSSO")`, `("Oreno")`
restituiscono il comune giusto con km e minuti; il conteggio per fascia è stampabile
e i numeri sono plausibili (~400 / ~300 / ~500).

---

## M2 — Il primo evento vero (3-4 giorni)

**Obiettivo: un evento reale nel foglio, senza LLM.** È la tappa che rende il
progetto tangibile.

1. `adapters/base.py`: contratto `fetch(fonte) → list[Artefatto]`
2. `ical.py`, `rss.py`, `jsonld.py`
3. `normalizer.py`: date ISO, risoluzione comune, pulizia titolo
4. `dedup.py` livello 1 (chiave esatta)
5. `publisher`: scrittura in `Eventi`, ordinamento per rilevanza
6. **Archiviazione**: spostamento in `Archivio` degli eventi con
   `data_fine < oggi − 2` ([03.1.2](03-modello-dati.md#rotazione-degli-eventi-conclusi))

✅ **Accettazione:** partendo da 3-5 fonti T0 reali, `run.py run` produce eventi
corretti in `Eventi`; un evento con data passata sparisce dal foglio principale e
compare in `Archivio`; rilanciare due volte non duplica nulla.

---

## M3 — Aggregatori (3-5 giorni)

Prima degli LLM, prima dei social: è il miglior rapporto copertura/sforzo del progetto.

1. Adattatori per PiemonteItalia, VisitLMR, VisitPiemonte e i portali sagre
2. Se espongono dati aperti o API: parsing diretto, nessun LLM
3. Altrimenti restano in coda per M5

✅ **Accettazione:** almeno un aggregatore produce ≥ 50 eventi reali entro il
perimetro, con comune risolto correttamente in ≥ 90% dei casi.

A questo punto il sistema è **già utile**. Da qui in poi ogni tappa aggiunge
copertura a qualcosa che funziona.

---

## M4 — Pre-filtro (2-3 giorni)

⚠️ **Va scritto prima dell'estrattore, non dopo.** Senza GPU è l'unica cosa che
protegge la quota, e scriverlo dopo significa scoprire di aver bruciato il budget
in due giorni di test.

1. `prefilter.py` testuale: pattern di date, parole chiave, schemi di non-evento
2. `prefilter.py` grafico: dimensioni, rapporto d'aspetto, **densità di testo**
   (filtro di Sobel o equivalente — distingue una locandina da una foto)
3. Cache `pHash` con distanza di Hamming ≤ 8
4. Cache dell'hash testuale normalizzato

✅ **Accettazione:** su 100 post reali salvati come fixture, il pre-filtro scarta
≥ 50% degli artefatti e **non scarta più del 5% degli eventi veri**. Il secondo
numero conta molto più del primo: un falso negativo è un evento perso per sempre.

---

## M5 — Estrazione LLM (1 settimana)

1. `extractor/client.py`: astrazione del fornitore, retry con backoff sul 429,
   contatore di quota persistente
2. Prompt testuale + validazione dello schema
3. Adattatore `html.py` generico con `trafilatura`
4. Confidenza ([06.6](06-estrazione-llm.md#66-calcolo-della-confidenza-finale))
   e routing in `Quarantena`
5. `dedup.py` livello 3 (fuzzy con blocking per data+comune)
6. `run.py reprocess`: riestrazione dal grezzo, **senza rete e senza quota**

✅ **Accettazione:** su 30 artefatti reali, ≥ 90% di date corrette e ≥ 95% di comuni
corretti; `reprocess` rigenera gli stessi eventi partendo dal DB, senza una sola
chiamata di rete.

---

## M6 — Ricorrenze (3-4 giorni)

1. Campi strutturati di ricorrenza nello schema di estrazione
2. `recurrence.py`: campi → RRULE (`dateutil.rrule`) → occorrenze
3. Foglio `Serie`, con `regola_leggibile` accanto alla RRULE
4. Espansione entro `orizzonte_espansione_giorni` (120), orizzonte scorrevole
5. `soppressa` e `bloccato` rispettati
6. Decadimento: 120 giorni → `da_verificare`, 400 → `sospesa`

✅ **Accettazione:** *"mercatino la prima domenica del mese, escluso agosto"* genera
le date corrette saltando agosto; cancelli un'occorrenza, rilanci, **e non torna**;
un annuncio singolo della stessa data confluisce nella riga generata invece di
duplicarla.

Il secondo test è quello che di solito fallisce, ed è quello che ti farebbe
abbandonare il foglio.

---

## M7 — Canali push (3-4 giorni)

1. `email_imap.py`: lettura della casella, testo + immagini allegate
2. Rilevazione dei moduli newsletter in `discover` → foglio `Newsletter`
3. `telegram.py`: API bot ufficiale

✅ **Accettazione:** un'email di newsletter reale produce eventi corretti; il foglio
`Newsletter` contiene una lista ordinata di soggetti con link di iscrizione.

---

## M8 — Fingerprinting e adattatori di piattaforma (1 settimana)

1. `fingerprint.py`: scarica le homepage, classifica per firma
   (meta generator, percorsi, struttura URL). Indizi noti: `municipiumapp.it`,
   il pattern `comune.NOME.PROV.it`
2. Classifica per frequenza le famiglie
3. Un adattatore per famiglia, partendo dalla più diffusa
4. Ritesta le sitemap con uno **User-Agent diverso**: il dato attuale
   (`HTTPStatusError` quasi ovunque) non è credibile ed è probabilmente un blocco

✅ **Accettazione:** ≥ 60% dei comuni di fascia A è coperto da un adattatore di
famiglia; il tasso di sitemap disponibili è nettamente superiore a quello registrato
nel workbook.

---

## M9 — Follow (2-3 giorni)

1. Foglio `CodaFollow`, popolato e ordinato da `Fonti`
   ([14.4](14-account-social.md#144-popolamento--coda-di-follow-semiautomatica))
2. `adapters/follow.py`: Playwright con **sessione persistente**, nessun re-login
   automatico
3. Le precondizioni e l'interruttore di sicurezza di
   [14.5](14-account-social.md#145-interruttore-di-sicurezza)
4. `run.py follow --dry-run` che stampa cosa farebbe senza farlo

✅ **Accettazione:** `--dry-run` elenca i 10 corretti nell'ordine giusto; un lotto
reale segue 10 profili in 6-10 minuti con pause irregolari; simulando un captcha, il
circuito si apre e il comando successivo **rifiuta di partire**.

Il `--dry-run` va usato davvero le prime volte. Un bug qui non produce un errore:
produce un account bloccato.

---

## M10 — Feed social e locandine (1-2 settimane)

1. `feed_social.py`: lettura cronologica, scroll fino all'ultimo post visto
2. Attribuzione: `handle` → `source_id` → comune. Handle sconosciuto → **candidato
   fonte**, non scarto
3. Prompt VLM ([06.4](06-estrazione-llm.md#64-prompt-per-locandine-vlm))
4. Priorità della quota per fascia
5. `social_polling.py` per le ~100 fonti in `polling_diretto`
6. Gruppi come categoria separata, comune **mai inferito**

✅ **Accettazione:** una sessione di feed produce eventi attribuiti al comune giusto;
la stessa locandina su due canali diversi genera **una sola** chiamata VLM e un solo
evento.

---

## M11 — Operatività (3-4 giorni)

1. Coda a priorità dinamica e budget di tempo
2. Scheduling con recupero **coalescente** (un solo run al riavvio)
3. Lock file
4. Foglio `Stato` con semafori
5. Backup settimanale del workbook
6. `run.py doctor`

✅ **Accettazione:** spegni il PC per tre giorni, lo riaccendi, parte **un solo** run;
un run che sfora il budget si interrompe pulitamente e riprende dal punto giusto;
`Stato` segnala rosso se non ci sono eventi nuovi da 7 giorni.

**Stato reale**: tutti i componenti elencati esistono nel codice
(`lockfile.py`, `stato_sistema.py`, `drive_backup.py`/`run.py backup-sheets`,
`run.py doctor`) — non risulta però un collaudo esplicito dell'accettazione
sopra (spegnimento reale di 3 giorni). Da verificare prima di considerare M11
davvero chiuso.

---

## 15.2 Ordine di lavoro, in breve

> **Tempistica puramente indicativa**, scritta prima di iniziare. Il ritmo
> reale ha avuto ampio overlap tra tappe (più M in corso in parallelo) invece
> di seguire le settimane numerate una per una. L'utile qui è l'**ordine di
> dipendenza** (M9 dopo aver creato l'account e aspettato il riscaldamento,
> M8 prima degli adattatori per famiglia, ecc.), non il numero di settimana.
> Per lo stato reale di avanzamento vedi [STATO-PROGETTO.md](../STATO-PROGETTO.md).

```
OGGI          account social + email dedicata + verifica aggregatori
SETT. 1-2     M0 M1 M2        → primi eventi veri nel foglio
SETT. 3       M3              → il sistema è già utile
SETT. 4-5     M4 M5           → salto di copertura
SETT. 6       M6 M7
SETT. 7-8     M8              → i mille siti comunali
SETT. 9       M9              → follow (account ormai riscaldato)
SETT. 10-11   M10             → feed e locandine
SETT. 12      M11             → gira da solo
```

I follow (M9) arrivano alla settimana 9 ma l'account è stato creato al giorno 1:
è esattamente l'incastro che rende il lead time invisibile.

---

## 15.3 Errori tipici, e dove sono già documentati

| Errore | Sintomo | Prevenzione |
|---|---|---|
| Sovrascrivere le modifiche manuali | Perdi note e conferme ogni notte | Test di accettazione M0 |
| Espansore che ricrea le occorrenze cancellate | La cancellazione non ha effetto | Flag `soppressa`, test M6 |
| Contare gli errori in run invece che in giorni | Fonti dormienti marcate rotte | [04.8](04-fonti-ingestione.md#48-fonti-rotte-qui-la-sospensione-ha-senso) |
| Disattivare fonti silenziose | Perdi la sagra annuale | [04.7](04-fonti-ingestione.md#47-fonti-dormienti--fonti-inutili) |
| Match di entità per somiglianza del nome | Eventi del comune sbagliato | [13.4](13-audit-fonti.md#134-regole-di-bonifica), livello 2 |
| Estrarre il primo link `facebook.com` dell'HTML | Widget di condivisione come profili | [13.2](13-audit-fonti.md#132-tassonomia-dei-difetti-riscontrati), difetto B |
| Chiamare l'LLM prima del pre-filtro | Quota esaurita in due giorni | M4 prima di M5 |
| Schedulare i follow | Account bloccato | [14.4](14-account-social.md#144-popolamento--coda-di-follow-semiautomatica) |
| Decimali con virgola non convertiti | Distanze a zero, silenziosamente | M1 |
| Vista principale senza limiti | Foglio illeggibile | [12.11](12-scala-e-copertura.md#1211-loutput-non-deve-annegare) |

---

## 15.4 Quando fermarsi

Il progetto è finito quando **smetti di controllare Facebook a mano** prima del
weekend. Non quando tutte le fonti sono coperte: quella soglia non arriva mai, e
inseguirla è il modo in cui questi sistemi consumano il tempo che dovevano far
risparmiare.

Se dopo M11 la copertura misurata sulla fascia A supera il 70-80%, il resto è
manutenzione e affinamento incrementale
([Fase 6](10-roadmap.md#fase-6--affinamento-continuo)) — non una fase di sviluppo.
