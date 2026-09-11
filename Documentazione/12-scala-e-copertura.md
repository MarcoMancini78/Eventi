# 12 — Scala: il perimetro reale e le sue fonti

> **Numeri definitivi** (vedi [13](13-audit-fonti.md)): casa a Calosso (AT), perimetro
> **tagliato a 100 km**, ~1.200-1.400 comuni. Fasce A ≤ 50 km (include Alba, Acqui,
> Alessandria), B ≤ 75, C ≤ 100. Le leve descritte qui restano valide; cambia la
> ripartizione del carico, spostata dalla fascia al flag `polling_diretto`.

Questo documento sostituisce le assunzioni di dimensionamento di
[01](01-requisiti.md#16-assunzioni) e ridefinisce la strategia di raccolta.
È il documento più importante del progetto insieme a [05](05-social-locandine.md).

## 12.1 Il conto che cambia tutto

Con ~1.000 comuni nel perimetro, l'inventario realistico delle fonti è:

| Categoria | Stima | Note |
|---|---|---|
| Siti comunali | ~1.000 | Uno per comune |
| Pagine Facebook comunali | ~700 | Non tutti ce l'hanno |
| Profili Instagram comunali | ~400 | Meno diffusi |
| Pro Loco (sito) | ~500 | Molte non hanno sito |
| Pro Loco (Facebook) | ~800 | Il canale principale delle Pro Loco |
| Pro Loco (Instagram) | ~450 | |
| Teatri, cinema, sale civiche | ~400 | |
| Locali, circoli, compagnie | ~500 | |
| Portali aggregatori | ~30 | |
| **Totale** | **~4.800** | |

Ora il costo del polling per fonte, con i tempi realistici:

```
Fonti social (~2.350) × 30 secondi   ≈ 19,5 ore
Fonti web   (~2.400) × 2 secondi     ≈  1,3 ore   (con change detection)
                                     ─────────────
                                       ~21 ore per passaggio completo
```

Il budget triplicato (180 minuti) copre il **14%** di questo. Anche con un ciclo
settimanale servirebbero 3 ore al giorno di sola navigazione social — e Meta
bloccherebbe l'account molto prima.

**Conclusione: il modello "visito ogni fonte" è matematicamente escluso.**
Non è un problema di ottimizzazione, è un problema di modello. Quello che segue è
il modello alternativo.

## 12.2 Le cinque leve

Nessuna da sola basta. Insieme portano il problema dentro il budget.

| Leva | Riduzione | Difficoltà |
|---|---|---|
| L1 — Inversione del feed social | **~20×** sui social | media |
| L2 — Fasce di perimetro | ~3× complessivo | banale |
| L3 — Adattatori per famiglia di piattaforma | ~5× sul web | media |
| L4 — Aggregatori e dati aperti come primo strato | ~2× | bassa |
| L5 — Raccolta per query invece che per account | complementare | media |

---

## 12.3 L1 — Inversione del feed social ⭐

**È la decisione che rende possibile includere Instagram.**

Il modello attuale: per ogni account, apri il profilo, scorri, scarica. 2.350 volte.

Il modello invertito: **un account dedicato segue tutti i 2.350 soggetti. Poi leggi
il tuo feed.** Una sola sessione, uno scroll continuo, e ricevi i post di tutti.

```
PRIMA                                  DOPO
2.350 visite a profili                 1 sessione, 1 feed
2.350 × 30s = 19,5 ore                 30-45 minuti
2.350 pattern di accesso sospetti      1 comportamento da utente normale
```

Il guadagno non è solo di tempo: **è anche di rischio**. Scorrere il proprio feed è
letteralmente ciò che fa un utente normale. Visitare 2.350 profili in sequenza è
letteralmente ciò che fa un bot. La leva che riduce il costo riduce anche la
probabilità di blocco.

### Come costruirlo

**Fase di popolamento (4-8 settimane, una tantum).** Non puoi seguire 2.000 account
in un giorno: è il segnale di automazione più evidente che esista.

- Instagram ha un tetto di circa 7.500 account seguibili, quindi il numero è
  compatibile — ma il ritmo va tenuto basso: **30-50 follow al giorno**, distribuiti,
  con qualche interazione normale in mezzo.
- Facebook: si usa "Segui" sulle Pagine, non l'amicizia. Meno limitato di Instagram
  ma vale lo stesso principio di gradualità.
- Ordine di popolamento: prima la fascia A del perimetro (vedi L2), poi B, poi C.
  Così il sistema è già utile dopo la prima settimana.

Il popolamento può essere **manuale o semiautomatico**: è lavoro noioso ma si fa una
volta sola, e farlo a mano davanti alla TV è più sicuro che automatizzarlo.

### Come leggerlo

- **Instagram:** usa la vista cronologica ("Seguiti" / "Following"), non quella
  algoritmica. Scorri fino a raggiungere l'ultimo post già visto (change detection
  sul post ID) e fermati.
