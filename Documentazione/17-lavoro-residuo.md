# 17 — Lavoro residuo: linea guida per i prossimi sviluppi

**Stato:** audit comparativo tra documentazione (00-16) e codice reale, eseguito
2026-09-01. Non un elenco di bug — il sistema funziona ed è in produzione (pipeline,
Sheets, webapp mappa tutti operativi) — ma un inventario di ciò che i documenti di
progettazione promettono e il codice non realizza ancora, per non perderne traccia.
**17.1.1 (L3) già realizzato** lo stesso giorno dell'audit — vedi in fondo alla
sezione per l'esito reale.

> ⚠️ **Questo documento è un'istantanea, non aggiornata da allora** (2026-09-01),
> mentre il codice ha continuato a evolvere (webapp elenco, nuovi comandi,
> fix vari — vedi [STATO-PROGETTO.md](../STATO-PROGETTO.md) e `git log`).
> **Andrebbe ripetuto periodicamente**, non trattato come definitivo: il modo
> più semplice per evitare che la documentazione si disallinei di nuovo dal
> codice è rifare questo confronto ogni volta che si sospetta uno scarto,
> non aspettare che diventi grande come è successo qui.

Ogni voce riporta: cosa dice la documentazione, cosa esiste davvero nel codice
(verificato, non dedotto dai commenti), e una stima di impatto/sforzo.

---

## 17.1 Gap ad alto impatto

### 17.1.1 L3 — Adattatori per famiglia di piattaforma (✅ realizzato 2026-09-01)

