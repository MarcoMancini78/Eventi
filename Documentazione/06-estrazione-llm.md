# 06 — Estrazione con LLM

## 6.1 Ruolo dell'LLM

L'LLM fa **una cosa sola**: dato un artefatto (testo e/o immagini) più un po' di
contesto, restituisce zero o più eventi in JSON.

Non decide se l'evento è nel perimetro, non calcola distanze, non deduplica, non
sceglie se pubblicare. Tutta la logica deterministica resta fuori — è più affidabile,
non consuma quota e si può correggere senza rilanciare l'estrazione.

**Corollario importante:** poiché l'output grezzo viene salvato (tabella
`extractions`), quando cambi le regole di normalizzazione puoi riprocessare mesi di
dati a costo zero.

## 6.2 Schema di output

Unico per tutti i tipi di artefatto. L'LLM restituisce sempre un array (può essere
vuoto — una locandina può contenere un programma di 5 serate).

```json
{
  "eventi": [
    {
      "titolo": "string",
      "descrizione": "string | null",
      "tipologia": "sagra|gastronomia|degustazione|concerto|teatro|cinema|mostra|fiera|sportivo|bambini|altro",
      "data_inizio": "YYYY-MM-DD | null",
      "data_fine": "YYYY-MM-DD | null",
      "ora_inizio": "HH:MM | null",
      "ora_fine": "HH:MM | null",
      "ricorrenza": {
        "e_ricorrente": false,
        "frequenza": "settimanale|mensile|annuale|null",
        "giorni_settimana": ["SU"],
        "ordinale": 1,
        "mesi_inclusi": [1,2,3,4,5,6,7,9,10,11,12],
        "fine_dichiarata": "YYYY-MM-DD | null",
        "testo_originale": "prima domenica di ogni mese, escluso agosto"
      },
      "luogo_testuale": "string | null",
      "comune_testuale": "string | null",
      "indirizzo": "string | null",
      "prezzo": "string | null",
      "organizzatore": "string | null",
      "url_approfondimento": "string | null",
      "anno_esplicito": true,
      "confidenza": 0-100,
      "campi_incerti": ["data_fine"],
      "note_estrazione": "string | null"
    }
  ],
  "non_e_un_evento": false,
  "motivo": "string | null"
}
```

Note di progettazione:
- `comune_testuale` è ciò che c'è scritto, **non** il comune normalizzato. Il matching
  con il perimetro avviene dopo, in modo deterministico ([07](07-normalizzazione-geo-dedup.md)).
- `anno_esplicito` distingue "12 luglio 2026" da "12 luglio". Nel secondo caso l'anno
  è inferito e la confidenza sulla data va abbassata.
- `campi_incerti` è più utile della confidenza globale: permette di mandare in
  quarantena solo per il campo giusto.