- **Facebook:** usa la scheda **Feed → Tutti / Più recenti**, che è cronologica e
  non filtrata dall'algoritmo. La sezione "Preferiti" ha un tetto basso (~30 pagine)
  e va riservata alle fonti di fascia A ad altissima resa.

### Limiti che vanno accettati esplicitamente

- **Il feed non è garantito completo.** Anche in modalità cronologica le piattaforme
  possono omettere post. Perdi qualcosa: è il prezzo del fattore 20×.
- **Instagram Stories restano fuori.** Molte Pro Loco annunciano lì. Non c'è modo
  sostenibile di coprirle a questa scala: limite accettato.
- **L'attribuzione della fonte va ricostruita** dal nome dell'account nel post, non
  dall'URL di partenza. Serve una tabella `handle → source_id → comune`, che è
  esattamente il foglio `Fonti`.
- Se il feed viene degradato o l'account bloccato, si torna al polling selettivo
  sulla sola fascia A (~150 account): degradazione prevista, non catastrofe.

### Il polling per account non sparisce del tutto

Resta, ma solo per **un centinaio di account di fascia A ad alta resa**, controllati
2-3 volte a settimana come rete di sicurezza sul feed. Sono 100 × 30s ≈ 50 minuti,
sostenibili.

---

## 12.4 L2 — Fasce di perimetro

Perimetro **tagliato a 100 km**: oltre quella soglia i comuni escono del tutto, non
sono più fascia D. Elimina Milano, Pavia, Genova e l'intera coda lombardo-emiliana,
cioè ~800-1.000 comuni da cui non saresti mai andato a un evento.

| Fascia | Distanza | Comuni (stima) | Livello di servizio |
|---|---|---|---|
| **A** | ≤ 50 km | ~400 | Copertura piena: sito + Pro Loco + social nel feed. Include **Alba (~30 km), Acqui Terme (29,6 km), Alessandria (~48 km)** e tutto ciò che sta nel raggio |
| **B** | 50-75 km | ~300 | Sito + social nel feed. Frequenza ridotta |
| **C** | 75-100 km | ~500 | Solo T0 + aggregatori + social già nel feed |
| — | > 100 km | escluso | Fuori perimetro |

### Il polling diretto è un flag separato, non la fascia A

Con A estesa a 50 km, l'equazione "fascia A = polling diretto" non regge più: 400
comuni significano ~800 account social, cioè quasi 7 ore di navigazione. Le due cose
vanno quindi separate.

```
fascia          → quanto spesso vale la pena guardare, e se ha senso
                  avere fonti individuali (dipende dalla DISTANZA)

polling_diretto → chi merita una visita dedicata oltre al feed
                  (dipende dalla RESA, non dalla distanza)
```

`polling_diretto` è un flag su un insieme **chiuso di ~100 fonti**, tenuto sotto
controllo dal budget di tempo:

