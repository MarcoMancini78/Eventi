# 10 — Roadmap

> **Superata nella pratica da [15-guida-implementazione.md](15-guida-implementazione.md)**:
> il progetto reale ha seguito le tappe M0-M11 di quel documento, non le Fasi
> 0-6 descritte qui — le due numerazioni non sono mai state riconciliate
> esplicitamente. Questo documento resta valido come intento originario
> (l'ordine di priorità e il principio "ogni fase produce qualcosa di
> utilizzabile"), ma per l'ordine di lavoro effettivo usa 15. Per lo stato
> attuale vedi [STATO-PROGETTO.md](../STATO-PROGETTO.md).

Il principio è: **ogni fase deve produrre qualcosa di utilizzabile**, anche se
parziale. Non esiste una fase "infrastruttura" che non produce eventi.

---

## Fase 0 — Validazione empirica (1-2 settimane)

> ⚠️ **Da avviare oggi, in parallelo a tutto:** la creazione dell'account social
> dedicato ([14](14-account-social.md)). Fra riscaldamento e popolamento servono
> **6-10 settimane di calendario** che non si possono comprimere. È l'unica attività
> del progetto con un lead time irriducibile: se parte solo alla Fase 4, la Fase 4
> aspetta due mesi.

**Non si scrive il sistema. Si misura.** Questa fase esiste perché il primo tentativo
è fallito, e ripartire senza sapere *perché* garantisce di rifallire.

### Attività

**0.1 Perimetro e fasce (mezza giornata)**
Scarica l'anagrafe comunale, calcola le distanze in batch, assegna le fasce con le
soglie 20 / 40 / 70 km. **Conta quanti comuni cadono in A, B, C, D.** Se la fascia A
supera i ~120 comuni, la soglia va stretta (D13 in [11](11-rischi-decisioni.md#115b-decisioni-ancora-aperte)).

**0.1a Import e validazione dell'elenco fonti esistente (mezza giornata)**
Importa l'elenco già disponibile, incrocialo con `Perimetro`, e verifica in batch
quali URL e handle rispondono ancora. **Misura: quanti comuni di fascia A e B sono
scoperti?** È la sola lista di lavoro manuale che ti serve.

**0.1b Ricerca degli aggregatori (1 giornata) — la più redditizia**
Cerca portali regionali, dati aperti e circuiti che coprano il tuo perimetro.
**Misura: quanti comuni copre il miglior aggregatore trovato?** Se un solo endpoint
copre 300 comuni, hai già risolto più della metà del problema.

**0.1c Fingerprinting dei siti comunali (mezza giornata, batch)**
Scarica le homepage dei comuni di fascia A/B e classificale per piattaforma.
**Misura: quante famiglie coprono il 70% dei comuni?** Determina quanti adattatori
di famiglia servono ([12](12-scala-e-copertura.md#125-l3--adattatori-per-famiglia-di-piattaforma)).

**0.2 Sonda manuale su 15 fonti (mezza giornata)**
Su un campione di 15 siti comunali di famiglie diverse, guarda il sorgente e cerca:
- link a `.ics` o a feed RSS
- `<script type="application/ld+json">` con `"@type":"Event"`
- una sitemap con URL di eventi

Registra: **quante fonti su 15 sono T0?** Questo numero determina l'intera fattibilità.

**0.3 Test dell'inversione del feed (1 giornata) — verifica l'ipotesi centrale**

Crea l'account dedicato, segui **30-40 soggetti reali** di fascia A su Facebook e
Instagram, aspetta qualche giorno e verifica:

- La vista cronologica è disponibile e utilizzabile su entrambe le piattaforme?
- Il feed è leggibile in modo programmatico, e con quale sforzo?
- **Quanti dei post pubblicati dai 30 soggetti compaiono davvero nel feed?**
  Confronta a mano il feed con i profili. È il numero che decide se L1 funziona.
- Quanto testo utile c'è nelle caption rispetto alle sole immagini?

Se il tasso di comparsa nel feed è sotto il 60%, l'inversione non basta e va
integrata da un polling più esteso sulla fascia A — con conseguente riduzione delle
fasce B e C. **Registra il verdetto in modo esplicito.**

**0.4 Test di estrazione su locandine reali (mezza giornata)**
Salva 20 locandine vere della tua zona. Passale a mano a un modello multimodale con
il prompt di [06](06-estrazione-llm.md#64-prompt-per-locandine-vlm). Valuta a mano:
titolo, data, comune, tipologia.

**Questo è il test più importante di tutti.** Se l'accuratezza sulla data è sotto il
70%, il pilastro centrale del progetto non regge e va ripensato prima di costruire.

**0.5 Test del pre-filtro deterministico (mezza giornata)**
Senza GPU il pre-filtro è l'unica difesa del budget di quota. Su 100 post reali,
misura quanti ne scarterebbero le regole di
[12.10](12-scala-e-copertura.md#il-pre-filtro-deterministico-diventa-il-componente-critico)
e — soprattutto — **quanti eventi veri scarterebbero per errore**. Serve alta
sensibilità: un falso negativo è un evento perso per sempre, un falso positivo costa
solo una chiamata.

**0.6 Misura reale della quota (1 ora)**
Verifica sulla console del provider la quota effettivamente associata al tuo progetto
e confrontala con la stima di ~285 chiamate/giorno (~850 nei picchi estivi).

### Criteri di uscita

| Domanda | Soglia per procedere come previsto |
|---|---|
| Comuni in fascia A | ≤ 120 |
| Copertura del miglior aggregatore | ≥ 200 comuni |
| Famiglie di piattaforma per il 70% dei comuni | ≤ 12 |
| Tasso di comparsa dei post nel feed | ≥ 60% |
| Accuratezza VLM sulla data | ≥ 70% |
| Accuratezza VLM sul comune | ≥ 80% |
| Richiamo del pre-filtro deterministico | ≥ 95% (pochi eventi veri scartati) |
| Riduzione operata dal pre-filtro | ≥ 50% degli artefatti |

**Se i criteri non sono soddisfatti:** non procedere ampliando lo scope. Riduci il
perimetro, punta sui portali aggregatori e sulle newsletter, e accetta una copertura
minore. Un sistema che copre il 50% degli eventi e funziona vale infinitamente più di
uno che punta al 95% e si rompe ogni settimana.

---

## Fase 0.5 — Import del perimetro e nuova discovery (1 settimana)

Del workbook esistente si tiene **solo il foglio `Perimetro`**; le fonti si rifanno.

- Import di `Perimetro`, con conversione dei decimali a virgola (`"5,5"`),
  filtro a 100 km e derivazione della fascia
- Estrazione dei **nomi** dei soggetti dal workbook (comuni, Pro Loco, feste, teatri)
  come punto di partenza — non i link
- Nuova discovery con un client non bloccato, evitando gli errori catalogati in
  [13.2](13-audit-fonti.md#132-tassonomia-dei-difetti-riscontrati):
  filtro dei widget di condivisione, normalizzazione dei deep link, nessun match per
  sola somiglianza del nome
- **Controllo di coerenza di entità** attivo fin dall'inizio: se l'handle contiene il
  nome di un comune diverso da quello assegnato → quarantena, mai accettazione
  automatica ([13.4](13-audit-fonti.md#134-regole-di-bonifica))
- Fingerprinting delle piattaforme e test sitemap
- Verifica prioritaria di **PiemonteItalia** e **VisitLMR**: se espongono dati
  strutturati, metà del progetto è già fatto
- Selezione iniziale delle ~100 fonti in `polling_diretto` (poli + feste storiche +
  aggregatori)

---

## Fase 1 — MVP deterministico + aggregatori (2-3 settimane)

**Obiettivo: eventi veri nel foglio, senza LLM.**

- Perimetro completo con fasce (20/40/70) e distanze batch
- **Import e validazione dell'elenco fonti esistente** ([12](12-scala-e-copertura.md#128-import-e-arricchimento-dellelenco-fonti))
- Struttura degli spreadsheet (tutti i fogli di [03](03-modello-dati.md)), incluso `Serie` e `Stato`
- SQLite + `store.py`
- Lettura configurazione dal foglio
- **Adattatori per i 3-5 migliori aggregatori e dataset aperti** — massima copertura
  per unità di sforzo
- Adattatori `ical`, `rss`, `jsonld` — solo T0
- **Espansore delle serie ricorrenti** (RRULE → occorrenze), con `soppressa` e
  `bloccato` rispettati ([07](07-normalizzazione-geo-dedup.md#79-ricorrenze-espansione-in-occorrenze))
- Vista principale limitata e ordinamento per rilevanza
- Normalizzazione date e comuni, JOIN con `Perimetro`
- Deduplica di livello 1 (chiave esatta)
- Publisher su Sheets, archiviazione degli eventi conclusi
- Esecuzione manuale da riga di comando

**Risultato:** un elenco reale, magari di soli 20-30 eventi, ma corretto e affidabile.
Da questo momento il sistema ha già un valore.

---

## Fase 2 — Estrazione da testo (1-2 settimane)

- Client LLM con astrazione del fornitore
- **Adattatori per le 5-8 famiglie di piattaforma più diffuse** — è qui che si copre
  la maggior parte dei 1.000 siti comunali
- Adattatore `html` generico con `trafilatura` per la coda lunga
- Prompt testuale v1 + validazione dello schema
- Sistema di confidenza e routing in `Quarantena`
- Deduplica di livello 3 (fuzzy)
- Contatore di quota e gestione del 429

**Risultato:** copertura dei siti comunali e dei portali. Probabilmente il salto di
copertura più grande dell'intero progetto.

---

## Fase 3 — Canali push (1 settimana)

Volutamente **prima** dei social, perché costa meno e rende di più.

- Adattatore `email` (IMAP) + iscrizione manuale alle newsletter
- Adattatore `telegram`
- Estrazione da immagini allegate alle email (già usa il VLM)
- Adattatore `telegram` per i canali dei soggetti

**Risultato:** copertura di Pro Loco e comuni senza toccare i social.

---

## Fase 4 — Locandine e feed social (3-4 settimane)

La fase più rischiosa. La **creazione degli account va però fatta subito**, in
parallelo alla Fase 1: fra riscaldamento e popolamento servono 6-10 settimane di
calendario che non si possono comprimere. Vedi la sequenza in
[15.2](15-guida-implementazione.md#152-ordine-di-lavoro-in-breve).

- Cache pHash + pre-filtro grafico (**obbligatori**, non ottimizzazioni)
- Prompt VLM + estrazione da immagini
- Priorità della quota per fascia ([12.10](12-scala-e-copertura.md#ordine-di-priorità-della-quota))
- Adattatore `feed` per la lettura cronologica di FB e IG
- Attribuzione post → `handle` → `source_id` → comune
- Change detection sull'ultimo post visto
- Polling di riserva sulla sola fascia A
- Budget di tempo e degradazione ([05](05-social-locandine.md#57-piano-di-degradazione))

**Risultato:** copertura degli eventi esclusivi dei social, Instagram incluso.

---

## Fase 5 — Operatività (1 settimana)

- Scheduling con recupero **coalescente** delle esecuzioni saltate (un run solo)
- Priorità dinamica della coda + budget di tempo
- Foglio `Stato` con semafori e formattazione condizionale
- Backup automatico del foglio
- Script di manutenzione mensile

**Risultato:** il sistema gira da solo e ti mostra a colpo d'occhio se si è rotto.

---

## Fase 6 — Affinamento (continuo)

- Esempi few-shot dalle tue correzioni
- Prober automatico e ri-discovery trimestrale
- Dizionario dei luoghi in crescita
- Modulazione stagionale delle frequenze
- Potatura delle fonti a resa nulla
- Eventuale modello locale per il pre-filtro

---

## Ordine di priorità se il tempo è poco

Se dovessi fermarti a metà, questo è l'ordine di valore decrescente:

1. **Aggregatori e dati aperti** (dentro Fase 1) — il miglior rapporto copertura/sforzo
   dell'intero progetto a questa scala
2. **Fase 1** — T0 + perimetro + bootstrap fonti
3. **Fase 2** — adattatori di famiglia + LLM. Il grande salto sui 1.000 comuni
4. **Fase 5** — operatività. Senza questa il sistema muore silenziosamente
5. **Fase 4** — feed social. Il più costoso e il meno affidabile
6. **Fase 3** — newsletter e Telegram. Ottimo rapporto costo/resa, ma su questo perimetro
   copre una frazione minore rispetto agli aggregatori

I social restano **penultimi**, con l'unica eccezione del popolamento dell'account
dedicato, che va avviato subito perché ha tempi di calendario lunghi. È l'inverso
dell'ordine istintivo — ed è probabilmente il motivo per cui il primo tentativo si è
arenato lì.