- `url_approfondimento` è un link AGGIUNTIVO trovato nel testo del post (es.
  un repost con "SCOPRI IL PROGRAMMA COMPLETO: www.sito.it") — non è l'URL del
  post stesso, che resta sempre in `url` (gestito dal sistema, non dall'LLM).
  Vuoto se il testo non contiene un link esplicito, mai dedotto. Normalizza i
  domini e ha un fallback sull'URL dell'immagine remota se il link testuale
  non è utilizzabile.
- `non_e_un_evento` è la valvola di sfogo: rende esplicito il "questo è un post di
  auguri di Natale", invece di costringere il modello a inventare un evento.
- `ricorrenza` è **strutturata, non testuale**: il modello descrive il pattern con
  campi vincolati, e un convertitore deterministico ne ricava la RRULE che genera le
  occorrenze ([07](07-normalizzazione-geo-dedup.md#79-ricorrenze-espansione-in-occorrenze)).
  Far generare una sintassi formale a un LLM produce errori silenziosi; far scegliere
  tra valori enumerati no. `testo_originale` si conserva comunque, per poter
  ricontrollare a mano i casi strani.

Se il provider supporta l'output JSON vincolato a schema, va usato: elimina la classe
di errori dovuti a JSON malformato.

## 6.3 Prompt per artefatti testuali

Struttura consigliata (versionata: `prompt_version` in `extractions`, così puoi
confrontare le rese di due versioni).

```
[SISTEMA]
Estrai eventi pubblici da testi italiani. Rispondi SOLO con JSON valido
conforme allo schema. Nessun testo prima o dopo.

REGOLE
1. Estrai solo eventi PUBBLICI con una data futura o in corso.
   Non estrarre: resoconti di eventi passati, ringraziamenti, auguri,
   avvisi amministrativi, offerte commerciali, post di sole foto.
1b. NON estrarre la programmazione cinematografica ordinaria di sala
   (il film delle 21 al cinema, gli orari degli spettacoli, i titoli
   in cartellone). Estrai SOLO le proiezioni-evento: cinema all'aperto,
   arene estive, rassegne tematiche, proiezioni con ospite o dibattito.
   Nel dubbio: se è un film in programmazione normale, non è un evento.
2. Non inventare mai. Campo non deducibile → null.
   È molto meglio un null che un valore plausibile ma sbagliato.
3. Date: usa DATA_RIFERIMENTO per risolvere date relative
   ("sabato prossimo", "il 12"). Se manca l'anno, assumi il
   prossimo anno in cui quella data cade nel futuro e imposta
   anno_esplicito=false.
4. Evento su più giorni → data_inizio e data_fine.
   Evento di un giorno → data_fine = data_inizio.
   Evento RICORRENTE ("tutti i venerdì di luglio", "la prima domenica
   del mese") → imposta ricorrenza.e_ricorrente=true e compila i campi
   strutturati. In data_inizio metti la PRIMA occorrenza futura.
   Non elencare tu le occorrenze: le calcola il sistema.
   `ordinale` vale 1..4 per "prima/seconda/terza/quarta", -1 per
   "ultima". Se un mese è escluso ("tranne agosto"), omettilo da
   mesi_inclusi.
5. Un testo può contenere PIÙ eventi (es. programma di una rassegna):
   restituiscili tutti separatamente.
6. comune_testuale: riporta il toponimo come scritto. Se il testo non
   indica alcun luogo, usa COMUNE_FONTE.
7. tipologia: scegli dalla lista. Nel dubbio "altro".
8. Confidenza: 90+ se tutto è esplicito; 60-80 se hai inferito
   qualcosa; <60 se il testo è ambiguo.

[UTENTE]
DATA_RIFERIMENTO: 2026-08-21
FONTE: Pro Loco Vimercate (proloco)
COMUNE_FONTE: Vimercate
URL: ...
TIPOLOGIE_AMMESSE: sagra, gastronomia, ...

TESTO:
"""
...
"""
```

DATA_RIFERIMENTO di default è la data odierna (`date.today()`), corretta per
fonti T0/T1 (ical, jsonld, siti — il testo estratto è sempre "fresco", letto
allo stesso momento in cui viene pubblicato online). Per i post del feed
social (`feed_social.py`) va invece usata **la data di pubblicazione del
post**, non il giorno di lettura: un post letto giorni dopo la pubblicazione
(change detection sullo scroll cronologico) con un testo relativo ("stasera")
produrrebbe altrimenti una data sbagliata.

`feed_social._scroll_feed_e_raccogli` legge la data reale di pubblicazione e
la passa come `data_riferimento` a `estrai_da_testo`/`estrai_da_immagine`:
- **Instagram**: attributo `datetime` (ISO, assoluto) dell'elemento `<time>`
  del post — affidabile, indipendente da lingua/formato del testo relativo
  visualizzato ("6 g", "6 giorni fa").
- **Facebook**: nessun timestamp assoluto nel markup statico del feed — si
  ottiene solo con l'hover sul tooltip della data (successo empirico
  40-50%, non garantito). Quando l'hover non produce una data leggibile,
  resta il default `date.today()`.

Dettaglio della scoperta e dei casi reali osservati: [CRONACA.md](../CRONACA.md).

## 6.4 Prompt per locandine (VLM)

Alle regole precedenti si aggiungono quelle specifiche del formato grafico.

```
Questa immagine è probabilmente la locandina di un evento.

9. Leggi la struttura visiva: il testo più grande in alto è di norma
   il titolo; date e orari sono spesso in evidenza o in fondo; il luogo
   è spesso vicino a un'icona o in fondo; i loghi in basso indicano gli
   organizzatori, NON il luogo dell'evento.
10. Le locandine spesso indicano il giorno della settimana e il numero
    ("SABATO 12 LUGLIO") senza anno: usa DATA_RIFERIMENTO e verifica
    la coerenza col giorno della settimana. Se giorno e data non
    coincidono in nessun anno vicino, segnala data in campi_incerti.
11. Se la locandina contiene un PROGRAMMA con più serate/spettacoli
    datati, restituisci un evento per ciascuno.
12. Ignora testo decorativo, slogan, hashtag, sponsor.
13. Se l'immagine non è una locandina (foto, logo, grafica di auguri),
    imposta non_e_un_evento=true.

CAPTION DEL POST (può contenere informazioni assenti dall'immagine):
"""
...
"""
```

La regola 10 (coerenza giorno-della-settimana / data) è un controllo di validità
gratuito e sorprendentemente efficace: intercetta sia gli errori di lettura del
modello sia gli errori di chi ha fatto la locandina.

## 6.5 Il problema dell'anno mancante

È la fonte di errore più frequente su questo tipo di contenuti. Regola deterministica
da applicare **dopo** l'LLM, non delegata al modello:

```
se anno_esplicito == false:
    candidati = [stessa data nell'anno di DATA_RIFERIMENTO,
                 anno successivo]
    scegli il primo che cade nel futuro
    se è disponibile il giorno della settimana dichiarato:
        preferisci l'anno in cui giorno e data coincidono
        se nessuno coincide → campi_incerti += "data_inizio"
    se la data risultante è a più di limite_sanita_anni → quarantena
```

## 6.6 Calcolo della confidenza finale

Non fidarsi della sola autovalutazione del modello, che tende all'ottimismo.
Combinala con controlli deterministici:

```
confidenza_finale =
      confidenza_llm
    × peso_tier          (T0: 1.00 | T1: 0.95 | T2: 0.85 | T3: 0.75)
    × peso_affidabilita_fonte  (storico: eventi_utili / eventi_totali)
    − 15  se data non esplicita
    − 20  se il comune non trova match nel perimetro
    − 10  se manca il luogo
    − 25  se giorno-settimana e data sono incoerenti
    + 10  se lo stesso evento è confermato da un'altra fonte indipendente
```

`confidenza_finale ≥ soglia_confidenza` (default 70) → `Eventi`; altrimenti →
`Quarantena`. La soglia sta in `Config` e va tarata guardando i KPI: se in quarantena
finisce troppa roba buona, abbassala.

Il bonus per conferma multi-fonte è particolarmente efficace: due estrazioni
indipendenti che concordano sono molto più affidabili di una sola con confidenza alta.

## 6.7 Scelta dei modelli

Servono due profili di modello. Vedi [09](09-stack-costi.md) per i dettagli sui provider.

| Uso | Requisiti | Volume stimato/giorno |
|---|---|---|
| Testo | JSON affidabile, buon italiano, economico | 100-400 chiamate |
| Immagini | Multimodale, buona lettura di testo grafico | 20-100 chiamate |

Il volume rientra nelle quote gratuite se i pre-filtri fanno il loro lavoro. Se non
ci rientri, il problema non è il modello: è che stai analizzando troppo.

**Strategia a cascata (v2):** modello piccolo/veloce per un pre-giudizio binario
("questo testo contiene un evento futuro? sì/no"), modello migliore solo sui positivi.
Riduce ulteriormente il consumo sui contenuti di scarto.

## 6.8 Controlli di sanità sull'output

Prima di accettare qualsiasi estrazione:

- JSON valido e conforme allo schema (altrimenti: 1 retry, poi scarto con log)
- `data_inizio` ≤ `data_fine`
- `data_inizio` compresa tra oggi − 1 e oggi + `limite_sanita_anni` (nessun limite di interesse: vedi [07.7](07-normalizzazione-geo-dedup.md#77-filtro-di-perimetro-e-di-interesse))
- `titolo` tra 3 e 200 caratteri, non composto solo da emoji o punteggiatura
- `tipologia` presente nella tassonomia
- Massimo `Config.max_eventi_per_artefatto` eventi per artefatto (oltre →
  probabile allucinazione, in quarantena). Non un numero fisso nel codice:
  default 60, alzato da un originario 20 dopo che un vero cartellone
  stagionale (46 spettacoli reali, verificati) veniva scartato per intero

Ogni violazione va loggata **per fonte**: se una fonte produce sistematicamente
output non validi, è un difetto della fonte o dell'adattatore, non del modello.

## 6.9 Miglioramento continuo

Le correzioni che fai in `Quarantena` e in `Eventi` (righe con `stato = corretto`)
sono dati di addestramento gratuiti:

1. Salva la coppia (artefatto originale, estrazione corretta)
2. Seleziona 5-10 casi rappresentativi dei tuoi errori tipici
3. Inseriscili come esempi few-shot nel prompt, per **tipo di fonte**
   (le locandine delle Pro Loco della tua zona hanno convenzioni ricorrenti)
4. Confronta la resa tra `prompt_version` diverse sui KPI

Questo ciclo è ciò che porta il sistema dal 60% all'80% di copertura. Va previsto
dall'inizio nella struttura dati, anche se lo attivi al terzo mese.