- i **poli**: Asti, Alba, Acqui Terme, Alessandria, Nizza Monferrato, Canelli,
  Cortemilia — comuni, teatri e uffici turistici
- le **feste storiche** ricorrenti (foglio `Feste`)
- gli **aggregatori** a resa più alta
- le Pro Loco della cerchia vicina che si dimostrano produttive nei primi mesi

Tutto il resto della fascia A vive nel feed social e nei T0/T1 in rotazione, che
costano una frazione. Il tetto dei 100 è un parametro in `Config`: se il run resta
sotto il budget lo alzi, altrimenti lo abbassi. È l'unica leva di carico che serve
davvero governare.

In fascia C si tiene solo ciò che vale il viaggio: teatri importanti, festival,
grandi sagre — che sono comunque presenti sui portali aggregatori.

Effetto: le fonti da gestire individualmente scendono da ~4.800 a **~1.800**, e le
fonti social da seguire da ~2.350 a **~1.400**. La fascia D si copre con 30 fonti.

La colonna `priorita` in `Perimetro` diventa quindi la **fascia**, derivata
automaticamente da `km`, con possibilità di override manuale (un comune a 50 km dove
vai spesso può stare in A).

## 12.4b Due regimi di copertura

Non tutte le categorie di fonti si trattano allo stesso modo. La distinzione è netta
e semplifica molto la discovery.

