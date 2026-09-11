# 03 — Modello dati

## 3.1 Struttura del Google Sheet

Un unico spreadsheet con i fogli seguenti. I fogli marcati **[IN]** li compili tu,
quelli **[OUT]** li scrive il sistema, quelli **[I/O]** sono misti.

| Foglio | Direzione | Scopo |
|---|---|---|
| `Eventi` | I/O | **Tutte** le righe attive (presenti/future), in un unico foglio. Fino al 2026-09-10 esisteva una vista filtrata (21 giorni, fasce A-B) più `Eventi_estesi` per il resto: unificate su richiesta dell'utente, che non vedeva il senso della divisione. `Eventi_estesi` resta nello spreadsheet ma non riceve più scritture |
| `Serie` | I/O | Regole degli eventi ricorrenti che generano le occorrenze |
| `Newsletter` | OUT + tu | Soggetti con newsletter rilevata e link di iscrizione, da fare a mano |
| `CodaFollow` | OUT + tu | Canali social da seguire, consumati 10 per volta ([14.4](14-account-social.md#144-popolamento--coda-di-follow-semiautomatica)) |
| `Stato` | OUT | Fotografia corrente con semafori ([08.9](08-orchestrazione-operativita.md#89-monitoraggio-senza-notifiche)) |
| `Quarantena` | I/O | Candidati incerti in attesa di giudizio |
| `Archivio` | OUT | Eventi conclusi. **In spreadsheet separato**, cresce senza limiti |

### Rotazione degli eventi conclusi

A ogni run, come parte dello stadio di pubblicazione
([02.2](02-architettura.md#22-pipeline-a-stadi)):

```
per ogni evento in Eventi o Eventi_estesi:
    se data_fine < oggi − giorni_archiviazione (default 2):
        SPOSTA la riga in Archivio
        (spostata, non copiata: sparisce dal foglio principale)
        conserva event_id, serie_id, fonti, stato e note
```

Il foglio principale contiene quindi **solo eventi presenti o futuri**, sempre.
`Archivio` non è solo storico passivo: alimenta la **finestra di attenzione
stagionale** delle fonti dormienti ([04.7](04-fonti-ingestione.md#47-fonti-dormienti--fonti-inutili))
e permette di riconoscere le ricorrenze annuali, perché la sagra dell'anno scorso
predice quella di quest'anno.

Le occorrenze passate di una `Serie` si archiviano come tutte le altre; la serie
resta viva e continua a generare le occorrenze future.
| `Perimetro` | IN | Comuni considerati + distanze precalcolate |
| `Fonti` | I/O | Elenco delle fonti da monitorare + statistiche |
| `Tipologie` | IN | Tassonomia e sinonimi |
| `Config` | IN | Parametri di esecuzione |
| `Log` | OUT | Esito dei run e KPI |

---

### 3.1.1 `Eventi` [I/O]

| Colonna | Tipo | Origine | Note |
|---|---|---|---|
| `id` | testo | sistema | Chiave stabile, generata (vedi 3.3). **Non modificare** |
| `titolo` | testo | estratto | Ripulito da emoji e maiuscolo urlato |
| `descrizione` | testo | estratto | Max ~400 caratteri, sintesi |
| `tipologia` | lista | classificato | Da foglio `Tipologie` |
| `data_inizio` | data | estratto | ISO `YYYY-MM-DD` |
| `ora_inizio` | ora | estratto | Vuoto se non dichiarata |
| `data_fine` | data | estratto | = `data_inizio` se evento di un giorno |
| `ora_fine` | ora | estratto | Spesso vuoto |
| `serie_id` | testo | sistema | Vuoto se evento singolo; valorizzato se occorrenza generata |
| `occorrenza` | testo | sistema | Es. "3 di 12" — solo per leggibilità |
| `comune` | testo | normalizzato | Deve esistere in `Perimetro` |
| `luogo` | testo | estratto | Piazza, teatro, oratorio, indirizzo |
| `km` | numero | calcolato | JOIN su `Perimetro` |
| `minuti` | numero | calcolato | JOIN su `Perimetro` |
| `prezzo` | testo | estratto | "gratis", "10 €", "" |
| `organizzatore` | testo | estratto | Pro Loco, compagnia, comune |
| `url` | link | fonte | Link primario |
| `url_immagine` | link | fonte | Locandina, se disponibile |
| `url_approfondimento` | link | estratto | Link "per saperne di più" trovato nel TESTO del post (es. un repost con "SCOPRI IL PROGRAMMA COMPLETO: www.sito.it") — diverso da `url`, che resta sempre il link del post sorgente (Facebook/Instagram/sito). Vuoto se nel testo non compare un link esplicito, mai indovinato |
| `fonti` | testo | sistema | Elenco `source_id` che riportano l'evento |
| `confidenza` | numero | sistema | 0-100 |
| `stato` | lista | **tu** | `nuovo` / `ok` / `interessante` / `scartato` / `corretto` |
| `note` | testo | **tu** | Libere |
| `primo_visto` | data | sistema | |
| `ultimo_visto` | data | sistema | Se non più visto per N run → possibile annullamento |
| `bloccato` | sì/no | **tu** | Se `sì`, il sistema non sovrascrive più questa riga |
| `soppressa` | sì/no | **tu** | Solo per le occorrenze generate: se `sì`, l'espansore non la ricrea più |

**Colonne che scrivi tu:** `stato`, `note`, `bloccato`, `soppressa`. Tutte le altre
possono essere sovrascritte al run successivo — a meno che `bloccato = sì`. Questo è
il meccanismo di RF-10, semplice e senza sorprese.

`soppressa` è indispensabile con le ricorrenze: senza un flag persistente, la riga che
cancelli viene ricreata dall'espansore al run successivo e la cancellazione non ha
alcun effetto visibile. Cancellare l'occorrenza di agosto del mercatino deve
funzionare la prima volta.

Ordinamento predefinito: `data_inizio` crescente, poi `km` crescente.

---

### 3.1.2 `Quarantena` [I/O]

Stesse colonne di `Eventi`, più:

| Colonna | Note |
|---|---|
| `motivo` | `data_mancante`, `comune_ambiguo`, `bassa_confidenza`, `fuori_tassonomia`, `possibile_duplicato` |
| `campi_dubbi` | Elenco dei campi problematici |
| `artefatto` | Link all'immagine o al testo originale, per giudicare in un colpo d'occhio |
| `azione` | **tu**: `promuovi` / `elimina` / `ignora_fonte` |

Il campo `artefatto` è ciò che rende la revisione veloce: se devi aprire Facebook per
capire di cosa si tratta, non lo farai.

---

### 3.1.3b `Serie` [I/O]

Le regole degli eventi ricorrenti. Poche decine di righe, ma generano una quota
significativa delle occorrenze in `Eventi`.
Logica completa in [07](07-normalizzazione-geo-dedup.md#79-ricorrenze-espansione-in-occorrenze).

| Colonna | Origine | Note |
|---|---|---|
| `serie_id` | sistema | |
| `titolo` | estratto | "Mercatino dell'antiquariato" |
| `tipologia`, `comune`, `luogo` | estratto | Valori ereditati da tutte le occorrenze |
| `rrule` | sistema | Es. `FREQ=MONTHLY;BYDAY=1SU;BYMONTH=1,2,3,4,5,6,7,9,10,11,12` |
| `regola_leggibile` | sistema | "Prima domenica del mese, escluso agosto" — per poterla correggere a colpo d'occhio |
| `valida_dal` / `valida_al` | estratto | `valida_al` vuoto = serie senza scadenza dichiarata |
| `eccezioni` | **tu** + estratto | Date da non generare, separate da `;` |
| `ultima_conferma` | sistema | Ultima volta che una fonte ha citato la serie o una sua occorrenza |
| `stato` | sistema | `attiva` / `da_verificare` / `sospesa` |
| `fonti` | sistema | |
| `bloccata` | **tu** | Se `sì`, la regola non viene più modificata dal sistema |

Il campo `regola_leggibile` esiste perché una RRULE sbagliata è invisibile a occhio:
"prima domenica" e "primo giorno" sono errori facili da fare e difficili da notare
finché non guardi le date generate.

---

### 3.1.4 `Perimetro` [I/O] — il foglio più importante

~1.000 righe. Popolato automaticamente dall'anagrafe comunale ufficiale + calcolo
batch delle distanze ([07](07-normalizzazione-geo-dedup.md#75-distanze-precalcolo-non-calcolo-a-runtime)),
poi corretto a mano dove serve. Le distanze si calcolano **una volta sola**.

| Colonna | Esempio | Note |
|---|---|---|
| `comune` | Vimercate | Nome ufficiale |
| `alias` | Vimercate, Oreno, Ruginello | Frazioni e varianti, separate da `;`. Usato per il matching |
| `provincia` | MB | |
| `lat` | 45.6142 | Centroide |
| `lon` | 9.3672 | |
| `istat` | 108050 | Codice ufficiale, chiave stabile |
| `km` | 12.4 | Distanza stradale da casa (batch) |
| `minuti` | 21 | Tempo medio auto |
| `fascia` | A/B/C/D | **Derivata da `km`**, con override manuale |
| `attivo` | sì/no | Permette di escludere temporaneamente |

Il campo `alias` risolve da solo una buona parte degli errori di localizzazione:
le locandine scrivono la frazione, non il comune. Su 1.000 comuni non lo compilerai
mai a mano per intero: popolalo **solo per la fascia A**, e lascia che cresca da solo
dalle tue conferme in quarantena (vedi il dizionario dei luoghi in
[07](07-normalizzazione-geo-dedup.md#74-il-dizionario-dei-luoghi)).

⚠️ **Attenzione all'omonimia.** Con 1.000 comuni i nomi ambigui diventano frequenti
(decine di "San Giovanni…", "Castelnuovo…", comuni con lo stesso nome in province
diverse). Il matching per nome puro non basta più: va sempre disambiguato con la
provincia, con il `comune_riferimento` della fonte o con la prossimità geografica
rispetto alla fonte. In caso di ambiguità irrisolta → quarantena, mai una scelta a
caso.

La **fascia** determina il livello di servizio ed è il fattore dominante di tutto il
sistema di priorità. Vedi [12](12-scala-e-copertura.md#124-l2--fasce-di-perimetro).

---

### 3.1.4 `Fonti` [I/O]

~2.000-5.000 righe, **generate dal bootstrap automatico**
([12](12-scala-e-copertura.md#128-bootstrap-automatico-delle-fonti)), non a mano.
Tu intervieni solo per correggere e per aggiungere la fascia A.

| Colonna | Direzione | Esempio |
|---|---|---|
| `source_id` | sistema | `proloco-vimercate-fb` |
| `soggetto` | bootstrap | Pro Loco Vimercate |
| `categoria` | bootstrap | `comune` / `proloco` / `teatro` / `cinema` / `locale` / `compagnia` / `portale` |
| `comune_riferimento` | bootstrap | Vimercate — default se l'evento non dice dove |
| `fascia` | derivata | Da `Perimetro` via `comune_riferimento` |
| `polling_diretto` | **tu** + sistema | sì/no — visita dedicata oltre al feed. Insieme chiuso, max ~100 |
| `canale` | bootstrap | `sito` / `facebook` / `instagram` / `newsletter` / `telegram` |
| `url` | bootstrap | URL della pagina o handle |
| `handle` | bootstrap | Nome account social **senza URL** — serve ad attribuire i post letti dal feed |
| `seguito` | sistema | sì/no — se l'account è già seguito dall'account dedicato |
| `piattaforma` | sistema | Famiglia di CMS rilevata dal fingerprinting ([12](12-scala-e-copertura.md#125-l3--adattatori-per-famiglia-di-piattaforma)) |
| `metodo` | sistema | `feed` / `polling` / `t0` — come viene raccolta |
| `tier` | sistema | `T0` / `T1` / `T2` / `T3` — dopo la discovery |
| `endpoint` | sistema | URL del feed trovato (ics/rss/jsonld) |
| `frequenza` | sistema/tu | `giornaliera` / `settimanale` / `mensile` |
| `attivo` | tu | sì/no — **solo per esclusione manuale**, non automatica |
| `stato` | sistema | `attiva` / `dormiente` / `in_backoff` / `rotta` |
| `priorita` | tu | 1-3 |
| `ultimo_run` | sistema | timestamp |
| `ultimo_esito` | sistema | `ok` / `vuoto` / `errore:404` / `bloccato` |
| `primo_errore` | sistema | Data del primo errore della serie corrente. Vuoto se ha risposto |
| `giorni_in_errore` | sistema | ≥ 14 su errore permanente → `rotta` + segnalazione |
| `ultimo_errore` | sistema | Messaggio testuale dell'ultimo fallimento (es. "HTTPError: 404"). Azzerato appena la fonte torna a funzionare |
| `eventi_totali` | sistema | Cumulativo |
| `eventi_utili` | sistema | Quanti sono finiti in `Eventi` senza correzioni |

⚠️ **`finestra_attenzione`, `resa_annuale` e `regime` rimosse il 2026-08-28**:
nessuna delle tre aveva un dato sorgente reale al momento dell'implementazione
— restavano colonne vuote o placeholder. L'intento (derivare quando una fonte
pubblica storicamente, per calibrare la frequenza di controllo) resta valido
e descritto in [04-fonti-ingestione.md §4.7](04-fonti-ingestione.md#47-fonti-dormienti--fonti-inutili),
ma va reimplementato da capo il giorno in cui `Archivio` avrà abbastanza
storico per calcolarle davvero.

⚠️ **`vuoto` non è un errore.** Una fonte che risponde correttamente e non contiene
eventi è nello stato normale per gran parte dell'anno: alimenta `dormiente`, non
`primo_errore`. Confondere i due è l'errore che porta a spegnere proprio le fonti
delle sagre. Vedi [04](04-fonti-ingestione.md#47-fonti-dormienti--fonti-inutili).

---

### 3.1.5 `Tipologie` [IN]

| `tipologia` | `sinonimi` | `attiva` |
|---|---|---|
| sagra | sagra, festa patronale, festa paesana, palio, fiera paesana | sì |
| gastronomia | serata gastronomica, cena, street food, pizzata | sì |
| degustazione | degustazione, wine tasting, cantine aperte, birra artigianale | sì |
| concerto | concerto, live, dj set, rassegna musicale, banda | sì |
| teatro | spettacolo teatrale, commedia, cabaret, prosa, musical | sì |
| cinema | cinema all'aperto, arena estiva, cinema sotto le stelle, rassegna cinematografica, proiezione all'aperto | sì |
| mostra | mostra, esposizione, vernissage | sì |
| fiera | fiera, mercatino, mercato dell'antiquariato | sì |
| sportivo | camminata, corsa, torneo, gara | **no** |
| bambini | spettacolo per bambini, laboratorio, ludoteca | **no** |
| altro | | sì |

I `sinonimi` entrano nel prompt di classificazione. `attiva = no` filtra senza
dover ridiscutere la tassonomia: le due categorie restano nella lista perché il
modello deve poterle *riconoscere* per scartarle, invece di forzarle in "altro" e
farle finire nell'elenco.

---

### 3.1.6 `Config` [IN]

| `chiave` | `valore` | Descrizione |
|---|---|---|
| `casa_lat` / `casa_lon` | | Punto di riferimento |
| `soglia_fascia_a/b/c` | **50 / 75 / 100** | Km. Oltre 100 → **fuori perimetro** |
| `max_polling_diretto` | 100 | Tetto delle fonti con visita dedicata. L'unica leva di carico da governare |
| `raggio_max_km` | 100 | Oltre → escluso |
| `orizzonte_espansione_giorni` | 120 | **Solo per le occorrenze generate da `Serie`.** Non limita gli eventi singoli |
| `limite_sanita_anni` | 2 | Date oltre → probabile errore di estrazione, quarantena |
| `giorni_archiviazione` | 2 | Giorni dopo `data_fine` prima di archiviare |
| `serie_decadimento_giorni` | 120 / 400 | Soglie di `da_verificare` e `sospesa` |
| `soglia_confidenza` | 70 | Sotto → quarantena |
| `budget_run_minuti` | 180 | Stop e riprendi al run successivo |
| `budget_feed_minuti` | 45 | Tetto per la lettura dei feed social |
| `budget_llm_giornaliero` | 1200 | Chiamate massime al modello cloud |
| `max_post_social` | 15 | Post recenti per canale, solo nel polling diretto |
| `max_eventi_per_artefatto` | 60 | Tetto anti-allucinazione per artefatto. Configurabile (non un numero fisso nel codice): un cartellone stagionale reale può avere più eventi del default originario di 20 |
| `follow_per_lotto` | 20 | Follow per esecuzione manuale di `run.py follow`. Alzato da 10 su richiesta esplicita, rischio accettato consapevolmente — vedi [CRONACA.md](../CRONACA.md) |
| `follow_max_giornalieri` | 100 | Per piattaforma. Alzato da 40 su richiesta esplicita, stesso rischio accettato |
| `follow_pausa_min` / `_max` | 25 / 70 | Secondi tra un follow e il successivo |
| `follow_intervallo_lotti_min` | 45 | Minuti minimi tra due lotti |
| `follow_circuito_aperto_fino` | — | Data/ora di riapertura dopo un blocco |
| `recupero_run_saltati` | **1** | Al riavvio si esegue **un solo** run di recupero, non uno per giorno perso |

Tutti i numeri magici stanno qui. Nessuno nel codice.

---

### 3.1.7 `Log` [OUT]

`run_id`, `inizio`, `fine`, `durata_min`, `fonti_tentate`, `fonti_ok`, `fonti_errore`,
`artefatti`, `chiamate_llm`, `eventi_nuovi`, `eventi_aggiornati`, `in_quarantena`,
`archiviati`, `note`.

Una riga per run. Il grafico di `durata_min` e `chiamate_llm` nel tempo ti avvisa
prima di sbattere contro i limiti.

---

## 3.2 Schema SQLite locale

Schema reale (`eventi/src/store.py`, `SCHEMA_SQL`), non un'approssimazione:

```sql
schema_version(version)

comuni(istat PK, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo)

sources(source_id PK, config_json, tier, endpoint, last_run,
        last_hash, consecutive_errors, stats_json,
        piattaforma, eventi_totali, eventi_utili,
        primo_errore, ultimo_errore, stato, categoria, polling_diretto)

fingerprint_comuni(istat PK, comune, url, piattaforma, indizi,
                    http_status, errore, fingerprinted_at)
-- censimento di TUTTI i comuni per famiglia CMS, anche senza una fonte
-- configurata — distinta da `sources`

artifacts(artifact_id PK, source_id, url, fetched_at, kind,
          text, context_date, raw_hash, image_paths_json,
          processed_at)

image_cache(phash PK, first_seen, extraction_json, model_used, cost_tokens)
-- il risparmio più grande: la stessa locandina gira su decine di canali

extractions(extraction_id PK, artifact_id, model, prompt_version,
            prompt_utente, raw_output, parsed_json, confidence, created_at)
-- conservare l'output grezzo permette di rilanciare la normalizzazione
-- senza ripagare l'LLM quando cambi le regole

series(serie_id PK, titolo, tipologia, comune, luogo, rrule,
       regola_leggibile, valida_dal, valida_al, eccezioni,
       ultima_conferma, stato, fonti, bloccata)

events(event_id PK, dedup_key, titolo, descrizione, tipologia,
       data_inizio, ora_inizio, data_fine, ora_fine, serie_id, occorrenza,
       comune, luogo, km, minuti, prezzo, organizzatore, url, url_immagine,
       url_approfondimento, confidenza, dettaglio_confidenza, campi_incerti,
       note_estrazione, data_post, ora_post, stato, note,
       primo_visto, ultimo_visto, bloccato, soppressa,
       manual_overrides_json, archiviato)

event_sources(event_id, source_id, url, seen_at)   -- PK composita

runs(run_id PK, tipo, inizio, fine, durata_min, fonti_tentate, fonti_ok,
     fonti_errore, artefatti, chiamate_llm, eventi_nuovi,
     eventi_aggiornati, in_quarantena, archiviati, note)

coda_follow(source_id, piattaforma, handle, url, soggetto, comune,
            fascia, categoria, stato, tentativi, data_follow, note)
            -- PK (source_id, piattaforma)

coda_follow_log(log_id PK, source_id, piattaforma, esito, data_follow)

app_state(chiave PK, valore)
-- stato minuto (es. ultimo post letto per change detection nel feed social)
```

⚠️ Nomi colonna: `bloccato`/`primo_visto`/`ultimo_visto` (non
`locked`/`first_seen`/`last_seen` come in una versione precedente di questo
documento). `resa_annuale`, `finestra_attenzione` e `regime` **non esistono
come colonne SQLite** — sono descritte più sotto (§3.1.4) come colonne del
foglio Google Sheet `Fonti`; non risultano implementate nemmeno lì (rimosse
dal foglio pubblicato il 2026-08-28, nessuna aveva un dato sorgente reale).
Se servono in futuro, vanno progettate da capo con una fonte dati reale
individuata prima di scrivere lo schema.

**Nota su `extractions`:** conservare l'output grezzo dell'LLM è ciò che permette di
riprocessare tutto a costo zero quando cambi la tassonomia, aggiusti la
normalizzazione delle date o correggi il matching dei comuni. Senza questo,
ogni modifica alle regole richiede di riscaricare e ri-analizzare tutto.

## 3.3 Identità dell'evento

Serve una chiave che sopravviva a piccole variazioni di titolo tra una fonte e l'altra.

```
dedup_key = sha1(
    slug(titolo_normalizzato)[:20]   # minuscolo, senza accenti/stopword/emoji
  + "|" + data_inizio                # ISO
  + "|" + comune_normalizzato
)
```

`event_id` = `dedup_key` troncato a 12 caratteri.

**Limite noto e accettato:** se due fonti scrivono *"Sagra della Rana"* e
*"53ª Sagra della Rana - Vimercate"*, la chiave differisce. Per questo la chiave
esatta è solo il **primo** livello: il secondo è il matching fuzzy descritto in
[07](07-normalizzazione-geo-dedup.md).

**Ricorrenze annuali:** la data nella chiave le distingue automaticamente. In
`Archivio` restano gli anni precedenti — utile perché la sagra dell'anno scorso
predice quella di quest'anno e permette di sollecitare la fonte al momento giusto.
