# 07 — Normalizzazione, geolocalizzazione e deduplica

Tutto ciò che è descritto qui è **deterministico**. Nessuna chiamata LLM, nessun
costo, comportamento riproducibile e correggibile.

## 7.1 Normalizzazione del titolo

Serve sia per la leggibilità sia come base della chiave di deduplica.

```
titolo_visualizzato:
  - rimuovi emoji e simboli decorativi
  - se è tutto maiuscolo → Title Case italiano
    (minuscole per articoli/preposizioni interne: di, della, e, a, in, per)
  - comprimi spazi multipli, rimuovi punteggiatura ripetuta (!!!, ...)
  - taglia a 120 caratteri su confine di parola

titolo_normalizzato (solo interno, per il matching):
  - minuscolo, accenti rimossi
  - rimuovi numeri ordinali di edizione (53ª, XII, 12°)
  - rimuovi il nome del comune se già presente
  - rimuovi stopword: la, il, lo, di, a, da, in, con, su, per, tra, fra,
    e, ed, festa, sagra, edizione, annuale
  - ordina alfabeticamente i token restanti
```

L'ultimo passaggio (ordinamento dei token) fa sì che *"Sagra della Rana Vimercate"* e
*"Vimercate: la Sagra della Rana"* producano la stessa stringa.

## 7.2 Normalizzazione delle date

L'LLM restituisce già ISO. Restano i controlli:

- Coerenza `data_inizio ≤ data_fine`; se invertite, scambia e segnala
- Se `data_fine` è oltre 30 giorni da `data_inizio` → probabile errore o rassegna:
  quarantena con motivo `durata_anomala`
- Anno mancante: regola di [06](06-estrazione-llm.md#65-il-problema-dellanno-mancante)
- Orari: `21` → `21:00`; `21.30` → `21:30`; "ore 21 e 30" → `21:30`
- Fuso orario: irrilevante, si lavora sempre in ora locale italiana

**Ricorrenze: vedi 7.9.** Un evento ricorrente non è una riga con una nota, ma una
**serie** che genera una riga per ogni occorrenza.

---

## 7.9 Ricorrenze: espansione in occorrenze

Il caso tipico — *"mercatino dell'antiquariato la prima domenica del mese"* — deve
produrre **una riga per ogni mese**, non una riga con un testo esplicativo. Questo
cambia il modello dati e vale la complessità aggiuntiva, per un motivo non ovvio:
solo con l'espansione le occorrenze si deduplicano correttamente. Se un'altra fonte
annuncia separatamente *"domenica 4 ottobre, mercatino"*, la chiave
`titolo + data + comune` la fa confluire da sola nella riga già generata. Con la nota
testuale sarebbero rimasti due record scollegati.

### Modello a due livelli

```
SERIE (foglio `Serie`, una riga)
  serie_id, titolo, tipologia, comune, luogo, regola, valida_dal,
  valida_al, eccezioni, ultima_conferma, fonte
        │
        ├──▶ OCCORRENZA  2026-09-06   (riga in `Eventi`)
        ├──▶ OCCORRENZA  2026-10-04
        ├──▶ OCCORRENZA  2026-11-01
        └──▶ ...
```

Ogni occorrenza è un evento a tutti gli effetti: ha il suo `event_id`, la sua
distanza, può essere corretta, bloccata o cancellata singolarmente. La serie è solo
la regola che le genera.

### Rappresentazione della regola

Usa **RRULE** (lo standard iCalendar, RFC 5545). Non inventare un formato: è già
progettato per questo, gestisce nativamente gli ordinali di giorno della settimana, ha
implementazioni mature in Python (`dateutil.rrule`) ed è direttamente riutilizzabile
se un giorno vorrai esportare in calendario.

| Caso reale | RRULE |
|---|---|
| Prima domenica del mese | `FREQ=MONTHLY;BYDAY=1SU` |
| Ultimo sabato del mese | `FREQ=MONTHLY;BYDAY=-1SA` |
| Tutti i venerdì di luglio | `FREQ=WEEKLY;BYDAY=FR;BYMONTH=7` |
| Ogni domenica fino al 30/9 | `FREQ=WEEKLY;BYDAY=SU;UNTIL=20260930` |
| Terzo weekend, sab+dom | `FREQ=MONTHLY;BYDAY=3SA,3SU` |

**L'LLM non produce la RRULE.** Restituisce campi vincolati (frequenza, giorno,
ordinale, mesi inclusi/esclusi, data di fine) e un convertitore deterministico
costruisce la regola. Far generare una sintassi formale a un modello è una fonte di
errori silenziosi evitabile.

### Orizzonte di espansione

Le occorrenze si generano **solo entro `orizzonte_espansione_giorni`** (120). L'orizzonte scorre:
a ogni run si generano le occorrenze nuove entrate in finestra e si archiviano quelle
passate. Non esistono righe per il 2028.

### Il problema vero: le serie senza scadenza

*"Tutti i venerdì di luglio"* ha una fine dichiarata. *"Il mercatino della prima
domenica"* no — e potrebbe essere finito due anni fa senza che nessuno l'abbia
annunciato. Generare occorrenze all'infinito da una regola letta una volta produce
eventi fantasma, che sono peggio degli eventi mancanti perché ti fanno uscire di casa
per niente.

