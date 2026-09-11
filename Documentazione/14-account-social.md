# 14 — L'account social dedicato

Guida operativa alla leva L1 ([12.3](12-scala-e-copertura.md#123-l1--inversione-del-feed-social-)):
un'identità che segue tutti i soggetti, così da leggere un feed solo invece di
visitare migliaia di profili.

⚠️ Va detto prima di tutto il resto: **leggere automaticamente il feed viola i
Termini di Servizio di Meta**, qualunque account si usi. Non è un problema legale
per un uso personale, ma è un rischio concreto di limitazione dell'account. Tutto
ciò che segue serve a ridurre quel rischio, non a eliminarlo. Il sistema deve
restare utile anche se questo canale sparisce
([05.7](05-social-locandine.md#57-piano-di-degradazione)).

---

## 14.1 Instagram e Facebook non sono lo stesso caso

Differenza che cambia la strategia e che va conosciuta prima di iniziare.

**Instagram consente più account per persona.** È una funzione supportata: il cambio
rapido tra profili esiste nell'app. Creare un account dedicato è del tutto
legittimo e non ha controindicazioni di policy.

**Facebook no.** I termini richiedono un solo profilo personale per persona, con nome
reale. Un secondo profilo è una violazione esplicita e, soprattutto, gli account nuovi
senza rete sociale reale vengono **flaggati con alta probabilità** — è proprio il
profilo comportamentale di un bot. Le opzioni sono tre, in ordine di preferenza:

| Opzione | Come funziona | Pro | Contro |
|---|---|---|---|
| **A — Pagina Facebook** | Crei una Pagina (es. "Eventi Astigiano", anche senza pubblicarla). Una Pagina può seguire altre Pagine e ha un proprio feed | Struttura **legittima**, pensata per questo. Non tocca il tuo profilo personale | Non può seguire i **gruppi**; alcune Pagine private restano fuori |
| **B — Profilo personale + curatela** | Usi il tuo account, ma sfrutti la scheda **Feed → Tutti / Più recenti**, cronologica e non filtrata dall'algoritmo | Nessuna violazione di policy sull'identità | Ti **inonda il feed personale** con 700 pagine di comuni. Praticamente ingestibile |
| **C — Secondo profilo personale** | Un profilo nuovo dedicato | Massima libertà, include i gruppi | Viola i termini, alto rischio di blocco nelle prime settimane |

**Scelta adottata: due account dedicati, Facebook e Instagram**, creati a mano.
Per Instagram è la strada naturale. Per Facebook è l'opzione C: dà accesso anche ai
gruppi (vedi 14.6), che è il motivo per cui la scegli, ma comporta il rischio
descritto sopra. Le prime settimane sono le più delicate — il riscaldamento di 14.3
non è un passaggio formale.

Se il profilo Facebook dovesse essere bloccato, il ripiego è l'opzione A: una Pagina
che segue le Pagine, perdendo i gruppi ma mantenendo la copertura principale.

---

## 14.2 Creazione

**Instagram**
1. Crea l'account da app mobile, non da browser: è il percorso più normale e meno
   sospetto.
2. Usa una **email dedicata** (la stessa casella che userai per le newsletter —
   vedi [05.4](05-social-locandine.md#54-i-due-canali-alternativi) — va benissimo).
3. Usa un **numero di telefono che non sia quello del tuo account principale**, se ne
   hai uno. Se non ne hai, salta: la verifica via email in genere basta.
4. Nome e bio coerenti e onesti: *"Raccolgo eventi e sagre del Monferrato"*. Non
   spacciarti per un'organizzazione che non sei.
5. **Attiva la 2FA** e salva i codici di recupero. Se perdi l'accesso dopo aver
   seguito 1.400 account, ricominci da zero.
6. Metti una foto profilo e pubblica 2-3 post qualsiasi. Un account vuoto che segue
   centinaia di profili è il pattern più riconoscibile che esista.

**Facebook (opzione A)**
1. Dal tuo profilo personale, crea una Pagina. Categoria: qualcosa di plausibile
   come "Sito web di notizie ed eventi" o "Comunità".
2. Non serve pubblicarla né promuoverla. Può restare inattiva.
3. Passa a "usa Facebook come Pagina" e da lì segui le altre Pagine.

---

## 14.3 Riscaldamento — 2 settimane, prima di qualunque follow massivo

Questa fase sembra tempo perso e non lo è: è ciò che distingue un account che
sopravvive da uno bloccato al trecentesimo follow.

- **Settimana 1:** usa l'account **a mano**, come utente normale. Apri l'app dal
  telefono, scorri, metti qualche like, segui 5-10 profili al giorno tra quelli che
  ti interessano davvero. Nessuna automazione.
- **Settimana 2:** stessa cosa, salendo a 15-20 follow al giorno.
- Accedi **dal telefono e da casa**, sulla stessa rete che userai poi. Un account
  creato da mobile e usato subito da uno script su un IP diverso è un segnale forte.

---

## 14.4 Popolamento — coda di follow semiautomatica

Il popolamento è **assistito**: una coda ordinata nel foglio e un comando che ne
consuma 10 per volta, lanciato **a mano** da te in momenti diversi della giornata.

Questa è, in tutto il progetto, **l'unica automazione che compie un'azione** invece di
limitarsi a leggere. È quindi la più rischiosa: le azioni sono molto più rilevabili
della lettura passiva. I parametri qui sotto sono conservativi apposta.

### Foglio `CodaFollow`

| Colonna | Origine | Contenuto |
|---|---|---|
| `source_id` | sistema | Riferimento a `Fonti` |
| `piattaforma` | sistema | `facebook` / `instagram` |
| `handle` | sistema | Normalizzato, senza URL |
| `url` | sistema | Profilo verificato |
| `soggetto`, `comune`, `fascia` | sistema | Per contesto |
| `priorita` | sistema | Vedi ordinamento |
| `stato` | sistema + tu | `da_seguire` / `seguito` / `fallito` / `non_valido` / `saltato` |
| `tentativi` | sistema | ≥ 3 → `fallito`, esce dalla coda |
| `data_follow` | sistema | Quando è andato a buon fine |
| `note` | sistema | Motivo dell'eventuale fallimento |

### Ordinamento della coda

```
priorita = polling_diretto × 100
         + (4 − fascia) × 20              # A=60, B=40, C=20
         + categoria_peso                  # proloco 15, comune 10,
                                           # festa 15, teatro 8, altro 3
         + ha_gia_altro_canale × (−5)      # se lo segui già su IG,
                                           # FB è meno urgente
```

Così le prime settimane portano dentro i soggetti che contano davvero: poli, feste
storiche, Pro Loco della cerchia vicina. Il sistema diventa utile dopo pochi giorni,
non a popolamento completato.

### La procedura `follow_batch`

```
COMANDO:  python run.py follow --platform=instagram [--n=10] [--dry-run]

PRECONDIZIONI (se una fallisce, esce senza fare nulla):
  - non ci sono già stati follow nelle ultime 45 minuti
  - il totale di oggi su questa piattaforma è < 40
  - lo stato del circuito non è "aperto" (vedi 14.5b)
  - la sessione salvata è valida (nessun re-login automatico:
    se serve login, chiede a te di farlo a mano)

CICLO, per i primi N=10 elementi in stato da_seguire:
  1. apri il profilo
  2. VERIFICA che l'handle corrisponda al soggetto atteso
     → se la pagina non esiste o è un altro soggetto: non_valido, avanti
  3. se risulta già seguito → seguito, avanti (nessuna azione)
  4. clicca Segui
  5. verifica che lo stato sia cambiato
     → se no: tentativi += 1, avanti
  6. registra seguito + data
  7. PAUSA random 25-70 secondi
     ogni 3-4 follow, pausa lunga random 2-4 minuti
     (simula lo scroll di chi guarda cosa ha appena seguito)

AL TERMINE:
  aggiorna Fonti.seguito, scrive nel Log, aggiorna il foglio Stato
```

Un lotto dura quindi **6-10 minuti**. Con 3-4 lanci al giorno sono 30-40 follow
giornalieri e ~1.400 soggetti in 5-7 settimane.

### Parametri

| Parametro (in `Config`) | Default |
|---|---|
| `follow_per_lotto` | 20 (default originario 10, alzato su richiesta esplicita) |
| `follow_max_giornalieri` | 100 per piattaforma (default originario 40, idem) |
| `follow_pausa_min` / `_max` | 25 / 70 secondi |
| `follow_pausa_lunga_ogni` | 3-4 follow |
| `follow_intervallo_lotti_min` | 45 minuti |

⚠️ **Tetti alzati rispetto al default prudente**, rischio accettato
consapevolmente prima della fine del periodo di riscaldamento — vedi
[CRONACA.md](../CRONACA.md) per il contesto della decisione. Il ragionamento
sotto ("perché il lancio resta manuale") resta il default raccomandato; lo
scostamento è una scelta operativa specifica, non un cambio di policy.

### Perché il lancio dovrebbe restare manuale

Uno scheduler produrrebbe lotti a orari regolari — e la regolarità è precisamente
il segnale che distingue un bot da una persona. Lanciandolo tu quando ti capita,
la distribuzione oraria è naturale senza doverla simulare. Costa dieci secondi e
rimuove l'indizio più forte.

**Stato reale**: oggi il follow è schedulato automaticamente ogni 2 ore
(`eventi/schedulazione_follow.bat`, Utilità di pianificazione Windows) — in
tensione diretta con questo principio. Le precondizioni/il circuito di
sicurezza esistenti fermano da soli un lotto se non è il momento giusto, ma
la regolarità dello scheduling resta un fattore di rischio non eliminato,
accettato consapevolmente su richiesta esplicita.

Vale anche come sicurezza: se qualcosa va storto, si ferma da solo perché nessuno lo
rilancia.

---

## 14.5 Interruttore di sicurezza

La procedura si ferma **immediatamente** e apre il circuito al primo di questi segnali:

| Segnale | Azione |
|---|---|
| Captcha o verifica di sicurezza | Stop lotto, circuito aperto **72 ore** |
| "Azione bloccata" / "Riprova più tardi" | Stop, circuito aperto **7 giorni** |
| 3 follow consecutivi che non cambiano stato | Stop, circuito aperto 24 ore, segnalazione |
| Redirect a login o sessione scaduta | Stop, nessun re-login automatico |
| Richiesta di verifica identità | Stop **definitivo**: decidi tu |

A circuito aperto, `follow_batch` esce subito con un messaggio. Non c'è modo di
forzarla se non modificando `Config` a mano — voluto: la tentazione di insistere dopo
un blocco è forte ed è il modo più rapido di perdere l'account.

Lo stato del circuito e la data di riapertura sono visibili nel foglio `Stato`.

### Regola di separazione

**Mai follow e lettura del feed nella stessa sessione.** Sono due comportamenti
diversi e vanno tenuti separati nel tempo: almeno un'ora tra un lotto di follow e la
sessione di lettura. Vale anche per le sessioni del browser: due contesti distinti.

---

## 14.5b Lettura del feed

- **Instagram:** vista cronologica ("Seguiti"/"Following"), non quella predefinita.
- **Facebook:** scheda **Feed → Tutti / Più recenti**.
- **Sessione persistente:** salva i cookie e riusali. Un login a ogni run è
  sospettissimo e, dopo qualche volta, fa scattare la verifica.
- **Scroll fino all'ultimo post già visto**, poi stop. Nella maggioranza dei giorni
  sono pochi minuti.
- **Nessun parallelismo, nessuna interazione automatica.** Solo lettura: niente like,
  niente commenti, niente follow da script. La lettura passiva è molto meno
  rilevabile dell'azione.
- **Una sessione al giorno**, in orario plausibile. Meglio la sera che le 3 di notte.

---

## 14.6 Gruppi Facebook — il caso che giustifica il rischio

Hai osservato giustamente che i gruppi e le pagine di ripubblicazione servono a
intercettare gli eventi organizzati da soggetti che non mapperai mai: gli **alpini**,
le parrocchie, i comitati di frazione, i gruppi sportivi che fanno la polentata.
È vero, ed è un argomento serio: sono proprio gli eventi che sfuggono a tutto il
resto.

Però i gruppi hanno tre caratteristiche che li rendono una categoria a sé:

1. **Una Pagina non può iscriversi a un gruppo.** Serve un profilo personale — quindi
   l'opzione A non li copre.
2. **L'attribuzione del comune è inaffidabile.** In un gruppo provinciale, chi
   pubblica non è chi organizza, e spesso non c'è alcun riferimento al luogo se non
   nella locandina. Il campo `comune_riferimento` della fonte, che altrove salva le
   estrazioni ambigue, qui è inutilizzabile: va lasciato vuoto e l'evento senza
   comune deve andare in quarantena, non essere attribuito.
3. **Rumore alto:** ricordi, foto dell'anno scorso, richieste di informazioni.

**Impostazione consigliata:** iscrivi il tuo **profilo personale** a 5-10 gruppi
selezionati (Sagre Piemonte e simili) e leggili come fonte separata, a bassa
frequenza (settimanale). Non servono per la copertura — servono per la **scoperta di
organizzatori nuovi**: quando un soggetto compare due o tre volte, lo aggiungi a
`Fonti` e da quel momento lo segui direttamente. È la leva L5
([12.7](12-scala-e-copertura.md#127-l5--raccolta-per-query-invece-che-per-account))
applicata bene.

---

## 14.7 Se qualcosa va storto

| Sintomo | Significato | Cosa fare |
|---|---|---|
| Captcha occasionale | Sospetto lieve | Rallenta, passa a giorni alterni, usa l'app a mano per qualche giorno |
| "Azione bloccata temporaneamente" | Rate limit | **Fermati del tutto per 48-72 ore.** Insistere peggiora |
| Richiesta di verifica identità | Sospetto serio | Se è la Pagina, nessun danno. Se è l'account IG dedicato, valuta se vale la pena verificarlo |
| Account disabilitato | Fine | Non ricrearne uno subito dallo stesso dispositivo e IP: verrebbe collegato. Il sistema continua senza social |

**Regola generale: l'account è sacrificabile, il progetto no.** Se il canale social
salta, restano aggregatori, T0, newsletter e liste manuali — che nel tuo perimetro
coprono comunque la maggior parte degli eventi importanti.

---

## 14.8 Cosa non fare, mai

- Superare i limiti della coda di follow o forzare il circuito aperto
- Schedulare `follow_batch`: il lancio manuale è parte del design
- Mettere like, commentare o inviare messaggi da script
- Usare servizi di terze parti che chiedono le tue credenziali
- Collegare l'account IG dedicato al tuo numero principale o al tuo profilo Facebook
- Fare più di una sessione di lettura al giorno
- Eseguire il tutto da un IP diverso da quello di casa (VPN incluse: peggiorano il
  segnale, non lo migliorano)
- Riprendere subito dopo un blocco temporaneo
