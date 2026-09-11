# 08 — Orchestrazione e operatività

> Elenco completo dei comandi `run.py` disponibili oggi:
> [02-architettura.md §2.3](02-architettura.md#23-orchestrazione-runpy).
> Questo documento tratta la logica di scheduling/budget/monitoraggio, non
> l'elenco dei comandi.

## 8.1 Il problema del tempo

Il primo tentativo era *"molto lento"*. La causa non è la velocità del codice: è
l'assenza di un **budget** e di una **coda prioritizzata**. Un sistema che tenta di
fare tutto ogni volta impiega tempo illimitato e produce risultati imprevedibili.

Principio: **il run ha una durata massima fissa; ciò che non entra slitta.**
Meglio 40 fonti buone ogni giorno che 200 fonti mediocri una volta a settimana.

## 8.2 Tipi di run

Il concetto di "run completo" non esiste più: a ~5.000 fonti nessun run le tocca
tutte. Vedi [12](12-scala-e-copertura.md#129-rotazione-e-capacità).

| Run | Quando | Cosa fa | Durata target |
|---|---|---|---|
| **Feed** | ogni giorno | Lettura dei feed social (FB + IG) dell'account dedicato | < 45 min |
| **Leggero** | ogni giorno | Aggregatori, dati aperti, T0 in rotazione, newsletter, Telegram | < 30 min |
| **Principale** | ogni notte | Feed + Leggero + T1 in rotazione + polling social fascia A | < 180 min |
| **Manutenzione** | 1×/mese | Discovery, fingerprinting, ricalcolo rese, pulizia cache, KPI | < 60 min |
| **Bootstrap** | 1-2×/anno | Rigenerazione dell'elenco fonti | ore |
| **Pubblicazione** | dopo ogni run | Scrittura Sheet, archiviazione | < 5 min |

Il run **Feed** è quello che conta davvero: in una sessione copre ~1.400 fonti social
e cattura le novità in giornata. Il run Leggero copre con gli aggregatori centinaia
di comuni al costo di poche decine di richieste.

## 8.3 Costruzione della coda

A ogni run l'orchestratore ordina le fonti per **priorità dinamica**:

```
punteggio = (5 − fascia) × 25              # A=100, B=75, C=50, D=25 — dominante
          + resa_storica × 20              # eventi_utili / minuti_spesi
          + giorni_da_ultimo_run × 3
          + bonus_stagionale               # sagre in estate, teatro in inverno
          − penalita_errori                # 5 × errori_consecutivi
          − costo_stimato_minuti
```

La **fascia domina tutto il resto**: è la disciplina che tiene il sistema dentro il
budget. Una fonte di fascia C con ottima resa può superare una fonte di fascia B
scarsa, ma non una di fascia A.

Poi processa in ordine finché il budget di tempo non si esaurisce. Le fonti non
raggiunte partono in testa alla coda del run successivo (con `giorni_da_ultimo_run`
che cresce, quindi salgono da sole).

**Ordine degli stadi all'interno del run:** prima tutte le fonti economiche
(T0, email, Telegram), poi T1, infine i social. Così se il budget finisce, ciò che si
perde è la parte a resa più incerta.

## 8.4 Isolamento degli errori

Ogni fonte è processata in isolamento: un'eccezione non deve mai fermare il run.

```
per ogni fonte in coda:
    try:
        con timeout(90 secondi):
            artefatti = adattatore.fetch(fonte)
        fonte.primo_errore = null
        fonte.stato = attiva
    except errore:
        log(fonte, errore, tipo)
        se fonte.primo_errore è null:
            fonte.primo_errore = oggi

        giorni_in_errore = oggi − fonte.primo_errore

        secondo il tipo di errore:
            transitorio (timeout, 5xx)  → nessuna azione sotto i 7 giorni
            blocco (403, 429, captcha)  → backoff 7 → 14 → 30 giorni
            permanente (404, DNS)       → se giorni_in_errore ≥ 14:
                                              fonte.stato = rotta
                                              stato rosso nel foglio Stato
        continua con la prossima
```

**Si contano i giorni, non i tentativi.** Una fonte dormiente visitata ogni 3
settimane raggiungerebbe "5 errori consecutivi" dopo quattro mesi: contare i run
produce soglie prive di senso sulle fonti a bassa frequenza.

**`rotta` non è `disattivata`:** la fonte resta nel foglio e viene ritentata una volta
al mese, con riattivazione automatica al primo successo. Tassonomia completa degli
errori in [04](04-fonti-ingestione.md#48-fonti-rotte-qui-la-sospensione-ha-senso).

Il timeout per fonte è essenziale: una singola pagina che non risponde può da sola
mangiare tutto il budget.

**Retry:** solo per errori transitori (timeout, 5xx, rate limit), con backoff
esponenziale e massimo 2 tentativi, **all'interno dello stesso run solo se c'è
budget**. Per 404 e 403 nessun retry: è un problema di configurazione, va guardato
a mano.

## 8.5 Budget della quota LLM

Contatore giornaliero persistente (`budget_llm_giornaliero` in Config), con soglie:

- 70% consumato → sospendi le estrazioni da immagini di fonti a priorità 3
- 85% → solo fonti in `polling_diretto` e fascia A
- 100% → solo T0 deterministico; gli artefatti restano in staging con
  `processed_at = null` e vengono ripresi il giorno dopo

Gli artefatti non processati **non vanno persi**: restano in coda. Questo trasforma
un limite duro in un semplice ritardo.

## 8.6 Idempotenza e ripartenza

Il run scrive stato dopo ogni stadio. Se il PC si spegne a metà:

- Gli artefatti già scaricati hanno `processed_at = null` → riprocessati
- Le estrazioni già fatte sono in `extractions` → non ripagate
- Gli eventi già inseriti hanno `event_id` stabile → aggiornati, non duplicati
- La pubblicazione su Sheet è sempre una scrittura **completa e batch** dello stato
  corrente, mai un append incrementale

Quest'ultimo punto è importante: la pubblicazione idempotente elimina un'intera
categoria di bug (righe doppie, righe orfane) al prezzo di qualche secondo in più.

### 8.6.1 Il limite dell'idempotenza per il feed social

I post letti dal feed social (M10) sono un'eccezione al riprocessamento
automatico: `leggi_feed_reale` scrolla il feed **solo fino all'ultimo post già
visto** (change detection sul `post_id`), poi si ferma — non torna mai indietro
a rileggere i post più vecchi in un giro normale. Se un evento è sbagliato per
un bug che nel frattempo è stato corretto nel codice (es. un fix al prompt di
estrazione, o alla lettura della data di pubblicazione), quell'evento resta
sbagliato per sempre finché non lo si ricorregge esplicitamente — cancellarlo e
rilanciare `feed-social` NON basta.

`run.py correggi-post <event_id> [<event_id> ...]` riapre il permalink diretto
del post e ri-estrae, sostituendo l'evento sbagliato solo se la nuova
estrazione produce un risultato (mai un buco silenzioso se il ri-processo
fallisce). **Solo Instagram**: per Facebook l'URL salvato nell'evento è il link
della pagina dell'autore con parametri di tracking (`__cft__`), non un
permalink al singolo post — non riapribile direttamente. Per Facebook resta
quindi solo la correzione manuale su questo fronte (riaprire e correggere a
mano l'evento specifico).

Due comandi analoghi coprono le altre fonti: `run.py correggi-fonte-html
<source_id> [...]` rilancia una o più fonti T1_html/aggregatore con
l'adattatore aggiornato (stesso principio: un fix al codice non si applica
retroattivamente da solo), e `run.py riprocessa-quarantena` ricorregge tutti
gli eventi in quarantena in un colpo solo, smistando da sé per tipo di fonte
(post social vs HTML) invece di richiedere una lista di ID.

### 8.6.2 Data di pubblicazione dei post Facebook: hover sul tooltip

Il timestamp relativo di un post Facebook ("N min/h/g") non è mai leggibile
come testo (né `innerText` né `textContent`): i caratteri sono deliberatamente
mescolati nel DOM, verificato confrontando l'HTML grezzo con l'output di
Playwright — anti-scraping intenzionale, non un problema di selettore. La data
assoluta è invece leggibile passando il mouse sopra quel link: compare un vero
elemento `[role="tooltip"]` nel DOM con testo pulito, es. "Giovedì 3 settembre
2026 alle ore 15:52" (`_leggi_data_pubblicazione_hover_facebook`,
`feed_social.py`). Nessuna interazione visibile ad altri utenti (14.5b, coerente
col click "Vedi altro" già usato altrove) — solo un movimento del mouse.

Il meccanismo non è affidabile al 100%: nei collaudi dal vivo tra il 40% e il
50% dei post ottiene la data al primo giro reale (il selettore trova sempre il
link giusto — verificato — il limite è di timing: il tooltip a volte non fa in
tempo a comparire). Un secondo tentativo con attesa più lunga recupera parte
dei casi lenti. Isolamento totale: un fallimento ricade sempre sul default
`date.today()` in `client.py`, mai un crash o un blocco del post.

## 8.7 Scheduling sul PC

Il PC è acceso quasi ogni giorno, ma non sempre. Serve un meccanismo che recuperi le
esecuzioni saltate — **coalescendole in una sola**.

> Se il PC resta spento due giorni, all'accensione si esegue **un run solo**, non due.
> Rieseguire un run per ogni giorno perso raddoppierebbe il tempo senza raddoppiare
> l'informazione: le fonti non visitate sono le stesse, e il feed social si legge
> comunque all'indietro fino all'ultimo post già visto.

Questo è esattamente il comportamento dei timer di sistema:

- **Windows:** Utilità di pianificazione, con l'opzione di esecuzione al più presto
  dopo un avvio pianificato mancato. **Non** abilitare l'accodamento di più istanze.
- **Linux/macOS:** systemd timer con `Persistent=true`, che per costruzione esegue
  una sola volta al riavvio indipendentemente da quante occorrenze sono state perse.

Il recupero del ritardo non avviene rieseguendo i run, ma attraverso la coda a
priorità: il termine `giorni_da_ultimo_run` fa risalire da sole le fonti rimaste
indietro, distribuendo il recupero sui run successivi senza sforare il budget.

Due protezioni aggiuntive: un **lock file** che impedisca due esecuzioni sovrapposte,
e un controllo all'avvio del tipo "se l'ultimo run è più vecchio di 24h, esegui subito
un run leggero".

Il run pesante va schedulato di notte; quello leggero può girare in background a
qualunque ora, dato che dura pochi minuti.

## 8.8 Scrittura su Google Sheet

Regole per non incorrere in lentezza e limiti d'uso dell'API:

- **Mai una chiamata per cella o per riga.** Costruisci l'intero contenuto del foglio
  in memoria e scrivilo con un unico aggiornamento di intervallo
- Leggi la configurazione **una volta** a inizio run e mettila in cache in SQLite
- Prima di sovrascrivere `Eventi`, **rileggi** il foglio per raccogliere le tue
  modifiche manuali (`stato`, `note`, `bloccato`) e riportale in SQLite. Solo dopo
  riscrivi. Altrimenti perdi il tuo lavoro
- Backup: prima della scrittura completa, copia il foglio in un tab datato una volta
  a settimana. Un bug che azzera l'elenco è sempre possibile
- Le righe con `bloccato = sì` non vengono mai sovrascritte, solo riposizionate

**Ripartizione su più spreadsheet, obbligatoria a questa scala.** Con 1.000 comuni,
`Perimetro` è già 1.000 righe, `Fonti` alcune migliaia, e gli eventi possono essere
centinaia a settimana. Struttura consigliata:

| Spreadsheet | Contenuto | Perché separato |
|---|---|---|
| **Principale** | `Eventi`, `Quarantena`, `Config`, `Tipologie`, `Log` | Deve restare veloce da aprire, è quello che consulti |
| **Anagrafiche** | `Perimetro`, `Fonti` | Grandi ma statici, si aprono di rado |
| **Esteso** | `Archivio` | Cresce senza limiti |

`Eventi` pubblica oggi tutte le righe attive in un unico foglio (unificato con
`Eventi_estesi` il 2026-09-10, vedi [03-modello-dati.md](03-modello-dati.md#31-struttura-del-google-sheet)).

Non tutto ciò che il sistema conosce deve stare in un foglio: SQLite regge il
dettaglio, i fogli mostrano ciò che serve a te.

## 8.9 Monitoraggio (senza notifiche)

Niente notifiche push: **la diagnostica vive nel foglio**, non nella tua casella.
Resta però necessario che il sistema segnali quando si è rotto — altrimenti continua a
girare a vuoto e te ne accorgi mesi dopo, che è il modo tipico in cui questi progetti
muoiono.

Un foglio `Stato`, poche righe, che leggi quando apri il file per altri motivi:

| Indicatore | Valore | Semaforo |
|---|---|---|
| Ultimo run completato | 21/08 03:14 | 🟢 |
| Durata ultimo run | 164 min | 🟢 |
| Fonti in stato `rotta` | 12 | 🟡 |
| Fonti nuove entrate in `rotta` questa settimana | 3 | 🟡 |
| Eventi nuovi ultimi 7 giorni | 0 | 🔴 |
| Feed social letto con successo | 20/08 | 🟢 |
| Quota LLM consumata ieri | 61% | 🟢 |
| Serie passate in `sospesa` | 1 | 🟡 |
| Fonti in quarantena da revisionare | 23 | 🟡 |

I semafori si fanno con la formattazione condizionale, senza scrivere codice.

**L'indicatore critico è "eventi nuovi ultimi 7 giorni = 0"**: significa che qualcosa
si è rotto a monte, perché su questo perimetro è statisticamente impossibile. È il
solo allarme che conta davvero, e in rosso in cima al foglio è impossibile da non
vedere.

Il foglio `Log` mantiene lo storico per riga di run; `Stato` è solo la fotografia
corrente.

## 8.10 Manutenzione ordinaria

**Ogni settimana (5 min):** svuota la quarantena, marca gli eventi interessanti.

**Ogni mese (20 min):** controlla le fonti in stato `rotta` e capisci se sono
recuperabili; verifica il KPI di copertura sul campione della fascia A; guarda le
fonti che rispondono ma non estraggono più nulla pur avendo prodotto in passato
(sintomo di struttura cambiata).

⚠️ **Non disattivare le fonti per bassa resa.** Il silenzio è la normalità per la
maggior parte delle Pro Loco: modula la frequenza, non elimina la fonte
([04](04-fonti-ingestione.md#47-fonti-dormienti--fonti-inutili)).

**Ogni trimestre:** rilancia la discovery (i siti aggiungono feed nel tempo); rivedi
il perimetro; valuta se aggiungere fonti nuove viste in giro.

Se la manutenzione supera 30 minuti al mese, il sistema ha troppe fonti fragili:
la risposta corretta è **restringere le fasce** — cioè ridurre il perimetro servito —
non aggiungere codice né eliminare le fonti silenziose.