Regola di decadimento, basata su `ultima_conferma` (l'ultima volta che una fonte
qualsiasi ha menzionato quella serie o una sua occorrenza):

```
giorni_da_ultima_conferma < 120   → espandi normalmente, confidenza piena
120 – 400                          → espandi, confidenza −25, marca "da verificare"
> 400 (oltre un ciclo annuale)     → smetti di espandere,
                                     serie in stato "sospesa",
                                     resta nel foglio `Serie` per riattivazione
```

Ogni volta che una fonte cita la serie o una singola occorrenza, `ultima_conferma` si
aggiorna e il decadimento riparte. Un mercatino vivo si riconferma da solo più volte
l'anno; uno morto smette di generare righe entro un anno.

### Eccezioni

Le eccezioni sono la norma in Italia, non un caso limite: quasi tutti i mercatini
saltano agosto, molti si spostano quando cadono su una festività, alcuni raddoppiano
a dicembre.

- **Campo `eccezioni` sulla serie**: elenco di date da non generare, alimentato sia
  dall'estrazione (*"escluso agosto"* → `BYMONTH` senza 8) sia a mano.
- **Soppressione della singola occorrenza**: se cancelli una riga generata, deve
  restare cancellata. Serve un flag persistente `soppressa` sull'occorrenza —
  altrimenti l'espansore la ricrea al run successivo e la cancellazione non ha alcun
  effetto. È l'errore classico di questo tipo di sistemi.
- **Spostamento**: un'occorrenza corretta a mano (data o luogo diversi) va marcata
  `bloccato = sì` e l'espansore non la tocca più.

### Interazione con la deduplica

Un'occorrenza generata e un evento annunciato singolarmente confluiscono per chiave
esatta. In fase di merge, però, **vince l'annuncio specifico**: se la fonte dice che
il mercatino di ottobre è al parco anziché in piazza, quel dato prevale sulla regola.
La regola è una previsione, l'annuncio è un fatto.

### Impatto sui volumi