| | **Massivo** | **Curato** |
|---|---|---|
| **Chi** | Comuni, Pro Loco | Feste storiche, compagnie teatrali, cantine, agriturismi, ristoranti, bar, pub, circoli, locali |
| **Obiettivo** | **Esaustività**: tutti, su tutto il perimetro | **Selezione**: solo ciò che ti interessa davvero |
| **Come si popola** | Discovery automatica ([12.8](12-scala-e-copertura.md#128-import-e-arricchimento-dellelenco-fonti)) | **A mano**, incrementalmente |
| **Volume** | ~1.200 comuni + ~1.000 Pro Loco | **Tetto ~200 fonti** |
| **Nessun limite di distanza** | Corretto: la fascia regola la frequenza, non l'inclusione | Idem |

**Perché la distinzione conta.** La discovery automatica di attività commerciali è
un problema aperto e a bassissima resa: migliaia di soggetti, quasi nessun evento
pubblico, moltissimo rumore promozionale. Cercare di mapparle tutte è esattamente il
tipo di ambizione che fa esplodere il progetto.

La copertura degli eventi organizzati da attività commerciali arriva quindi da due
strade indirette, entrambe già previste:
- i **portali aggregatori**, che raccolgono la serata degustazione della cantina
  senza che tu debba conoscere la cantina;
- le **liste manuali**, che aggiungi quando un locale ti interessa davvero.

Il tetto di 200 non è tecnico ma pratico: è quante fonti puoi realisticamente
mantenere a mano. Quando ne aggiungi una, ne dovresti togliere un'altra.

Nel foglio `Fonti` la colonna `regime` (`massivo` / `curato`) distingue le due
popolazioni: le fonti curate non vengono mai toccate dalla discovery automatica né
disattivate d'ufficio, perché le hai messe tu.

---

## 12.5 L3 — Adattatori per famiglia di piattaforma

A 40 fonti scrivere un parser dedicato non conviene mai. **A 1.000 siti comunali
conviene eccome**, perché non sono 1.000 siti diversi: sono una decina di piattaforme
ripetute mille volte.

I siti dei comuni italiani si concentrano su pochi modelli ricorrenti: i template
istituzionali diffusi dopo le linee guida di design per la PA, alcuni CMS commerciali
per enti locali molto venduti, WordPress con i plugin di calendario eventi più
comuni, e poche piattaforme regionali condivise.

**Procedura:**
1. **Fingerprinting** — scarica la homepage di tutti i siti comunali e classificali
   per firma (meta generator, percorsi caratteristici, CSS ricorrenti, struttura URL).
   È un'operazione batch da fare una volta: 1.000 richieste leggere, ~30 minuti.
2. **Classifica per frequenza.** Probabilmente le prime 8-10 famiglie coprono il
   60-75% dei comuni.
3. **Scrivi un adattatore per famiglia**, non per comune. Ogni adattatore conosce
   il percorso della sezione eventi, la struttura della lista e, spesso, l'endpoint
   strutturato nascosto (i template istituzionali e i plugin di calendario espongono
   quasi sempre RSS o iCal).
4. Il resto rimane in T1 generico con `trafilatura` + LLM.

**Questa è l'unica parte del progetto dove scrivere codice specifico conviene**,
proprio perché il moltiplicatore è ×100 e non ×1. È l'inversione esatta della regola
data in [04](04-fonti-ingestione.md#43-adattatori): a quella scala era sbagliata,
a questa è giusta.

**Effetto collaterale prezioso:** un adattatore di famiglia spesso trasforma
centinaia di fonti da T1 a T0 in un colpo solo.

---

## 12.6 L4 — Aggregatori e dati aperti come primo strato

A questa scala i portali cambiano di ruolo: da "utile complemento" a **fondamento**.

Un portale regionale che copre 500 comuni vale 500 fonti al costo di una. A 1.000
comuni, questo strato dovrebbe essere la **prima** cosa costruita, non l'ultima.

Da cercare sistematicamente:
- **Portali turistici regionali** — quasi tutte le regioni italiane ne hanno uno con
  sezione eventi, e diverse pubblicano gli eventi come **dati aperti** con API o
  dump scaricabili. Un solo endpoint può coprire un'intera regione.
- **Cataloghi di dati aperti** regionali e nazionali, cercando dataset di eventi,
  manifestazioni, spettacoli.
- **Portali di sagre e feste paesane** a copertura nazionale.
- **Circuiti cinematografici** — le programmazioni sono strutturate e complete.
- **Reti teatrali regionali** e circuiti di distribuzione.
- **Piattaforme di biglietteria**, filtrate per provincia.

Prima di scrivere qualsiasi adattatore social, vale la pena spendere due giornate a
cercare questi endpoint: il rapporto tra sforzo e copertura non è paragonabile a
nient'altro nel progetto.

---

## 12.7 L5 — Raccolta per query invece che per account

Complementare al feed: invece di chiedere "cosa ha pubblicato X", chiedi
"cosa è stato pubblicato **su questo argomento / in questo luogo**".

- **Hashtag** geografici e tematici (`#sagra`, `#prolococittà`, hashtag provinciali)
- **Geotag / luoghi** — i post taggati in un comune
- **Ricerca per parole chiave** con filtro temporale

Vantaggi: cattura anche soggetti che **non hai mappato** — a 1.000 comuni è certo che
ne mancheranno centinaia. Svantaggi: molto rumore, risultati non esaustivi,
disponibilità variabile.

**Ruolo corretto:** rete a strascico complementare, non fondamento. Da eseguire
settimanalmente su un insieme limitato di query, con filtro rigoroso sul comune
risultante. Serve soprattutto a **scoprire fonti nuove** da aggiungere al foglio.

---

## 12.8 Import e arricchimento dell'elenco fonti

**L'elenco delle fonti è già disponibile** (decisione D10) nel workbook *Perimetro
Eventi*. Il bootstrap non deve quindi scoprire i soggetti da zero, ma **importarli,
bonificarli e arricchirli**.

⚠️ **La bonifica non è un passaggio formale.** L'audit in [13](13-audit-fonti.md) ha
trovato che circa un link social su cinque punta all'entità sbagliata — in alcuni casi
a comuni a 150 km di distanza. Costruire sopra questi dati produce un elenco che
sembra funzionare e non funziona. Le regole di bonifica sono in
[13.4](13-audit-fonti.md#134-regole-di-bonifica).

```
1. Import dell'elenco esistente → foglio `Fonti`
   Normalizzazione dei nomi comune, assegnazione `source_id`,
   join con `Perimetro` per fascia e comune di riferimento

2. Validazione (batch, ~2.000 richieste leggere)
   - gli URL rispondono? redirect? dominio cambiato?
   - gli handle social esistono ancora?
   → le fonti che non rispondono non vanno cancellate ma marcate,
     perché spesso è solo un URL vecchio

3. Arricchimento
   - per i comuni privi di URL: recupero dall'indice ufficiale delle
     Pubbliche Amministrazioni, che contiene il sito di ogni comune
   - per i siti privi di handle social: estrazione dei link a
     facebook.com / instagram.com dalla homepage (di norma nel footer)
   - ricerca di Pro Loco, teatro e biblioteca dai link uscenti

4. Fingerprinting della piattaforma (L3) e discovery degli endpoint
   strutturati (prober di [04](04-fonti-ingestione.md#42-discovery-il-prober))

5. Copertura dei buchi
   Confronto tra `Perimetro` e `Fonti`: quali comuni di fascia A e B
   non hanno nessuna fonte? Sono la lista di lavoro manuale, e sarà
   corta invece che di mille righe.
```

Il passo 5 è quello che rende utile avere già l'elenco: invece di mappare tutto,
lavori solo sui buchi delle fasce che contano.

Da rieseguire una o due volte l'anno per la sola validazione (passo 2), che intercetta
i siti dismessi e gli handle cambiati.

---

## 12.9 Rotazione e capacità

Il concetto di "run completo" sparisce. Al suo posto: **capacità fissa per run e
rotazione**.

```
Capacità giornaliera (180 minuti):
  - Feed social (FB + IG)          45 min   → copre TUTTE le fonti social seguite
  - Aggregatori + dati aperti      15 min   → copre l'intero perimetro
  - T0 (ical/rss/jsonld)           30 min   → ~600 fonti/giorno in rotazione
  - T1 fascia A                    40 min   → ~500 fonti/giorno in rotazione
  - Polling diretto (max ~100)     30 min   → ~60 fonti/giorno
  - Estrazione, dedup, publish     20 min
```

Il **polling diretto** è l'unica voce che non scala con il perimetro: è un insieme
chiuso, quindi il run resta dentro il budget anche se aggiungi comuni.

Con questa capacità, il **ciclo di visita** per tipo di fonte diventa:

| Fonte | Ciclo |
|---|---|
| Feed social | quotidiano (tutte insieme) |
| Aggregatori | quotidiano |
| Polling diretto (~100) | 2 volte/settimana |
| T0 fascia A | ogni 2-3 giorni |
| T0 fascia B/C | settimanale |
| T1 fascia A | ogni 3-4 giorni |
| T1 fascia B | ogni 10-14 giorni |
| T1 fascia C | ogni 3-4 settimane |

Il ciclo lungo sulla fascia C è accettabile: quegli eventi sono comunque marginali,
e il feed social li cattura comunque in tempo reale.

La coda a priorità dinamica di [08](08-orchestrazione-operativita.md#83-costruzione-della-coda)
resta valida, con l'aggiunta della fascia come fattore dominante:

```
punteggio = (4 − fascia) × 30          # A=90, B=60, C=30 — dominante
          + polling_diretto × 50       # il flag, non la distanza
          + resa_stagionale × 20       # resa nello stesso periodo, anni scorsi
          + finestra_attenzione × 40   # +40 se siamo nella finestra storica
          + giorni_da_ultimo_run × 3   # senza tetto: nessuna fonte resta
                                       # indietro per sempre
          + bonus_novità               # fonte nuova, senza storico
          − penalita_errori            # solo per errori, non per silenzio
```

Tre proprietà volute:

- **La fascia domina tutto il resto.** È la disciplina che tiene il sistema dentro il
  budget. Una fonte di fascia C con ottima resa può superare una fonte di fascia B
  scarsa, ma non una di fascia A.
- **Il termine `giorni_da_ultimo_run` non ha tetto.** Garantisce che anche la fonte
  più silenziosa del perimetro risalga da sola in coda: è il *floor* di
  [04](04-fonti-ingestione.md#47-fonti-dormienti--fonti-inutili) espresso come
  priorità dinamica invece che come frequenza fissa.
- **`finestra_attenzione` pesa quasi quanto una fascia intera.** Nelle settimane in
  cui l'anno scorso quella Pro Loco ha annunciato la sagra, la fonte va trattata come
  se fosse di fascia A anche se sta in C.

⚠️ **Stato reale**: `finestra_attenzione` e `resa_stagionale` restano l'intento
di design, non ancora implementati — la colonna `finestra_attenzione` sul
foglio `Fonti` è stata rimossa il 2026-08-28 perché non aveva un dato sorgente
reale (vedi [03-modello-dati.md](03-modello-dati.md#314-fonti)). La priorità
dinamica realmente in produzione (`src/scheduling.py`) usa fascia, resa
storica, giorni dall'ultimo run e penalità errori — senza il termine
stagionale, che richiede più storico in `Archivio` per essere calcolato
onestamente.

**La bassa resa non toglie mai una fonte dalla coda: ne allunga solo l'intervallo.**
Solo lo stato `rotta` la sospende, e in modo reversibile.

---

## 12.10 Impatto sui volumi LLM (senza GPU)

Questo è il punto in cui il budget zero si tende, e senza modello locale il margine
si assottiglia ulteriormente.

**Stima del flusso giornaliero:**

```
Post dal feed social            ~1.400 account × 0,25 post/giorno ≈  350
  − pre-filtro grafico e testuale (−40%)                          ≈  210
  − cache pHash, stessa locandina su più canali (−35%)            ≈  135
Artefatti web T1 con contenuto cambiato                           ≈  120
Artefatti da aggregatori (in gran parte T0, senza LLM)            ≈   30
                                                                  ─────
Chiamate LLM stimate al giorno                                    ≈  285
  di cui multimodali (locandine)                                  ≈  135
```

Rientra nella quota gratuita di un modello della famiglia Flash, ma **senza margine
per gli errori**: nei picchi estivi il flusso delle sagre può triplicare, portando a
~850 chiamate al giorno.

### Il pre-filtro deterministico diventa il componente critico

Senza un modello locale che faccia il triage, tutto il lavoro di riduzione deve essere
fatto da regole a costo zero. Vanno progettate con cura, non improvvisate:

**Sul testo** — scarta prima di qualunque chiamata:
- nessun pattern di data riconoscibile (numeri+mese, giorno della settimana, "domani",
  "questo weekend") **e** nessuna parola chiave di evento
- solo pattern di data al passato rispetto a oggi
- lunghezza sotto una soglia minima e nessuna immagine allegata
- corrispondenza con schemi noti di post non-evento: auguri, ringraziamenti,
  necrologi, avvisi di viabilità, comunicati amministrativi

**Sulle immagini** — scarta prima del VLM:
- lato minore < 400 px
- rapporto d'aspetto fuori dall'intervallo plausibile per una locandina
- immagine identica (pHash) al logo o alla foto profilo della pagina — molto frequente
- **densità di bordi/testo bassa**: una locandina è densa di testo, una foto di
  paesaggio no. Si stima a costo trascurabile con un filtro di Sobel o simile, e
  intercetta la categoria più numerosa di scarti (foto dell'evento dell'anno scorso)

**Sulla cache** — la leva più efficace di tutte:
- `pHash` con distanza di Hamming ≤ 8 → riusa l'estrazione già fatta
- hash del testo normalizzato → riusa
- a questa scala la stessa locandina compare su 5-10 canali: **è questo componente
  che decide se il budget regge**

### Ordine di priorità della quota

Quando il budget giornaliero si avvicina al limite, non tutte le chiamate valgono
uguale:

```
1. Locandine da fonti in polling_diretto e fascia A   → sempre
2. Testo da fonti in polling_diretto e fascia A       → sempre
3. Locandine fascia B                                 → sotto l'80% della quota
4. Testo fascia B                                     → sotto l'80%
5. Fascia C (qualsiasi)                               → sotto il 60%
```

Gli artefatti non processati restano in coda con `processed_at = null` e vengono
ripresi il giorno dopo: un limite duro diventa un ritardo.

### Triage testuale su CPU — opzionale

Un modello 1-3B via `llama.cpp` può fare il giudizio binario sul solo testo in pochi
secondi per chiamata, senza consumare quota. Su ~300 artefatti sono 25-40 minuti di
CPU, che rientrano nel budget ma se lo mangiano quasi tutto.

**Vale la pena solo se la quota cloud si rivela davvero insufficiente**, e comunque
non aiuta sulle immagini — che sono la metà del volume e tutta la parte costosa.
Da tenere come opzione, non da costruire subito.

---

## 12.11 L'output non deve annegare

Problema nuovo, che a 40 comuni non esisteva: **1.000 comuni possono produrre
centinaia di eventi a settimana**. Un foglio con 2.000 righe non è consultabile, e
un elenco inutilizzabile equivale a un progetto fallito.

Contromisure di progettazione:

- ~~`Eventi` non è tutto: è una vista, limitata a 21 giorni/fasce A-B, con
  `Eventi_estesi` per il resto~~ — **superato il 2026-09-10**: `Eventi`
  pubblica oggi tutte le righe attive in un unico foglio, su richiesta
  esplicita dell'utente che non vedeva il senso della divisione (vedi
  [03-modello-dati.md](03-modello-dati.md#31-struttura-del-google-sheet)).
  Se il volume dovesse tornare a rendere il foglio illeggibile, l'idea di una
  vista filtrata resta disponibile da reintrodurre.
- **Ordinamento per rilevanza, non per data:** una funzione di punteggio che combina
  distanza, imminenza, tipologia preferita e affidabilità.
- **`Archivio` in uno spreadsheet separato**. Il file principale deve restare
  leggero.
- **Filtri e viste salvate** nel foglio (per tipologia, per fascia, per weekend).
- Il KPI di copertura ([01](01-requisiti.md#15-kpi-da-misurare-non-opzionali)) si
  misura **solo sulla fascia A**: su 1.000 comuni non è misurabile e non ha senso.

---

## 12.12 Cosa non fare a questa scala

- **Non visitare i profili social uno per uno.** È il modello che ha fatto fallire il
  primo tentativo e a 2.350 account è impossibile, non solo lento.
- **Non usare browser headless come metodo generale.** Riservalo alla fascia A e ai
  casi in cui il contenuto è davvero inaccessibile altrimenti.
- **Non parallelizzare le richieste social.** Il fattore limitante non è la banda,
  è la soglia di rilevamento.
- **Non tentare la copertura individuale della fascia C.** Costa e non ti serve.
- **Non mappare le fonti a mano oltre la fascia A.** Il bootstrap automatico è
  l'unico approccio sostenibile su 1.000 comuni.
- **Non disattivare le fonti perché tacciono.** Una Pro Loco che pubblica solo per la
  sagra di luglio è silenziosa undici mesi e poi produce l'evento più importante del
  suo comune. Il silenzio modula la frequenza; solo l'errore persistente sospende
  ([04](04-fonti-ingestione.md#47-fonti-dormienti--fonti-inutili)).
- **Non trattare tutte le fonti come uguali.** La differenza tra questo progetto che
  funziona e questo progetto che muore è interamente nella disciplina delle fasce.
