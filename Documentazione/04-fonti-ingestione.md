# 04 — Fonti e ingestione

## 4.1 La gerarchia a tier

Il problema *"ogni sito ha una struttura diversa"* è vero solo se guardi l'HTML.
Molti siti espongono anche un canale **strutturato** che nessuno controlla mai.

| Tier | Cosa | Costo | Affidabilità | Esempi |
|---|---|---|---|---|
| **T0** | Dati strutturati | trascurabile | altissima | iCal `.ics`, RSS/Atom, JSON-LD `schema.org/Event`, API dati aperti |
| **T1** | HTML da leggere | basso | media | Pagina "Eventi" del comune, cartellone del teatro |
| **T2** | Post social con testo | alto | bassa | Post Facebook con descrizione |
| **T3** | Solo immagine | altissimo | bassa | Locandina senza caption |

**Regola operativa:** ogni fonte parte a T3 e viene *promossa* verso il basso dalla
discovery. Ogni fonte che riesci a portare a T0 è un problema risolto per sempre.
L'obiettivo della Fase 0 è misurare quante fonti riesci a portare a T0/T1.

Aspettativa realistica in Italia, da verificare sul tuo campione:
- Comuni: molti usano CMS istituzionali con feed RSS o calendari; una parte
  significativa dovrebbe scendere a T0/T1.
- Teatri e cinema: hanno quasi sempre una pagina cartellone strutturata (T1), spesso
  con JSON-LD perché serve al SEO. I cinema in particolare espongono spesso dati
  molto puliti.
- Pro Loco e locali: prevalentemente T2/T3. Sono il problema vero.
- Portali aggregatori di sagre: T1, alta resa per fonte.

## 4.2 Discovery: il prober

Eseguito una volta per fonte (`run.py prober`, e su richiesta, es.
mensilmente).

**Esito empirico reale** (collaudato su un campione per famiglia CMS —
WordPress, Drupal, PA design system): indovinare pattern di URL fissi
(`/eventi.ics`, path standard) ha dato risultati scarsi (404/timeout su siti
comunali reali). Ciò che funziona davvero: **cercare nella homepage già
scaricata un link testuale "Eventi"** (nessuna richiesta HTTP aggiuntiva) e
seguirlo — path molto diversi da un sito all'altro
(`/vivere/eventi/`, `/vivere-comune/eventi`, ecc.), ma quasi sempre presente
in homepage. Su un campione di 10 fonti reali, 8/10 hanno prodotto una vera
pagina eventi diversa dalla homepage con questo metodo. `src/prober.py`
implementa questo approccio come strategia principale; i metodi seguenti
restano come controlli aggiuntivi, non come prima scelta:

1. **iCal** — cerca link `text/calendar` nella pagina scaricata
2. **RSS/Atom** — `<link rel="alternate" type="application/rss+xml">`
3. **JSON-LD** — scarica 2-3 pagine evento e cerca `<script type="application/ld+json">`
   con `"@type": "Event"`. Se c'è, la fonte è di fatto T0 anche se passa da HTML
   (vedi anche `run.py promuovi-jsonld`, che verifica e promuove
   automaticamente le fonti T1_html che lo espongono)
4. **Sitemap** — `/sitemap.xml`, cerca URL con pattern `/eventi/`,
   `/manifestazioni/`, `/spettacoli/`, `/cartellone/`
5. **API note** — se il dominio corrisponde a piattaforme diffuse (es.
   gestionali per comuni, sistemi di biglietteria), usa l'endpoint documentato
6. **Fallback** — resta al tier social/HTML

Il risultato va scritto nella colonna `endpoint` del foglio `Fonti`, così è
ispezionabile e correggibile a mano.

> **Vale la pena farlo anche a mano.** Per 50 fonti, mezz'ora di controllo manuale
> con "view-source" e ricerca di `ld+json` produce risultati migliori di qualsiasi
> prober automatico. Il prober serve poi a mantenerli.

## 4.3 Adattatori

Sette adattatori generici, non uno per sito.

### `ical`
Parsing standard (`VEVENT` → `SUMMARY`, `DTSTART`, `DTEND`, `LOCATION`, `DESCRIPTION`).
Nessun LLM. Solo normalizzazione.

### `rss`
Titolo + descrizione + data pubblicazione + link. **Attenzione:** la data del feed è
la data di *pubblicazione*, non dell'evento. Serve comunque l'LLM sul testo per
estrarre la data reale, ma con `context_date` valorizzato — il che rende
l'interpretazione di "sabato prossimo" molto più affidabile.