Un mercatino mensile genera 3 righe per finestra invece di 1; una rassegna settimanale
ne genera 12. Su un perimetro ampio le serie ricorrenti possono facilmente
raddoppiare il numero di righe. È il principale motivo per cui la vista principale
deve restare limitata a 21 giorni e alle fasce A-B
([12](12-scala-e-copertura.md#1211-loutput-non-deve-annegare)) — con l'espansione
questa non è più una raccomandazione ma una necessità.

## 7.3 Risoluzione del comune

Passaggio critico, perché su questo si basa la distanza. Cascata di tentativi:

```
1. match esatto su `comune` in Perimetro          (normalizzato)
2. match esatto su uno degli `alias`               → risolve le frazioni
3. il testo del luogo contiene un nome di comune del perimetro
   (es. "Teatro Comunale di Concorezzo" → Concorezzo)
4. dizionario locale di luoghi noti (vedi 7.4)
5. `comune_riferimento` della fonte
   → confidenza −10, perché è un'inferenza
6. geocoding esterno (solo se 1-5 falliscono e c'è un indirizzo)
7. nessun match → Quarantena, motivo `comune_ambiguo`
```

Il passo 6 costa tempo e ha limiti d'uso: va usato raramente e i risultati vanno
**messi in cache permanente**. Con un servizio di geocoding gratuito basato su
OpenStreetMap si rispetta il limite di 1 richiesta al secondo e si mette in cache
tutto — con un perimetro finito, dopo poche settimane il geocoder non serve quasi più.

## 7.4 Il dizionario dei luoghi

Una tabella locale (alimentata dalle tue conferme in quarantena) che mappa
nome del luogo → comune:

| `luogo` | `comune` | `origine` |
|---|---|---|
| Villa Sottocasa | Vimercate | manuale |
| Teatro Binario 7 | Monza | manuale |
| Auditorium San Rocco | Seregno | confermato |
| Oratorio San Luigi | Concorezzo | confermato |

Cresce da sola: ogni volta che risolvi un `comune_ambiguo` in quarantena, la coppia
viene salvata qui. Dopo pochi mesi copre gran parte dei luoghi ricorrenti della tua
zona e il tasso di quarantena per località crolla.

## 7.5 Distanze: precalcolo, non calcolo a runtime

**Osservazione chiave: il perimetro è un insieme finito e stabile di comuni.**
Non ha senso calcolare la distanza per ogni evento; la distanza dipende solo dal comune.

Quindi:
1. **Una volta sola**, calcoli la matrice casa → ogni comune del perimetro
2. Scrivi `km` e `minuti` nel foglio `Perimetro`
3. A runtime è un semplice JOIN. Costo zero, nessuna dipendenza esterna, nessun
   limite di quota, funziona anche offline

**Con ~1.000 comuni il calcolo manuale è escluso.** Approccio in due passaggi:

1. **Coordinate.** L'anagrafe ufficiale dei comuni italiani fornisce l'elenco completo
   con codici ISTAT; le coordinate dei centroidi sono disponibili in dataset pubblici
   e gratuiti. Nessun geocoding uno per uno.
2. **Distanze stradali.** Un motore di routing open source basato su OpenStreetMap,
   eseguito **in locale** su un estratto della macroarea di interesse, calcola una
   matrice 1×1.000 in pochi secondi. Nessun limite di quota, nessun costo, ripetibile.
   Non usare servizi pubblici a quota limitata per 1.000 richieste.

**Approssimazione di riserva:** distanza aerea × 1,3 e velocità media 55 km/h. Per la
sola fascia C (75-100 km), dove serve solo sapere che è lontano, è ampiamente
sufficiente ed evita di installare qualsiasi cosa.

**La fascia si deriva da `km`** e va scritta nel foglio `Perimetro`:
A ≤ 50 km, B ≤ 75, C ≤ 100 km; oltre 100 fuori perimetro. Override manuale sempre possibile.

Aggiornamento: solo quando cambi casa o modifichi le soglie delle fasce.

**Nota:** i minuti sono un valore *medio*, non trafficoaware. Per l'uso previsto
(decidere se un evento è raggiungibile) è ampiamente sufficiente.

## 7.6 Deduplica

Lo stesso evento arriva tipicamente da 2-4 fonti. Tre livelli, in ordine.

### Livello 1 — chiave esatta
`dedup_key` da [03](03-modello-dati.md#33-identità-dellevento). Copre la maggioranza
dei casi facili, costo nullo.

### Livello 2 — hash percettivo dell'immagine
Se due candidati hanno la stessa locandina (distanza di Hamming del pHash ≤ 8), sono
lo stesso evento. Punto. È il criterio più forte disponibile, perché la locandina
è letteralmente lo stesso file che gira tra i canali.

### Livello 3 — similarità fuzzy
Solo tra candidati con **stessa data e stesso comune** (blocking: riduce i confronti
da N² a poche decine):

```
score = 0.6 × similarità(titolo_normalizzato)     # token_set_ratio
      + 0.2 × similarità(luogo)
      + 0.2 × sovrapposizione(organizzatore)

score ≥ 0.85          → duplicato certo, merge automatico
0.70 ≤ score < 0.85   → quarantena, motivo possibile_duplicato
score < 0.70          → eventi distinti
```

Attenzione: eventi diversi nello stesso posto e nello stesso giorno esistono davvero
(due spettacoli, due concerti). Il blocking per data+comune non basta da solo: serve
la soglia sul titolo.

### Regole di merge

Quando due candidati si fondono, per ogni campo vince il valore proveniente dalla
fonte con **tier più basso** (T0 batte T3), a parità di tier quello con confidenza
maggiore, a parità di confidenza il più recente. `fonti` accumula tutti i `source_id`.
Il `url` primario è quello della fonte vincente; se una fonte ha l'immagine e le altre
no, l'immagine si tiene comunque.

## 7.7 Filtro di perimetro e di interesse

Applicato dopo la normalizzazione:

- `comune` non in `Perimetro` con `attivo = sì` → scarta silenziosamente
- `km > 100` → scarta (fuori perimetro)
- `tipologia` con `attiva = no` → scarta
- `data_fine < oggi − giorni_archiviazione` → archivia

**Nessun limite superiore sulla data.** Se oggi annunciano un evento tra 180 giorni,
va conservato: le sagre storiche e i grandi festival si annunciano con mesi di
anticipo, ed è proprio l'informazione che difficilmente ritroveresti da solo.
L'evento resta nel foglio `Eventi` (dal 2026-09-10 un unico foglio con tutte
le righe attive, non più diviso in una vista a 21 giorni più `Eventi_estesi`
— vedi [03-modello-dati.md](03-modello-dati.md#31-struttura-del-google-sheet)).

Tre distinzioni che vanno tenute separate, perché nella prima versione di questi
documenti erano collassate in un unico parametro `finestra_giorni`:

| Concetto | Valore | A cosa serve |
|---|---|---|
| **Finestra di raccolta** | **nessun limite** | Qualsiasi evento futuro trovato viene conservato |
| **Orizzonte di espansione** | 120 giorni | Quante occorrenze generare da una `Serie` ricorrente. **Deve** essere limitato, o "prima domenica del mese" genererebbe righe all'infinito |
| **Vista principale** | 21 giorni, fasce A-B | Cosa vedi aprendo il foglio |

L'unico controllo sulla data lontana è di **sanità**, non di interesse: una data oltre
i 2 anni è quasi certamente un errore di estrazione (anno letto male su una locandina)
e va in quarantena, non scartata.

## 7.8 Gestione degli eventi che spariscono

Se un evento presente in `Eventi` non viene più visto da nessuna fonte per 3 run
consecutivi **e** manca meno di una settimana alla data, potrebbe essere stato
annullato — oppure la fonte semplicemente non lo ripubblica più (caso molto più
frequente).

Comportamento prudente: **non rimuovere mai automaticamente**. Marca la riga con
`ultimo_visto` vecchio e, se vuoi, un'evidenziazione condizionale nel foglio.
La decisione resta tua.
