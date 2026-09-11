# 13 — Audit del dataset esistente

> Documento storico: analizza il workbook **ereditato** dal tentativo
> precedente, prima che venisse bonificato. Il dataset descritto qui non è
> più quello in uso — è stato importato, corretto e integrato nel database
> reale del progetto (vedi [CRONACA.md](../CRONACA.md) per il dettaglio della
> bonifica). Resta valido come riferimento delle classi di errore trovate e
> delle regole di bonifica che ne sono derivate (§13.4, tuttora implementate
> in `src/bonifica_social.py`).

Analisi del workbook **Perimetro Eventi** (fogli `Perimetro`, `Comuni`, `ProLoco`,
`CompagnieTeatrali`, `Concerti`, `Feste`, `Social`, `ElenchiEventi`).

Il dataset è un buon punto di partenza, ma contiene **difetti sistematici** che
spiegano gran parte del fallimento precedente. Vanno corretti prima di costruire
qualsiasi cosa sopra: sono la causa a monte, non un dettaglio di pulizia.

---

## 13.1 Il perimetro reale

| | |
|---|---|
| **Casa** | Calosso (AT), Langhe/Monferrato |
| **Estensione nel file** | fino a ~140 km / ~105 minuti |
| **Estensione confermata** | **tagliata a 100 km** |
| **Comuni dopo il taglio** | ~1.200-1.400 |

Distanze di riferimento verificate: Asti 15,7 km · Acqui Terme 29,6 km ·
Alba ~30 km · Alessandria ~48 km.

### Fasce confermate

| Fascia | Soglia | Comuni (stima) |
|---|---|---|
| **A** | ≤ 50 km | ~400 — include Alba, Acqui, Alessandria e tutto il raggio |
| **B** | 50-75 km | ~300 |
| **C** | 75-100 km | ~500 |
| — | > 100 km | fuori perimetro |

Il taglio a 100 km elimina circa 800-1.000 comuni (Milano, Pavia, Genova, la coda
lombardo-emiliana) da cui realisticamente non saresti mai andato a un evento.

⚠️ **Conseguenza sul carico:** con la fascia A a 50 km, l'equazione "fascia A =
polling diretto" non regge più — 400 comuni sono ~800 account social, quasi 7 ore di
navigazione. Il polling diretto diventa quindi un **flag separato** su un insieme
chiuso di ~100 fonti, governato dalla resa e non dalla distanza. Vedi
[12.4](12-scala-e-copertura.md#124-l2--fasce-di-perimetro).

### Cosa tenere del file

Il valore del workbook è **il foglio `Perimetro`**: elenco comuni, codici ISTAT,
coordinate, distanze e tempi già calcolati. Quello si importa così com'è (attenzione
ai decimali con virgola tra apici: `"5,5"`), filtrando a 100 km e derivando la fascia.

Gli altri fogli sono **materiale da cui ripartire, non da fidarsi**: i nomi dei
soggetti sono utili come punto di partenza, i link vanno rifatti. La sezione 13.2
serve quindi meno come piano di bonifica e più come **elenco degli errori da non
ripetere** nella nuova discovery.

---

## 13.2 Tassonomia dei difetti riscontrati

Questi sono esempi reali presi dal foglio. Il punto non sono i singoli casi, ma il
fatto che ciascuno rappresenta una **classe** di errore ricorrente.

### A. Entità sbagliata — la categoria più grave

| Soggetto | Link assegnato | Realtà |
|---|---|---|
| Comune di Calamandrana (AT) | `comune.bussero.mi.it` | **Bussero è in provincia di Milano** |
| Pro Loco Asti | `facebook.com/prolocodiRefrancore` | Refrancore è un altro comune |
| Pro Loco Acqui Terme | `facebook.com/ProLocoOvrano` | Altro soggetto |
| Pro Loco Cavour (TO) | `facebook.com/ProLoco.Cusano.Milanino` | **Cusano Milanino, hinterland di Milano** |
| Pro Loco Cengio (SV) | `instagram.com/proloco_cogollo` | **Cogollo è in Veneto** |
| Pro Loco Valeggio (PV) | `instagram.com/proloco.valeggiosulmincio` | **Valeggio sul Mincio, VR** |
| Pro Loco Arignano | `instagram.com/prolococarignano` | Carignano ≠ Arignano |
| Pro Loco Saluzzo | `facebook.com/proloco.costigliolesaluzzo` | Costigliole Saluzzo è altro comune |
| Pro Loco Trinità | `facebook.com/prolocoterritoriocostarossa` | Altro soggetto |
| Pro Loco Montemarzino | `facebook.com/Pro-loco-Garbagna-Al-.../videos/...` | Garbagna ≠ Montemarzino |