### `jsonld`
Estrae direttamente `startDate`, `endDate`, `location`, `name`, `description`.
Nessun LLM. È il tier T0 più prezioso perché arriva da pagine HTML normali.

### `html`
1. Scarica la pagina indice (lista eventi)
2. `trafilatura` per rimuovere menù, footer, cookie banner
3. Se il testo ripulito contiene ≥ 2 pattern di data → passa all'estrattore
4. Segue **sempre** i link di dettaglio quando trova un prefisso di path
   dominante (non solo come fallback quando la lista è povera), con un limite
   di 15 link per fonte per run; estrae anche `og:image` per la locandina
5. Due adattatori dedicati aggiuntivi coprono le famiglie di template più
   diffuse tra i comuni (vedi [12-scala-e-copertura.md §12.5](12-scala-e-copertura.md#125-l3--adattatori-per-famiglia-di-piattaforma)):
   `jsonld` (template ComWeb/ePublic con schema.org/Event) e
   `pa_design_system` (template AGID, markup `.card-wrapper`)

Nessun selettore CSS specifico per sito nell'adattatore generico. Se una fonte
richiede selettori custom fuori da queste due famiglie, è un segnale che la
resa non giustifica lo sforzo.

**Rendering JavaScript:** solo se il testo ripulito risulta praticamente vuoto e la
fonte è in `polling_diretto`. Playwright headless costa 3-10 secondi per pagina e va usato con
parsimonia. Da valutare come flag per-fonte nel foglio.

### `social`
Vedi il documento dedicato [05](05-social-locandine.md).

### `email`
IMAP su una casella dedicata. Molto sottovalutato, vedi [05](05-social-locandine.md#54-i-due-canali-alternativi).

### `telegram`
API bot ufficiale, gratuita e stabile. Vedi [05](05-social-locandine.md#54-i-due-canali-alternativi).

## 4.4 Portali aggregatori: la fonte a resa più alta

Un singolo portale che copre 30 comuni vale 30 fonti comunali. Vanno cercati e messi
in `polling_diretto`:

- Portali nazionali/regionali di **sagre e feste paesane** (ne esistono diversi,
  con copertura variabile per regione)
- Portali **turistici regionali e provinciali** — spesso hanno dati aperti o feed
- Circuiti di **cinema** (le programmazioni sono quasi sempre in formato strutturato)
- Circuiti **teatrali regionali** e reti di teatri
- Piattaforme di **biglietteria** filtrate per zona
- Sezione **Eventi** delle piattaforme social (utile ma con gli stessi problemi di
  accesso descritti in [05](05-social-locandine.md))

Sono anche la copertura di riserva quando i social falliscono: se lo stesso evento
arriva dal portale, non ti serve la locandina Facebook.

## 4.5 Politica di accesso responsabile

Per i siti web (non social):

- Rispetta `robots.txt`
- User-Agent identificabile e onesto, con un contatto
- Max 1 richiesta ogni 2-3 secondi per dominio, mai in parallelo sullo stesso host
- `If-Modified-Since` / `ETag` sempre
- Cache locale delle pagine per almeno 24h
- Nessun tentativo di aggirare paywall, captcha o protezioni anti-bot

Uso strettamente personale, nessuna ridistribuzione. Vedi [11](11-rischi-decisioni.md).

## 4.6 Frequenze di aggiornamento

Non ha senso controllare tutto ogni giorno.

| Tipo fonte | Frequenza | Motivo |
|---|---|---|
| Portali aggregatori | giornaliera | Alta resa, basso costo |
| T0 (ical/rss/jsonld) | giornaliera | Costo trascurabile |
| Teatri, cinema | settimanale | Programmazione pubblicata a blocchi |
| Comuni (T1) | 2-3 volte/settimana | Aggiornamenti lenti |
| Feed social (tutti gli account seguiti) | quotidiano | Una sessione copre tutto |
| Polling diretto (~100 fonti) | 2 volte/settimana | Costo alto, insieme chiuso |
| Fonti dormienti | ridotta, **mai azzerata** | Vedi 4.7 |
| Fonti rotte (errore persistente) | sospese | Vedi 4.8 |

**Modulazione stagionale:** le sagre si concentrano in primavera-estate, la stagione
teatrale in autunno-inverno. La colonna `frequenza` può essere fatta variare dal
sistema in base alla resa storica *nello stesso periodo dell'anno precedente* —
informazione che hai in `Archivio`. Vedi 4.7: a questa scala non è
un'ottimizzazione di v2, è il meccanismo che rende gestibili le fonti dormienti.

---

## 4.7 Fonti dormienti ≠ fonti inutili

Una Pro Loco che pubblica **solo** per la sagra di luglio è silenziosa undici mesi
all'anno e poi produce l'evento più importante del suo comune. Una fonte che non dà
risultati da 60 giorni non è una fonte da disattivare: è una fonte **dormiente**, e
disattivarla significa garantirsi di perdere esattamente l'evento per cui era stata
inserita.

**Regola: il silenzio non disattiva mai una fonte.** Il silenzio modula la frequenza,
e lo fa in modo asimmetrico.

### Finestra di attenzione stagionale

`Archivio` sa che l'anno scorso quella Pro Loco ha pubblicato tra il 10 e il 30 giugno
per una sagra del 12 luglio. Da questo si deriva, per ogni fonte, una **finestra di
attenzione**: il periodo in cui quella fonte storicamente si sveglia.

```
per ogni fonte:
    eventi_storici = Archivio.eventi(fonte, ultimi 3 anni)

    se eventi_storici non è vuoto:
        per ogni evento passato:
            finestra = [data_evento − 60gg, data_evento + 5gg]
        dentro la finestra   → frequenza alta (2-3 volte/settimana)
        fuori dalla finestra → frequenza bassa (ogni 2-3 settimane)

    se eventi_storici è vuoto (fonte nuova o mai produttiva):
        frequenza di base: ogni 2-3 settimane, tutto l'anno
        MAI zero
```

Il margine di 60 giorni prima copre l'anticipo tipico con cui si annuncia una sagra;
i 5 giorni dopo servono a intercettare rinvii e repliche.

**Effetto:** una fonte dormiente costa 20-25 visite l'anno invece di 150, ma nel
momento giusto è controllata come una fonte di prima fascia. È il compromesso corretto
tra costo e copertura, e non richiede alcuna decisione manuale.

### Il floor: nessuna fonte scende sotto la frequenza minima

Anche la fonte più silenziosa del perimetro va comunque visitata almeno una volta ogni
2-3 settimane, per tre motivi: le sagre cambiano data, nascono eventi nuovi, e una
fonte mai visitata non accumula lo storico che serve a calcolarne la finestra.

### Il caso social è ancora più semplice

Con la lettura invertita del feed ([12](12-scala-e-copertura.md#123-l1--inversione-del-feed-social-))
una fonte social dormiente **non costa nulla**: l'account resta seguito e, il giorno
in cui pubblica, il post arriva nel feed come tutti gli altri. Non c'è alcun motivo
per smettere di seguire una Pro Loco silenziosa.

Questo è un vantaggio non ovvio dell'inversione del feed: **elimina del tutto il
compromesso tra copertura e costo per le fonti a bassa frequenza di pubblicazione** —
che sono la maggioranza assoluta delle Pro Loco.

---

## 4.8 Fonti rotte: qui la sospensione ha senso

Diverso è il caso della fonte che **non risponde**. Qui non c'è informazione da
attendere: c'è un problema da segnalare. Ma va graduato per tipo di errore.

| Tipo | Esempi | Comportamento |
|---|---|---|
| **Transitorio** | timeout, 5xx, DNS momentaneo | Retry al run successivo. Nessuna conseguenza sotto i 7 giorni |
| **Blocco / limite** | 403, 429, captcha | **Backoff lungo** (7, 14, 30 giorni), mai disattivazione: spesso è temporaneo o dipende dal tuo ritmo |
| **Permanente** | 404 stabile, dominio scaduto, sito dismesso | Dopo **14 giorni consecutivi** → stato `rotta` + segnalazione |
| **Struttura cambiata** | risponde 200 ma non si estrae più nulla da una fonte prima produttiva | Segnalazione **senza** sospensione: va guardata a mano |

Due precisazioni che contano:

- **Si contano i giorni, non i run.** Una fonte visitata ogni 3 settimane
  raggiungerebbe 5 errori consecutivi dopo quattro mesi: contare i tentativi produce
  soglie senza senso su fonti a bassa frequenza.
- **`rotta` non è `disattivata`.** La fonte resta nel foglio, con lo stato visibile, e
  viene comunque ritentata una volta al mese: i siti dei comuni tornano online, i
  domini vengono rinnovati, le sezioni eventi vengono ricostruite. La riattivazione
  è automatica al primo successo.

L'unica vera disattivazione definitiva la decidi tu, a mano, quando constati che il
soggetto non esiste più.