**Cosa promette la doc** ([12.5](12-scala-e-copertura.md#125-l3--adattatori-per-famiglia-di-piattaforma)):
è definita **"l'unica parte del progetto dove scrivere codice specifico conviene"**,
perché un adattatore per famiglia di CMS comunale si applica non a un comune ma a
centinaia contemporaneamente (moltiplicatore ×100). Procedura in 4 passi:
fingerprinting batch → classifica per frequenza → un adattatore per famiglia →
il resto resta T1 generico.

**Cosa esiste davvero:** il fingerprinting (passo 1-2) è **fatto e i dati sono
buoni** — `src/fingerprint.py`, comando `run.py fingerprint-comuni`, tabella
`fingerprint_comuni` in SQLite. Risultato reale sul perimetro attuale:

| Famiglia | Comuni | % del perimetro |
|---|---|---|
| `pa_design_system` | 436 | ~64% |
| `sconosciuta` | 139 | ~20% |
| `wordpress` | 91 | ~13% |
| `drupal` | 6 | ~1% |

Il passo 3 (l'adattatore vero e proprio) **non esiste**: `src/adapters/platform/`
è una cartella vuota, `pipeline.py` registra solo `T0_ical`, `T0_jsonld`, `T0_rss`,
`T1_html` — nessun adattatore per famiglia. Il commento nello stesso
`fingerprint.py` lo ammette esplicitamente: *"la scrittura di un adattatore per
famiglia resta il passo successivo di M8"*.

**Perché conviene farlo ora, non in astratto:** `pa_design_system` da solo copre
436 comuni su 683 (64%). Ispezionando dal vivo due siti reali di questa famiglia
(Calosso, Santo Stefano Belbo — comuni diversi, province diverse) si trova la
**stessa identica struttura HTML**: card con classe `card-wrapper`, categoria
dell'evento in un link `?idCat=N`, data nel formato `GG/MM/AAAA - GG/MM/AAAA`,
link al dettaglio `Dettaglionews?IDNews=N`, titolo in `.card-title`, sintesi in
`.text-paragraph-card`. È il template del Design System della PA italiana
(AGID/designers.italia.it), adottato in modo pressoché identico su moltissimi
piccoli comuni piemontesi.

**Stima di sforzo:** un adattatore mirato a questo singolo pattern (parsing con
selettori CSS invece del generico `trafilatura`+LLM, estrazione diretta di
data/titolo/categoria/link senza passare dall'estrattore per i campi già
strutturati) potrebbe convertire ~400 fonti da T1 (una chiamata LLM per pagina) a
T0-simile (zero o quasi chiamate LLM, solo per la descrizione se serve arricchirla).
È il singolo intervento con il rapporto costo/beneficio più alto rimasto nel
progetto: tocca il 64% del perimetro con un solo adattatore.

**Esito reale (2026-09-01):** il campione di verifica su 6 comuni ha rivelato che
`pa_design_system` non è una famiglia sola ma **due varianti distinte**, entrambe
risolte:

1. **Variante ComWeb/ePublic** (`meta generator="ComWeb - www.epublic.it"`, URL
   `.../it-it/vivere-il-comune/eventi`) — espone già JSON-LD `schema.org/Event`
   valido, l'adattatore `adapters/jsonld.py` esisteva già ma **crashava** su un
   caso reale (`location.address` come lista invece di dict — corretto). Nessun
   nuovo adattatore necessario: solo il bug fix, poi promozione di tier.
   Comando riusabile `run.py promuovi-jsonld --filtro-url "vivere-il-comune/eventi"`
   (verifica dal vivo prima di promuovere, non un pattern URL indovinato).
   **66 fonti promosse da T1_html a T0_jsonld**, 0 errori su 69 verificate.
2. **Variante legacy** (URL `.../Eventi`, come Calosso) — nessun JSON-LD, ma
   struttura HTML identica su comuni di 5 province diverse (`.card-wrapper`,
   `.card-title`, data in `.category-top .data`, link dettaglio
   `Dettaglionews?IDNews=N`). Nuovo `src/adapters/pa_design_system.py`
   (`T0_pa_design_system`, XPath nativo di lxml, nessuna nuova dipendenza).
   Comando riusabile `run.py promuovi-pa-design-system` (verifica il markup
   `.card-wrapper` prima di promuovere, non solo il pattern URL).
   **321 fonti promosse a T0_pa_design_system**, 309/318 al primo giro (1
   errore reale, resto "markup assente" — corretto, sono siti Drupal/altro
   erroneamente inclusi solo perché condividono il pattern URL `.../Eventi`).

**Totale: 387 fonti (66 + 321), il 57% delle fonti comunali del perimetro,
convertite da T1_html (una chiamata LLM per pagina) a T0 (zero chiamate).**
Entrambi i comandi restano disponibili per ripromuovere nuove fonti in futuro,
senza ripetere il lavoro a mano. 11 nuovi test (adattatore + verifica batch +
bug fix jsonld), tutti collaudati anche dal vivo su fonti reali del perimetro
— incluso un giro end-to-end completo su comune-vigliano-d'asti (5 artefatti
→ 5 eventi pubblicati, 0 chiamate LLM, confidenza 85 da bypass estrattore).

**Nota operativa:** il primo giro del batch di 318 fonti è durato
inaspettatamente ~80 minuti — non un bug, ma il caso peggiore reale di
centinaia di piccoli siti comunali con timeout httpx di 15s ciascuno su
quelli lenti/irraggiungibili. Il comando è stato riscritto con progresso
riga-per-riga e commit incrementale per-fonte (invece di un solo commit a
fine batch), così un'interruzione a metà non perde il lavoro già fatto.

---

### 17.1.2 Priorità dinamica non alimentata da dati reali

**Cosa promette la doc** ([12.9](12-scala-e-copertura.md#129-rotazione-e-capacità),
decisione D19 in [11](11-rischi-decisioni.md)): la coda a priorità dinamica
(`scheduling.py`, formula esistente e collegata) dovrebbe pesare anche
`finestra_attenzione` (periodo dell'anno in cui una fonte storicamente pubblica) e
`resa_annuale`/`regime` (massivo vs curato).

**Cosa esiste davvero:** le colonne `finestra_attenzione`, `resa_annuale`, `regime`
sono state **rimosse dal foglio Fonti pubblicato** il 2026-08-28 — il commento in
`src/publisher.py` lo dice esplicitamente: *"nessuna aveva un dato sorgente
reale"*. La formula in `scheduling.py` gira, ma su un sottoinsieme dei fattori
previsti (fascia, resa storica misurata, giorni dall'ultimo run, penalità errori) —
manca la componente stagionale.

**Perché è un gap reale, non solo estetico:** la stagionalità è il punto centrale
del progetto (una Pro Loco silenziosa 11 mesi produce l'evento più importante a
luglio) — la sua assenza dalla formula di priorità significa che oggi il sistema
non "sa" quando una fonte dormiente sta per svegliarsi.

**Prossimo passo concreto:** i dati per calcolare `finestra_attenzione` esistono
già in `Archivio` (eventi passati con data e fonte) — è un calcolo derivabile
offline (mese/settimana ricorrente in cui una fonte ha eventi negli anni passati),
non un nuovo dato da raccogliere. Il lavoro è: una funzione che legge `Archivio`
raggruppato per `source_id`, calcola la distribuzione mensile storica, e la scrive
in una nuova colonna calcolata (non più manuale) usata da `scheduling.py`.

---

### 17.1.3 Newsletter come fonte automatica (mai iniziato)

**Cosa promette la doc** (decisione D21): rilevazione automatica delle newsletter
in fase di discovery.

**Cosa esiste davvero:** il foglio `Newsletter` esiste nello schema Sheets, ma
nessun codice lo popola — resta un foglio vuoto da compilare a mano, il che
contraddice la parola "automatica" della decisione originale.

**Prossimo passo concreto:** non prioritario rispetto a 17.1.1/17.1.2 — richiede
prima di decidere *come* rilevare "questo sito ha una newsletter" (form di
iscrizione nel footer? link a Mailchimp/altri provider?) prima di scrivere codice.
Va trattato come una nuova mini-decisione di design, non solo un'implementazione.

---

## 17.2 Gap a impatto medio

### 17.2.1 L4 — Aggregatori regionali, solo 1 di 5-6 previsti

**Cosa promette la doc** ([12.6](12-scala-e-copertura.md#126-l4--aggregatori-e-dati-aperti-come-primo-strato)):
PiemonteItalia, VisitLMR, VisitPiemonte, Sagr.it, GuidaTorino come "primo strato"
ad alto rendimento.

**Cosa esiste davvero:** solo `src/adapters/aggregatore_regionale.py` per VisitLMR,
e con esito degradato rispetto all'ipotesi — PiemonteItalia risultò bloccare lo
scraping (escluso), VisitLMR richiede Playwright (T1 costoso, non il T0 sperato,
nessuna API/dati aperti trovati). Gli altri portali elencati in
[13.5](13-audit-fonti.md) non sono mai stati verificati.

**Prossimo passo concreto:** una verifica rapida (Fase-0-style, poche ore) su
VisitPiemonte/Sagr.it/GuidaTorino per lo stesso controllo già fatto su
PiemonteItalia/VisitLMR — feed RSS/iCal/JSON-LD disponibili? Scraping bloccato?
Prima di investire in un adattatore, sapere se vale la pena.

### 17.2.2 Backup automatico del foglio Sheets (✅ realizzato 2026-09-02)

**Cosa promette la doc** ([11.1](11-rischi-decisioni.md)): backup settimanale
automatico come mitigazione al rischio "foglio corrotto da un bug di publish".

**Cosa esiste ora:** nuovo `src/drive_backup.py` — copia lo spreadsheet
principale in una cartella Drive dedicata ("Eventi Locali — Backup", creata al
primo utilizzo e riusata ai successivi), con nome `Backup AAAA-MM-GG`. Nessuna
nuova dipendenza: la ricerca/creazione della cartella usa l'API REST Drive
direttamente con `httpx` (stesso token OAuth già caricato da `sheets_client`,
trovato ispezionando `gspread.Client` dal vivo — non documentato pubblicamente
che le credenziali vivono in `client.http_client.auth`, non su `client`
direttamente), la copia usa `gspread.Client.copy` già disponibile. Nessuna
cancellazione automatica delle copie vecchie (deciso con l'utente): l'operatore
ripulisce a mano quando vuole.

Comando `run.py backup-sheets`, e nuovo `backup_sheets_schedulato.bat` da
schedulare settimanalmente in Utilità di pianificazione Windows (stesso
pattern di `schedulazione_follow.bat`/`ricerca_eventi_automatica.bat`) —
🐛 bug trovato nel collaudo: il file scritto con un em-dash tipografico
(carattere non-ASCII) veniva salvato come UTF-8, che `cmd.exe` non
interpreta in modo affidabile per i file `.bat` senza BOM, e mandava in
crash lo script ("M" non riconosciuto come comando). Corretto riscrivendo
in puro ASCII, come tutti gli altri `.bat` del progetto — nessuno di
quelli esistenti contiene caratteri non-ASCII, non a caso.

Collaudato dal vivo due volte (comando diretto + tramite il `.bat`): entrambi i
backup creati con successo, cartella riusata correttamente al secondo giro,
14 fogli e dati reali presenti nella copia (verificato: 104 righe nel foglio
Eventi). 3 nuovi test con mock httpx/gspread, suite 307/307.

### 17.2.3 Fogli Feste/CompagnieTeatrali dedicati (assorbiti nel generico)

**Cosa promette la doc** ([13.5](13-audit-fonti.md)): fogli tematici distinti per
seguire fonti ad alta resa come feste patronali e compagnie teatrali itineranti.

**Cosa esiste davvero:** solo una categoria `festa` dentro lo store generico di
`sources`/`events` — nessun foglio o flusso operativo separato che le renda
tracciabili come gruppo a sé.

**Valutazione:** probabilmente non vale la pena costruire fogli dedicati oggi — la
categoria `festa` già esiste in `CoperturaAltreEntita` (16) ed è filtrabile lì.
Da riconsiderare solo se il numero di feste/compagnie censite cresce abbastanza da
giustificare una vista propria.

---

## 17.3 Gap a basso impatto / esplicitamente non prioritari

Questi sono marcati nella documentazione stessa come "fase 6, affinamento
continuo" o "opzionale" — non sono errori, sono lavoro futuro non ancora iniziato
perché legittimamente rimandato:

- **L5 — raccolta per hashtag/geotag** ([12.7](12-scala-e-copertura.md#127-l5--raccolta-per-query-invece-che-per-account)):
  "complementare" nella doc stessa, zero riscontro nel codice.
- **Few-shot dalle correzioni utente** (roadmap Fase 6): nessun meccanismo che
  impari dalle correzioni manuali su Sheets per migliorare i prompt futuri.
- **Ri-discovery trimestrale schedulata**: il comando `run.py prober` esiste ed è
  manuale — nessuna schedulazione automatica periodica.
- **Potatura automatica delle fonti a resa nulla**: nessuna logica che disattivi
  da sola una fonte mai produttiva (resta una decisione manuale).
- **Modello locale per pre-filtro su CPU** (D11): esplicitamente scartato per
  mancanza di GPU disponibile — non un gap, una scelta già presa e accettata.
- **Colonne di tracciamento verifica bonifica fonti** (`entita_confermata`,
  `metodo_verifica`, `data_verifica` — [13.6](13-audit-fonti.md) punto 6): non
  trovate in nessun file, ma il loro impatto pratico è limitato finché la
  bonifica fonti resta un'attività occasionale e non un processo automatico.

---

## 17.4 Ordine consigliato se si riprende questo lavoro

1. ~~**[17.1.1] Adattatore `pa_design_system`**~~ — ✅ fatto 2026-09-01, 387
   fonti (57% dei comuni) promosse da T1 a T0.
2. ~~**[17.2.2] Backup automatico Sheets**~~ — ✅ fatto 2026-09-02.
   Resta solo un passo manuale per l'utente: schedulare
   `backup_sheets_schedulato.bat` una volta a settimana in Utilità di
   pianificazione Windows (nessun trigger automatico creato da qui).
3. **[17.1.2] Finestra di attenzione calcolata da Archivio** — dato già
   disponibile, "solo" da aggregare e collegare a `scheduling.py`.
4. **[17.2.1] Verifica rapida altri aggregatori regionali** — poche ore per
   sapere se vale la pena continuare su questa leva.
5. Il resto (17.1.3, 17.2.3, 17.3) solo se emerge un bisogno concreto — evitare
   di costruire in anticipo su un'esigenza ancora ipotetica, coerente con lo
   stile di sviluppo già seguito nel resto del progetto.