Tutti hanno la stessa firma: **match per somiglianza del nome**, tipicamente dal
primo risultato di una ricerca. È l'errore peggiore possibile perché non è
silenzioso — **inietta attivamente eventi del comune sbagliato nel tuo elenco**,
con la distanza sbagliata, e tu non hai modo di accorgertene guardando il risultato.
Un link mancante ti fa perdere un evento; un link sbagliato te ne fa vedere uno falso
e ti fa perdere quello vero.

Nel campione esaminato, **circa un link social su cinque** ricade in questa categoria
o nella successiva.

### B. URL che non sono profili

`facebook.com/sharer/sharer.php` · `facebook.com/plugins/video.php` ·
`facebook.com/profile.php` · `facebook.com/story.php` ·
`twitter.com/intent/tweet?text=...`

Sono i **widget di condivisione** presenti in ogni pagina. L'estrattore ha preso il
primo link `facebook.com` trovato nell'HTML senza distinguere tra "link al profilo" e
"pulsante condividi". Errore classico e facilissimo da filtrare.

### C. Deep link invece del profilo

`/events` · `/about` · `/mentions` · `/reels` · `/past_hosted_events` ·
`/photos/a.658852547836032/1931024003952207` · `/posts/2206529142988755` ·
`/videos/204654260950322`

E soprattutto, su Instagram: **`instagram.com/p/DRHIBFfDZfV`** — che non è un profilo
ma il permalink di un singolo post. Compare in una quota consistente della colonna
Instagram (Montiglio, Coazzolo, Mombercelli, Loazzolo, Cervasca, Olivola, Moncrivello,
Chianocco, Carpignano Sesia, Verrua Po, Roppolo, Castellino Tanaro…). Come fonte
ricorrente è inutilizzabile.

Recuperabile però: da un post permalink si risale all'autore, e quello è il profilo
giusto. Vale la pena farlo in fase di bonifica invece di buttare la riga.

### D. Concatenazione di stringhe

```
facebook.com/www.comune.porte.to.it26/ita/rss.aspx41https://www.facebook.com/
borgosandalmazzo526374https://www.youtube.com/channel/UC7Xi...8597https://t.me/...
```

Bug di parsing conclamato. Notevole: dentro c'è anche un **canale Telegram**
(`t.me/VisitBorgoSanDalmazzo_bot`), che è esattamente il tipo di fonte a costo zero
raccomandata in [05](05-social-locandine.md#54-i-due-canali-alternativi) — e si è
perso nella spazzatura.

### E. Nomi che non sono nomi

`"Vai ai contenuti"` · `"Pro Loco"` · `"ProLoco"` · `"Associazioni - Pro Loco"` ·
`"CALENDARIO MANIFESTAZIONI COMUNALI DELLA PRO LOCO"` · `"50 anni della Proloco
Pareto"` · `"T. Pro Loco Vigone"` · `"Festa Pro Loco Tramonti in terrazza _ Venerdì 7
Agosto 2026 dalle ore 20:00 *Info e prenotazioni: 333.8866972"`

Testo di link o intestazioni di pagina presi come denominazione dell'ente. Cosmetico
di per sé, ma diventa sostanziale quando il nome viene usato per il matching di
entità: `"Vai ai contenuti"` non matcherà mai nulla.

### F. Segnali di errore sistematico nella pipeline

| Osservazione | Frequenza | Diagnosi |
|---|---|---|
| `sitemap=NON_DISPONIBILE: HTTPStatusError` | maggioranza | Non è credibile che quasi nessun comune abbia una sitemap. Molto probabilmente **User-Agent bloccato** o percorso sbagliato. Da ritestare con UA diverso |
| `proloco=NON_TROVATA_SUL_SITO_COMUNALE` | quasi sempre | La strada "trova la Pro Loco dal sito comunale" **non ha praticamente mai funzionato**. Le Pro Loco presenti vengono tutte da ricerca esterna |
| `instagram_social=NO` nel foglio `Comuni` | quasi sempre | La discovery Instagram dei comuni ha resa nulla. O i comuni non ce l'hanno, o il metodo non funziona: va distinto |
| `Accesso vietato da twitter.com/robots.txt` | ricorrente | Il crawler **rispetta robots.txt** (corretto) ma stava seguendo link di condivisione Twitter (vedi difetto B) |
| `notfound.municipiumapp.it` come sito di San Marzano Oliveto | — | Placeholder 404 di una piattaforma, salvato come se fosse il sito |

---

## 13.3 Il segnale più utile del dataset

**`sitemap=OK` correla fortemente con `fonti_evento` alto.**

| Comune | sitemap | fonti_evento |
|---|---|---|
| Serravalle Scrivia | OK | 49 |
| Pasturana | OK | 46 |
| Neive | OK | 22 |
| Murello | OK | 10 |
| Casalgrasso | OK | 7 |
| …la maggior parte con `HTTPStatusError` | | 0-3 |

Questo dice che **le fonti si dividono in due popolazioni**, non in mille casi
particolari: quelle su una piattaforma che espone struttura (sitemap, pagine evento
regolari) e quelle no. È la conferma empirica della leva L3
([12](12-scala-e-copertura.md#125-l3--adattatori-per-famiglia-di-piattaforma)).

Ci sono anche indizi diretti della piattaforma: il dominio `municipiumapp.it` e la
struttura di URL ricorrente (`/vivere-il-comune/luoghi/…`, `/novita/…`, `/eventi/…`)
sul pattern `comune.NOME.PROV.it`. **Il fingerprinting va fatto per primo**: se una
manciata di piattaforme copre la maggioranza dei comuni, un pugno di adattatori
risolve il problema che mille parser non risolvevano.

---

## 13.4 Regole di bonifica

### Livello 1 — sintattico, automatico, nessun dubbio

```
SCARTA se l'URL corrisponde a:
    facebook.com/(sharer|plugins|profile\.php|story\.php|dialog|login)
    twitter.com/intent/
    .*notfound.*
    qualsiasi URL con più di un "https://" al suo interno

NORMALIZZA:
    facebook.com/{handle}/(events|about|mentions|reels|photos|videos|
                           posts|past_hosted_events)/...  →  facebook.com/{handle}
    it-it.facebook.com | m.facebook.com  →  www.facebook.com
    instagram.com/{handle}/(reels|tagged)  →  instagram.com/{handle}

MARCA per risoluzione:
    instagram.com/p/{id}      → risalire all'autore del post
    facebook.com/{solo cifre} → ID profilo valido, da risolvere in handle
    facebook.com/groups/{id}  → è un GRUPPO, non una pagina: modello di
                                accesso diverso, va in una categoria a sé
```

### Livello 2 — coerenza di entità, il controllo che mancava

Hai un elenco di 2.000+ nomi di comune. Usalo al contrario:

```
per ogni fonte con comune assegnato C e handle H:
    se H contiene il nome normalizzato di un comune DIVERSO da C
       che esiste in Perimetro
    → ERRORE QUASI CERTO, metti in quarantena
```

Questa singola regola, a costo zero, intercetta Refrancore, Ovrano, Cusano Milanino,
Carignano, Costigliole Saluzzo, Cogollo, Valeggio sul Mincio e Bussero — cioè
l'intera categoria A.

Controlli complementari:
- **Sovrapposizione di token** tra nome comune e handle sotto una soglia → sospetto
- **Provincia nel dominio**: `comune.calamandrana.at.it` atteso, `comune.bussero.mi.it`
  incoerente con provincia AT → errore
- **Verifica incrociata sulla pagina**: la bio o la descrizione del profilo cita il
  comune assegnato? Un controllo alla volta, solo sulle fasce A e B

### Livello 3 — manuale, solo dove serve

Dopo i livelli 1 e 2, la lista da guardare a mano sarà nell'ordine delle **decine di
righe per la fascia A** e forse due-trecento per la B. Fattibile in una sera. La
fascia C e D non si bonificano a mano: si tengono i link che passano i controlli
automatici e si accetta il resto.

**Ordine di lavoro: `polling_diretto`, poi fascia A, poi basta.** Bonificare la fascia C
è tempo speso su comuni dove non andrai comunque.

---

## 13.5 Cosa è già buono nel dataset

Va detto, perché è la parte da cui partire.

**Gli aggregatori sono già quelli giusti** (foglio `ElenchiEventi`). In particolare:

- **PiemonteItalia** — portale istituzionale regionale. Da verificare per primo se
  espone dati aperti o API: un solo endpoint potrebbe coprire l'intera fascia C e D
  e buona parte della B.
- **VisitLMR** (Langhe Monferrato Roero) — copre **esattamente** l'area di casa tua.
  Potenzialmente la fonte a resa più alta dell'intero progetto per le fasce A e B.
- **VisitPiemonte**, **Sagr.it**, **GuidaTorino**, **TorinoGiovani**.

Questi cinque-sei endpoint, se funzionano, valgono più di duemila fonti comunali.
Confermano l'ordine di priorità della [roadmap](10-roadmap.md): aggregatori prima
di tutto il resto.

**Il foglio `Social`** contiene già `Sagre Piemonte` e `SagreinPiemonte` — pagine e
gruppi aggregatori tematici, ottimi candidati per il feed invertito. Nota: uno è un
**gruppo** Facebook, che ha un modello di accesso e una qualità del contenuto diversi
da una pagina; vanno tenuti come categoria separata.

**Le distanze sono già calcolate** (`DistanzaKm`, `DurataStimataMinuti`, `DataCalcolo`),
con coordinate e codici ISTAT. Il lavoro di [07](07-normalizzazione-geo-dedup.md#75-distanze-precalcolo-non-calcolo-a-runtime)
è già fatto. Unica accortezza: i decimali usano la **virgola** e sono racchiusi tra
apici (`"5,5"`); vanno convertiti in fase di import o produrranno silenziosamente
valori nulli.

**I fogli tematici** (`Feste`, `CompagnieTeatrali`, `Concerti`) sono l'intuizione
giusta ma sono **quasi vuoti**: 2 feste, 1 artista. Vanno popolati, e sono ad alta
resa perché una sagra storica come la Fiera del Rapulè ha sito, Facebook e Instagram
propri e ricorre ogni anno — cioè è esattamente una **serie** nel senso di
[07](07-normalizzazione-geo-dedup.md#79-ricorrenze-espansione-in-occorrenze).

Nota su `CompagnieTeatrali`: un URL punta a un **PDF** (`paesaggieoltre2026.pdf`) e
un altro alla pagina di una singola stagione (`…stagione-2025-2026/`). Il primo
richiede l'estrazione da PDF — che il tuo estrattore multimodale gestisce già, un
cartellone in PDF non è diverso da una locandina. Il secondo **andrà a scadere ogni
anno**: gli URL con l'anno dentro vanno marcati come tali e ricontrollati a settembre.

---

## 13.6 Conseguenze sul piano

1. **Aggiungere una Fase 0.5 di bonifica**, tra la validazione e la costruzione. Non è
   opzionale: costruire sopra link che puntano a Bussero e a Cusano Milanino produce
   un elenco che sembra funzionare e non funziona.
2. **Rifare il fingerprinting delle piattaforme** con un client che non venga bloccato,
   e ritestare le sitemap. Il dato attuale non è credibile.
3. **Verificare per primi PiemonteItalia e VisitLMR.** Se espongono dati strutturati,
   metà del progetto è già fatto e il resto diventa complemento.
4. **Soglia della fascia A**: confermata a 50 km (13.1).
5. **Popolare i fogli `Feste` e `CompagnieTeatrali`**: alta resa, poco lavoro,
   e sono le fonti che restano stabili di anno in anno.
6. **Aggiungere al foglio `Fonti` le colonne di verifica**: `entita_confermata`,
   `metodo_verifica`, `data_verifica`. Un link non verificato e un link verificato
   non devono valere uguale nel calcolo della confidenza
   ([06](06-estrazione-llm.md#66-calcolo-della-confidenza-finale)).
