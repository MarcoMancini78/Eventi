# Cronaca — Aggregatore Eventi Locali

> Archivio storico, append-only. Contiene la narrazione dettagliata di bug
> trovati/corretti, collaudi, "giri" di debug e decisioni prese in corsa.
> **Non è la fonte per capire lo stato attuale del progetto** — per quello
> vedi [STATO-PROGETTO.md](STATO-PROGETTO.md). Consulta questo file solo se
> ti serve capire *perché* una scelta è stata presa o *come* si è arrivati
> a un certo comportamento del codice.
>
> Copertura: dall'avvio del progetto (2026-08-22) al 2026-08-27 (fine M10).
> Il periodo successivo (2026-08-28 → oggi) non ha una cronaca dettagliata
> equivalente: consulta `git log` nella cartella `eventi/` per i dettagli
> tecnici dei commit più recenti.

Ultimo aggiornamento di questa cronaca: 2026-08-27

## ⚠️ Documenti mancanti nella cartella Documentazione

L'indice in [00-README.md](Documentazione/00-README.md) elenca 15 documenti, ma solo 12 file esistono. **Mancano: 01 (requisiti), 02 (architettura), 05 (social e locandine), 09 (stack e costi)**. Non sono stati persi in questa sessione: risultano assenti fin dall'inizio. Le decisioni che li riguardano sono state prese consultando i doc esistenti (che li citano e li riassumono in parte, es. 06.7 per la scelta del modello) — se servono i documenti completi, vanno scritti da zero o recuperati da un'altra fonte.

## ✅ TeatroAlessandria, TeatroCuneo — collaudati end-to-end (2026-08-25)

- **TeatroAlessandria**: primo lancio → 0 eventi pubblicati, causa **scoperta e corretta**: l'LLM aveva estratto correttamente **46 spettacoli reali e plausibili** (nomi noti, date coerenti ott 2026-mag 2027, nessun duplicato) da un unico cartellone stagionale, ma il limite anti-allucinazione fisso (`_MAX_EVENTI_PER_ARTEFATTO = 20`, 06.8) scartava l'intera risposta. Non era un'allucinazione: un vero cartellone teatrale annuale può avere più eventi di quanti previsti dalla soglia. **Corretto**: soglia spostata in `Config.max_eventi_per_artefatto` (default 60, commit `6b7b5e2`), coerente con 15.1.1 ("nessun numero magico"). Rilanciato: **46/46 eventi pubblicati correttamente**.
- **TeatroCuneo**: 0 eventi pubblicati, **motivo verificato e legittimo** (non un bug): l'LLM ha classificato l'intera pagina come `non_e_un_evento=True` con motivazione corretta — "tutti gli spettacoli appartengono alla stagione 2025/2026, terminata ad aprile 2026, antecedenti alla data di riferimento (25 agosto 2026)". Comportamento atteso (filtro correttamente gli eventi passati).

Dati di test ripuliti da SQLite dopo la verifica (artifacts, extractions, events, event_sources per entrambe le fonti).

## 📌 Da bonificare più avanti: dati anagrafici

- **Bormida (SV)** — ✅ **corretto 2026-08-23 sera**: la riga `proloco-bormida-instagram` aveva l'handle di Monastero Bormida (AT), errore di entità del dataset ereditato. Spostata in `stato='quarantena'` con nota esplicativa, non verrà seguita finché non si trova l'handle vero (se esiste) o si elimina la riga.
- **Montà** — ✅ **falso allarme, chiuso 2026-08-25**: verificato a fondo (byte grezzi del CSV, decodifica UTF-8 completa, valore reale in SQLite via `.encode("utf-8")`) che il nome è correttamente `Montà` (byte `0xc3 0xa0`, UTF-8 valido per "à") sia nel CSV originale sia in `comuni.comune`/`comuni.alias`. Il carattere `�` che appariva era solo un artefatto di visualizzazione della console Windows (codepage 437, non supporta accenti) — mai un dato realmente corrotto, confermato dall'utente di averlo visto solo in terminale/log, mai su Sheets o nell'app. Nessuna correzione necessaria.

## Follow sui social dedicati — stato: codice pronto, nessuna azione reale eseguita

Aggiornamento 2026-08-23 sera: la procedura è implementata, ma **non è mai stata lanciata contro Facebook/Instagram veri**. L'utente ha già provato `--dry-run` e giustamente segnalato che non chiedeva il login: era un errore nell'istruzione data, corretto di seguito.

**Fatto:**
- `src/bonifica_social.py` — bonifica dei link ereditati dal vecchio workbook, livello 1+2 di 13.4. **896 fonti pulite** (323 fascia A, 263 B, 311 C) in `coda_follow` su SQLite locale (`python run.py populate-coda-follow`, senza `--publish`: il foglio Sheets reale non è stato ancora toccato). Corretto anche un bug di estrazione handle sugli URL `facebook.com/people/Nome/ID` (restituivano `people` invece del nome).
- `src/follow.py` — logica di stato/circuito interamente testata senza browser (11 test): precondizioni, limite giornaliero (ora **50**), intervallo minimo 45 min tra lotti, apertura del circuito su segnale di blocco. L'interazione Playwright vera è isolata e non è mai stata eseguita.
- `run.py login --platform=X` — **nuovo comando dedicato al login**, aggiunto dopo che l'utente ha segnalato che `--dry-run` non apriva il browser. Causa: `follow_batch` ritorna prima di aprire qualunque sessione quando `dry_run=True` — il dry-run è fatto apposta per non toccare nulla, quindi non è mai stato un modo valido per il primo login. `run.py login` risolve aprendo il browser solo sulla pagina di login e aspettando che l'utente lo chiuda dopo aver fatto accesso.
- `run.py follow --platform=facebook|instagram [--n] [--dry-run]` pronto (il dry-run resta solo-lettura, corretto).

**Facebook: login con account personale, non un secondo profilo.** L'account dedicato è una **Pagina** (`facebook.com/profile.php?id=61593736766094`) gestita dal profilo personale dell'utente (14.2 opzione A) — il login su `run.py login --platform=facebook` va fatto con le credenziali personali. Il codice ora gestisce automaticamente il passaggio: prima di ogni sessione di follow, `follow.py` naviga alla Pagina e verifica di essere "loggati come Pagina" (indicatore "Gestisci"), non come profilo personale — se non riesce a confermarlo, si ferma senza eseguire alcun follow (mai il rischio di seguire dal profilo personale, 14.1). URL configurabile via `FACEBOOK_PAGE_URL` in `.env` se dovesse cambiare.

**Fatto (2026-08-23 sera):**
- ✅ `run.py login --platform=instagram` eseguito dall'utente: login manuale completato, sessione salvata in `data/sessions/instagram_profile/`.
- ✅ `run.py login --platform=facebook` eseguito dall'utente (con le credenziali personali, essendo la Pagina collegata al profilo): login completato, sessione salvata in `data/sessions/facebook_profile/`.

**Fatto (2026-08-23 sera, continua):**
- ✅ `run.py follow --platform=instagram --dry-run` eseguito: elenco di 10 Pro Loco fascia A, tutti gli handle puliti (nessun `people`, nessun falso positivo di entità).
- ⚠️ **Primo follow reale tentato** (`run.py follow --platform=instagram --n=3`, rischio accettato esplicitamente dall'utente nonostante il riscaldamento non ancora concluso): **Instagram ha mostrato un captcha sul primo candidato**. Il sistema di sicurezza ha reagito correttamente: circuito aperto, lotto interrotto immediatamente, nessun altro candidato tentato.
- 🐛 **Bug di reporting trovato e corretto**: il comando aveva stampato "Nessun candidato in coda_follow" invece di segnalare il captcha — messaggio completamente fuorviante, perché in realtà `follow_batch` ritornava una lista vuota anche quando il blocco scattava sul primo candidato del lotto. Corretto: ora l'esito del blocco è sempre visibile nell'output.
- **Stato attuale: circuito Instagram aperto fino al 2026-08-26** (72 ore da un captcha). Nessun follow ripartirà prima di allora — **per design, non va forzato né aggirato** (14.5: la tentazione di insistere dopo un blocco è il modo più rapido di perdere l'account).

**Perché non si mostra il captcha per risolverlo a mano:** l'utente ha chiesto se fosse possibile. Risposta: no, di proposito. Il doc 14.5 dice esplicitamente che non c'è modo di forzare la ripartenza se non modificando `Config` a mano, e che risolvere un captcha durante un'automazione e continuare subito è statisticamente il momento in cui gli account vengono disabilitati (conferma alla piattaforma che dietro c'era uno script). Il browser resta comunque visibile (`headless=False`) durante l'esecuzione, quindi il captcha è già osservabile mentre lo script gira, ma il flusso di follow non riparte automaticamente dopo averlo eventualmente risolto nella finestra.

**Convenzione per i follow fatti a mano (2026-08-23 sera), superata da `sync-seguiti`:** inizialmente si comunicava in chat (nome/comune/handle) e l'assistente aggiornava `coda_follow` a mano — funziona ancora, ma scomodo su tanti follow. **Sostituita da una procedura automatica**: `src/sync_seguiti.py` + `run.py sync-seguiti --platform=X` legge davvero la lista "seguiti" dalla piattaforma (sola lettura, nessun click, coerente con 14.5b "la lettura passiva è molto meno rilevabile dell'azione") e allinea `coda_follow` da solo — handle già censiti vengono marcati `seguito`, handle sconosciuti (es. consigliati dall'app, seguiti per errore) finiscono in quarantena con comune vuoto da verificare, mai scartati né attivati automaticamente.

🐛 **Bug critico trovato e corretto al primo utilizzo reale (2026-08-23, seconda sera):** `python run.py sync-seguiti --platform=instagram` è andato in crash con `AttributeError: 'function' object has no attribute 'replace'`. Causa: **`get_by_role`/`get_by_text` di Playwright non accettano una funzione lambda come parametro `name`**, a differenza di quanto assunto scrivendo il codice — serve una stringa o una `re.compile(...)`. Bug presente in 4 punti: 3 in `follow.py` (menu identità Facebook, link "Cambia", **pulsante "Segui"**) e 1 in `sync_seguiti.py` (link "Vedi il profilo"). Tutti corretti con `re.compile(pattern, re.IGNORECASE)`, verificato empiricamente con un test Playwright reale prima di considerarlo risolto.

⚠️ **Implicazione importante**: questo bug era presente anche nel primo tentativo di follow reale (quello fermato dal captcha, vedi sopra) — il pulsante "Segui" **non sarebbe mai stato trovato correttamente** nemmeno se il captcha non fosse scattato. Va ripetuto il collaudo di `sync-seguiti` ora, e quello di `follow` quando il circuito Instagram si sarà riaperto (2026-08-26).

🐛🐛 **Secondo giro di bug reali, riportati dall'utente dopo il fix precedente (2026-08-23, terza sera):**
- **Instagram**: `sync-seguiti` ha trovato **0 profili**, nonostante l'utente ne avesse seguiti diversi. Causa probabile: il codice cercava un link testuale "Vedi il profilo"/"View profile" su `instagram.com/accounts/edit/` che quasi certamente non esiste con quel wording nell'interfaccia reale — falliva **silenziosamente**, ritornando lista vuota invece di segnalare l'anomalia. **Corretto**: ora cerca l'username dal link dell'icona profilo nella barra di navigazione della home (`aria-label` contenente "profilo"/"profile"), più robusto di un testo di bottone legato a lingua/interfaccia. **Non verificato empiricamente** (a differenza del fix Facebook sotto): è un tentativo migliore, non una certezza. Se desse ancora 0 risultati, serve ispezionare l'HTML reale della pagina per trovare i selettori giusti.
- **Facebook**: `sync-seguiti` ha aperto la pagina, ma ha mostrato **i seguiti personali dell'utente**, non quelli della Pagina — l'utente ha dovuto chiudere la finestra per fermarlo. Causa trovata e confermata: `facebook_page_url + "/following"` su un URL con query string (`profile.php?id=...`) produce un URL malformato (`...?id=123/following`), e Facebook probabilmente reindirizzava altrove. **Corretto**: `_id_pagina_da_url` estrae l'ID numerico o l'handle dall'URL della Pagina e costruisce `/{id}/pages_followed_by`, il path corretto per le pagine seguite da una Pagina. Logica pura, testata in isolamento (3 nuovi test), maggiore fiducia che sia risolto rispetto al fix Instagram.

Suite completa: 82/82 test passati.

🐛🐛🐛 **Terzo giro (2026-08-23, quarta sera): entrambi i fix del secondo giro NON hanno risolto.**
- **Instagram**: ancora **0 profili trovati**. Il fix basato su `aria-label` non ha funzionato — l'assunzione sul wording era sbagliata anche questa volta, oppure la home non espone quel link nel modo previsto.
- **Facebook**: ha trovato "1 profilo" ma **sbagliato** — l'utente ha visto un errore "pagina inesistente" mentre il browser navigava, segno che `/pages_followed_by` **non è un path valido** (oggi, o per questa Pagina). Il "1 profilo" raccolto è quasi certamente uno scarto dalla pagina di errore stessa, non un dato reale.

**Cambio di approccio deciso con l'utente**: basta indovinare selettori/URL alla cieca dopo 2 tentativi falliti. L'utente ha ispezionato a mano l'interfaccia reale (browser normale, loggato) e fornito gli URL esatti:
- **Instagram**: `https://www.instagram.com/?variant=following` — nessun bisogno di conoscere lo username, molto più semplice di quanto ipotizzato.
- **Facebook**: l'URL della propria Pagina con il parametro aggiuntivo `&sk=following` (non un path separato `/pages_followed_by`, che non esiste per questa Pagina/versione dell'interfaccia).

✅ **Quarto giro (2026-08-23, quinta sera): riscritto sulla base dei dati reali, non più ipotesi.** Entrambe le funzioni di lettura semplificate: Instagram non cerca più lo username, Facebook usa `_aggiungi_parametro_query` (testata in isolamento, 2 test) invece del path sbagliato. Ripulita anche una riga spuria (`sconosciuto-facebook-help`) raccolta per errore dal tentativo precedente che aveva scambiato un link del footer di una pagina di errore per un profilo seguito. Suite completa: 81/81 test passati.

🐛 **Quinto giro (2026-08-23, sesta sera): gli URL sono giusti, ma il selettore raccoglie link da tutta la pagina, non solo dalla lista seguiti.** Le pagine si aprono correttamente stavolta (28 profili trovati su Instagram, 65 su Facebook — numeri plausibili), ma **mescolati con scarti**: voci di menu (`inbox`, `reels`, `privacy`, `terms`, `locations`, `people`), ID di sessione/CDN (`27390612760618293`, `dcykf0rlemy...`), il proprio handle/pagina raccolto per errore (`eventi.langa`, `profile.php?id=61593736766094` e le sue varianti `&sk=...`), e frammenti di query string isolati (`?fbid=...`, `?asset_id=...`). Causa: il selettore CSS attuale (`a[href^='/'][role='link']` per Instagram, `a[href*='facebook.com/'][role='link']` per Facebook) cattura **qualsiasi link della pagina**, non solo quelli dentro il contenitore/modale della vera lista.

**Pulizia intermedia già fatta**: rimossi manualmente da `coda_follow` gli scarti chiaramente non-profilo identificati a occhio (15 su Instagram, 12 su Facebook). Restano in quarantena 10 (Instagram) + 37 (Facebook) candidati plausibili non ancora verificati uno per uno (nomi come `abba_tribute_show`, `castello-reale-di-govone`, vari `proloco.*`), che potrebbero comunque contenere altri scarti minori.

✅ **Sesto giro (2026-08-23, settima sera): fix basato sull'HTML reale ispezionato dall'utente.** L'utente ha fatto F12 su un profilo vero nella lista (`prolocopriocca`) e fornito l'HTML esatto: ogni riga contiene un bottone di stato-follow ("Segui già") accanto al link al profilo — segnale assente in qualsiasi link di menu/navigazione. Riscritta l'estrazione (`_JS_RACCOGLI_RIGHE_CON_BOTTONE_FOLLOW`, eseguita via `pagina.evaluate`): trova i bottoni con testo Segui/Segui già/Follow/Following, risale il DOM fino a un link fratello, usa quello come identificatore. Applicato a entrambe le piattaforme; per Facebook aggiunta l'esclusione esplicita della propria Pagina dai risultati. **Verificato empiricamente** con Playwright reale contro un HTML fedele a quello fornito: isola correttamente `prolocopriocca` escludendo `inbox`/`reels`/il proprio profilo. Suite completa: 81/81 test passati.

**Da ricollaudare dal vivo** per confermare che il rumore sia sparito del tutto (la verifica automatica ha usato un HTML semplificato, non la pagina reale intera). Controllare in particolare che tra i "nuovi" non compaiano più voci come `inbox`/`reels`/`privacy`/query string isolate/il proprio handle.

**Settimo giro di collaudo (2026-08-23, ottava sera): il rumore è sparito, ma emersi due problemi opposti sulle due piattaforme.**
- **Facebook: sceso a 0.** L'utente ha ispezionato l'HTML di una riga vera della lista ("Proloco Callianetto") e confermato: **le Pagine seguite da una Pagina non mostrano alcun bottone di stato-follow**, a differenza di Instagram — solo un menu "Altre opzioni" (icona a tre puntini) con `aria-label="Altre opzioni per {nome}"`. Il fix del giro precedente cercava un bottone che semplicemente non esiste in questo contesto. ✅ **Corretto**: nuova strategia `_JS_RACCOGLI_RIGHE_CON_ALTRE_OPZIONI` basata su questo aria-label, verificata empiricamente contro l'HTML reale (isola correttamente `proloco.callianetto`). Suite completa: 81/81 test passati.
- **Instagram: sceso da 28 a 5 profili.** ⚠️ Non era un problema di selettore. L'utente ha verificato: **nessuno dei 5 trovati appartiene all'account dedicato** — la sessione salvata (`data/sessions/instagram_profile`) era loggata sul profilo Instagram **personale** dell'utente, non su `eventi.langa`. Causa a monte: scelta account sbagliata durante uno dei login manuali precedenti.

🐛 **Ottavo giro (2026-08-24, notte): identità mai verificata, corretto.** Il codice non aveva alcun controllo che la sessione fosse davvero quella dell'account dedicato — lo stesso rischio già mitigato per Facebook (`_assicura_identita_pagina`), ma mai applicato a Instagram. **Corretto**: nuova `follow.verifica_identita_instagram`, legge lo username reale da `instagram.com/accounts/edit/` (campo input, affidabile indipendentemente da lingua/interfaccia) e lo confronta con `Config.instagram_username` (default `eventi.langa`, configurabile via `INSTAGRAM_USERNAME` in `.env`). Se non corrisponde, si ferma con `IdentitaInstagramNonVerificataError` senza eseguire alcuna lettura o azione. Collegata sia a `follow_batch` sia a `sync_seguiti.leggi_seguiti_reali`. 5 nuovi test (oggetti finti, nessun browser). Suite completa: 85/85 test passati.

**Pulizia dati fatta**: cancellata la sessione Instagram corrotta dal filesystem (`data/sessions/instagram_profile`, mai tracciata da git) e rimosse da `coda_follow` le 5 righe raccolte per errore dal profilo personale.

⚠️ **Azione richiesta dall'utente prima di ricollaudare Instagram**: rifare il login, questa volta assicurandosi di scegliere/autenticarsi con l'account `eventi.langa` (non il proprio profilo personale):
```
python run.py login --platform=instagram
```
Al primo `sync-seguiti`/`follow` successivo, se l'account risultasse ancora sbagliato, il comando si fermerà da solo con un errore chiaro invece di raccogliere dati sbagliati in silenzio.

**Nono giro (2026-08-24/25, notte): due nuovi bug, entrambi corretti.**
- **Facebook, ancora 0 profili** nonostante l'utente vedesse la lista scorrere sullo schermo. Causa confermata dall'utente: la lista "Pagine seguite" si apre in un **modale/riquadro con scroll proprio**, non con la pagina intera. `mouse.wheel` sulla finestra non toccava affatto il contenuto del modale, che restava fermo sui primi elementi. ✅ **Corretto**: `_scroll_e_raccogli` ora individua dinamicamente i contenitori con `overflow-y` scrollabile e ne incrementa lo `scrollTop`, oltre al normale scroll di finestra. **Verificato empiricamente** con Playwright reale contro un modale simulato (3 righe, tutte raccolte correttamente, scrollTop passato da 0 a 100).
- **Instagram, errore "impossibile leggere lo username"** subito dopo la richiesta di consenso cookie. Causa: il banner cookie ritardava il caricamento del form `accounts/edit/`, e il timeout fisso di 2s non bastava ad aspettarlo. ✅ **Corretto**: `_chiudi_banner_cookie_se_presente` (cerca e chiude il banner se presente) più `wait_for_selector` al posto del timeout fisso. **Non verificabile in isolamento** (dipende dal login reale), da confermare al collaudo.

Suite completa: 85/85 test passati.

Comandi da riprovare (per Instagram, prima rifare il login con `eventi.langa` se non ancora fatto dopo il fix sull'identità):
```
python run.py login --platform=instagram   # solo se non ancora rifatto con eventi.langa
python run.py sync-seguiti --platform=facebook
python run.py sync-seguiti --platform=instagram
```

🐛 **Decimo giro (2026-08-25): Facebook ancora 0 nonostante 53 seguiti visibili sullo schermo.** L'utente ha confermato: la pagina mostra chiaramente 53 profili nella lista, lo scroll del modale funziona (visibile a schermo), ma il comando continua a restituire 0. Il fix dello scroll del giro precedente (commit `a6568e5`) NON ha risolto il problema reale, benché verificato empiricamente su un modale simulato.

Passo 1: **aggiunta una diagnostica temporanea** (`_JS_DIAGNOSTICA_FACEBOOK` in `sync_seguiti.py`, commit `2d1873c`) che si attiva automaticamente quando la raccolta risulta vuota — stampa quanti elementi `[aria-label]` esistono sulla pagina, un campione dei primi 15 valori e quelli che contengono "opzioni"/"options".

Passo 2: l'utente ha fornito l'HTML reale di una **seconda riga** della lista ("Proloco Bistagno"), diversa da quella del giro precedente ("Proloco Callianetto") — struttura identica: stesso pattern `aria-label="Altre opzioni per {nome}"` su un `div role="button" aria-haspopup="dialog"`, annidato alcuni livelli sotto la riga insieme ai link del profilo (foto + nome).

**Verificato empiricamente** (Playwright reale) che la logica attuale di `_JS_RACCOGLI_RIGHE_CON_ALTRE_OPZIONI` funziona correttamente sia su una riga singola sia su tre righe multiple annidate dentro un contenitore `role="dialog"` condiviso (tipico di un modale): isola correttamente ciascun handle, nessuna confusione tra righe vicine. Quindi il selettore e la risalita del DOM **non sono la causa** del problema reale — l'ipotesi dei giri precedenti è esclusa.

**Ipotesi aperte per il prossimo dato reale (diagnostica del Passo 1, da eseguire dal vivo)**:
- il bottone "Altre opzioni" potrebbe essere renderizzato solo al passaggio del mouse/focus sulla riga (lazy render), quindi assente nel DOM quando lo script legge staticamente;
- il contenuto del modale potrebbe vivere in un iframe non raggiunto da `page.evaluate` sul frame principale;
- lo scroll potrebbe fermarsi troppo presto se il modale usa un contenitore scrollabile diverso da quelli individuati da `_JS_SCROLL_CONTENITORE_INTERNO` (es. virtualizzazione della lista).

**Prossimo passo**: rilanciare `python run.py sync-seguiti --platform=facebook` — ora stampa la diagnostica automaticamente quando il risultato è 0, che darà i dati reali per confermare/escludere le ipotesi sopra invece di continuare a modificare selettori senza prove.

Suite completa: 85/85 test passati.

✅ **Undicesimo giro (2026-08-25): risolti sia Facebook che Instagram con dati reali forniti dall'utente.**

- **Facebook**: la diagnostica ha mostrato solo 90 elementi `[aria-label]` sulla pagina, tutti di navigazione (Home, Reel, Pagine...), zero riguardanti la lista dei 53 seguiti — confermato che la lista non era affatto nel DOM. Screenshot reale dell'utente ha chiarito l'equivoco dei giri precedenti: `&sk=following` apre la scheda **"Follower" della Pagina** (non un modale come ipotizzato) con due sotto-tab interni "Follower" (attivo di default) e "Persone seguite" (mai selezionato). ✅ **Corretto**: `_clicca_sottotab_persone_seguite` clicca il sotto-tab prima della raccolta (commit `82b1b71`). Verificato empiricamente con Playwright reale.
- **Instagram**: l'utente ha fornito l'HTML reale dell'icona profilo nella barra di navigazione — nessun `aria-label` utile sul link (il testo "Profilo" è visivamente nascosto in uno `<span>`, mai un attributo). L'unico segnale affidabile è l'`alt` dell'`<img>` interna: `"Immagine del profilo di {username}"`. ✅ **Corretto**: `_username_da_link_profilo` riscritta per leggere questo pattern (commit `9b15ecf`). Verificato empiricamente con Playwright reale contro l'HTML esatto fornito.

Suite completa: 85/85 test passati.

**Prossimo passo**: ricollaudare dal vivo entrambe le piattaforme:
```
python run.py sync-seguiti --platform=facebook
python run.py sync-seguiti --platform=instagram
```

**Dodicesimo giro (2026-08-25): Instagram risolto e confermato dal vivo, Facebook ancora in corso.**

- **Instagram — ✅ RISOLTO E CONFERMATO.** Il collaudo aveva restituito 5 profili (in realtà i follower, non i seguiti): screenshot reale dell'utente ha mostrato che `?variant=following` sulla home non apre nulla di diverso dalla home normale. Il percorso corretto è andare sul profilo (`instagram.com/{username}/`, ora affidabile grazie allo username già verificato) e cliccare il link "N seguiti", che apre il vero popup modale "Chi segui" (con righe "Segui già", conforme alla logica di raccolta esistente). Corretto in `_leggi_seguiti_instagram` + nuova `_clicca_link_seguiti_instagram` (commit `43f70c0`). **Confermato dal vivo dall'utente: trovati 38/38 profili seguiti reali** (in linea con quanto mostrato dallo screenshot: "0 post · 5 follower · 38 seguiti").
- **Facebook — in corso.** Il log dal vivo ha mostrato che il selettore del sotto-tab "Persone seguite" **trova correttamente l'elemento** (`locator resolved to <span>...Persone seguite</span>`), ma Playwright rifiuta il click giudicandolo "not visible" dopo 5s di retry. Aggiunto `scroll_into_view_if_needed` + click via JS (`el.click()`) come fallback quando il click normale di Playwright fallisce per visibilità (commit `68cc1b8`). **Da ricollaudare dal vivo.**

Suite completa: 85/85 test passati.

✅ **Tredicesimo giro (2026-08-25): risolto anche Facebook — sync-seguiti ora funziona su entrambe le piattaforme.**

Sequenza di scoperte, tutte basate su HTML reale/screenshot forniti dall'utente (mai indovinato alla cieca dopo il primo fallimento):

1. Il click sul sotto-tab "Persone seguite" "riusciva" (nessun errore, anche con `force=True`) ma non cambiava mai tab: l'HTML reale ha rivelato che il testo compare **due volte** nel documento — una in uno `<span>` decorativo senza ruolo interattivo, una nel vero `<a role="tab">`. `get_by_text().first` prendeva sempre quello sbagliato. **Corretto** con `get_by_role("tab", name=...)` (commit `8723cf8`).
2. Anche dopo il fix, il risultato restava 0: l'utente ha ispezionato la sessione Playwright reale (stesso profilo browser dell'app, aperto standalone) e scoperto che era loggata come **profilo personale che visita la Pagina da esterno** (bottone "Segui"/"Mi piace" visibile, tab extra "Follower in comune" tipico della vista pubblica) — non in modalità gestione.
3. Causa a monte: **Facebook ha eliminato lo switch "Usa Facebook come Pagina"**. Un amministratore oggi vede sempre la vista pubblica quando visita la pagina della propria Pagina; la gestione avviene altrove. Il vecchio check di identità (`_identita_pagina_attiva`, basato su quel meccanismo) era quindi strutturalmente inaffidabile — si bloccava anche a login corretto. **Sostituito** (commit `a560f65`) con la verifica del nome dell'account **personale** loggato (nuovo campo `Config.facebook_account_name`, letto da `FACEBOOK_ACCOUNT_NAME` in `.env`), simmetrico a come già funziona `verifica_identita_instagram`.
4. Dopo il nuovo login dell'utente con l'account corretto: **confermato dal vivo, 41/53 profili trovati** (differenza da approfondire più avanti — probabile scroll incompleto o filtro `page_id`, non bloccante). Instagram confermato in precedenza a 38/38.

Rimossi tutti i print diagnostici temporanei usati durante la caccia ai bug (commit `80b6acf`). Aggiunto `FACEBOOK_ACCOUNT_NAME=` e `INSTAGRAM_USERNAME=eventi.langa` a `config/.env.example`.

**Azione richiesta all'utente**: aggiungere `FACEBOOK_ACCOUNT_NAME=Marco Mancini` al proprio `config/.env` (già fatto, confermato dal collaudo riuscito).

Suite completa: 88/88 test passati.

✅ **Quattordicesimo giro (2026-08-25): risolto anche il conteggio parziale — Facebook ora trova 53/53.**

Investigazione guidata dal confronto diretto tra i 53 nomi visibili sullo schermo (forniti dall'utente) e gli handle raccolti dallo script:

1. Diagnostica passo-passo dello scroll ha mostrato che tutte le 53 righe erano già nel DOM dal passo 3 in poi — quindi il problema non era (più) lo scroll, ma l'estrazione.
2. Riscritto l'algoritmo di estrazione del link (da risalita del DOM con `querySelector` a un approccio basato sull'ordine del documento, `compareDocumentPosition`) — nessun miglioramento: stesso 44/53 identico byte per byte, prova che il collo di bottiglia era altrove.
3. Salvataggio automatico dell'HTML esatto nell'istante di fine scroll (`dump_scroll_finale.html`, generato dallo script stesso, non più dipendente da un salvataggio manuale potenzialmente disallineato) ha rivelato la vera causa: **11 dei 53 profili non hanno uno username personalizzato** e usano l'URL `facebook.com/profile.php?id={numero}`. La normalizzazione dell'handle (`ultimo segmento del path, query string scartata`) riduceva tutti questi href al valore identico `"profile.php"`, facendoli collassare in un solo elemento del `Set` — poi eliminato da un filtro pensato per un falso positivo di navigazione.
4. **Corretto** con `_handle_da_href` (commit `5bd373f`): preserva l'`id` dalla query string quando il path termina in `profile.php`, mantenendo ogni profilo distinto.

**Confermato dal vivo dall'utente: 53/53 profili trovati**, esattamente il totale reale. Rimossi tutti i print diagnostici temporanei (commit `bdd9ca2`).

Suite completa: 88/88 test passati.

M9 (sync-seguiti Facebook + Instagram) è ora considerato **completo e collaudato** su entrambe le piattaforme.

**Da fare quando serve** (non bloccante): il file locale `pagina_facebook.txt`/`pagina_facebook`/`dump_scroll_finale.html` (HTML salvati per il debug) restano nella cartella `eventi/`, non tracciati da git — possono essere cancellati.

**Follow manuali registrati finora (via chat, 2026-08-23 sera): 35 profili Instagram** marcati `seguito` in `coda_follow`, tra Langhe/Monferrato/Roero fascia A. Due correzioni fatte durante l'inserimento:
- **Rocchetta Tanaro**: handle nel dataset ereditato era sbagliato (`rocchettatanaro`), corretto con quello verificato dall'utente (`proloco_rocchettatanaro`).
- **Dogliani e Santo Stefano Belbo**: esisteva già una riga con un handle diverso da quello indicato dall'utente; aggiornato con l'handle verificato di persona (più affidabile del dato ereditato).

**Comuni ambigui chiariti dall'utente:** "Ricca" e "Valle Talloria" sono frazioni di **Diano d'Alba**, inserite come soggetti/handle distinti dalla Pro Loco principale del comune (3 righe totali per Diano d'Alba).

**Anomalia Bormida/Monastero Bormida — ✅ risolta 2026-08-25:** `proloco-bormida-instagram` (comune Bormida, SV) condivideva lo stesso handle Instagram `proloco_monasterobormida` di `proloco-monastero-bormida-instagram` (comune reale distinto, AT) — la riga era stata marcata `'seguito'` per errore dal `sync-seguiti` del 25/08 (il sistema aveva trovato l'handle reale tra i seguiti e marcato entrambe le righe che lo condividevano, ma l'utente non ha mai seguito la Pro Loco di Bormida SV con quell'handle). L'utente ha confermato: nessuna vera Pro Loco associata a quell'handle. **Riga eliminata da `coda_follow`.**

**Bonifica più ampia scoperta durante la verifica (2026-08-25): 49 handle rotti nel dataset ereditato.** Indagando l'anomalia Bormida, trovate altre 48 righe con lo stesso tipo di difetto: handle ridotti a un frammento generico dell'URL (`p`, `pages`, `events`, `explore`, `reel`) invece del vero identificativo — bug nel pattern di estrazione di `bonifica_social.py`, mai applicato a questi casi specifici finora.

✅ **Corretto in `src/bonifica_social.py`** (commit `766baf6`):
- Recuperato l'handle vero per i pattern `facebook.com/p/Nome-ID`, `facebook.com/pages/Nome/ID` e `facebook.com/pages/category/Tipo/Nome-ID` (nuovi pattern regex, analoghi al già esistente `people/Nome/ID`).
- Marcati esplicitamente come "non profilo" (quarantena, mai handle finto) i link a: eventi standalone (`facebook.com/events/.../ID`), tag di posizione geografica (`instagram.com/explore/locations/...`), reel singoli (`(instagram|facebook).com/reel/...`).
- 5 nuovi test mirati ai casi reali. Suite completa: 93/93 test passati.

✅ **Applicato ai dati esistenti in `coda_follow`** (script una tantum, non un comando permanente): delle 49 righe con handle rotto, **32 corrette con l'handle vero recuperato**, **6 spostate in quarantena** (non erano mai state seguite, url non è un vero profilo), **11 preservate come `'seguito'`** (l'utente ha confermato di averle seguite realmente a mano il 23/08, solo l'handle registrato era sbagliato — handle svuotato con nota, da confermare al prossimo `sync-seguiti`). Nessun handle rotto residuo verificato.

**Difetto preesistente notato, poi chiuso come falso allarme:** il comune "Montà" appariva con encoding corrotto (`Mont�`) nella console — verificato 2026-08-25 che è solo un artefatto di visualizzazione del terminale Windows (codepage 437), il dato reale in SQLite/CSV è UTF-8 corretto. Nessuna correzione necessaria, vedi sezione dedicata sopra.

**Primo tentativo reale di follow su Facebook (2026-08-25): falso allarme captcha, trovato e corretto.**

Con `sync-seguiti` ormai affidabile su entrambe le piattaforme, tentato il primo `follow --platform=facebook --n=3` mai eseguito. Risultato: circuito aperto immediatamente su un presunto "captcha" rilevato su `proloco-isola-d'asti-facebook` — ma **l'utente ha visto la pagina aprirsi normalmente, nessun captcha visibile**.

🐛 **Bug reale trovato e corretto**: `_apri_e_segui` cercava i segnali di blocco (`_SEGNALI_BLOCCO`: captcha, checkpoint, ecc.) nell'HTML grezzo (`pagina.content()`), non nel testo visibile. **Verificato empiricamente** riaprendo la stessa pagina con la sessione salvata: "captcha" compariva solo come nome di un'integrazione di terze parti (`arkose_captcha`) nel blob di configurazione cookie, presente su **ogni** pagina Facebook indipendentemente da un vero blocco — stessa classe di falso positivo già vista con "gestisci" nella sidebar (undicesimo/tredicesimo giro sync-seguiti). Confermato che lo stesso controllo su `pagina.inner_text("body")` (il testo che un utente vede davvero) non produce il falso positivo sulla stessa pagina, con il bottone "Segui" trovato correttamente. **Corretto** (commit `d8dbdda`): il controllo dei segnali di blocco ora usa il testo visibile, non l'HTML grezzo.

Anche un bug minore corretto nello stesso giro: `run.py` usava un'emoji (⚠️) nel messaggio di blocco che causava un crash (`UnicodeEncodeError`) sul terminale Windows in codepage cp1252, mascherando l'informazione già stampata sopra (commit `f2b79cf`).

Circuito Facebook aperto per errore rimosso manualmente da `app_state` (`DELETE FROM app_state WHERE chiave = 'circuito_aperto_fino_facebook'`). Resta però attivo l'intervallo minimo di 45 minuti tra lotti (`ultimo_lotto_follow_facebook`, protezione separata e legittima, non un bug): il prossimo tentativo reale va fatto non prima di ~45 minuti dopo le 10:22 del 2026-08-25.

✅ **Primo lotto di follow reale completato con successo (2026-08-25, 11:23-11:24): `follow --platform=facebook --n=3`.**

Risultato: **2 profili seguiti realmente** (`ProLocoBUBBIO`, `proloco.monesiglio`, entrambi marcati `stato='seguito'` in `coda_follow` con `data_follow` reale), 1 candidato (`proloco-barbaresco-facebook`) segnalato `"nessun pulsante Segui trovato"` — probabile già seguito in precedenza (condivide lo stesso handle Facebook con `comune-barbaresco-facebook`, seguito potenzialmente in un lotto diverso), non un errore: `tentativi` incrementato a 1, riproverà al prossimo lotto, nessun blocco. Nessun captcha, nessun crash, nessun falso allarme — il fix del rilevamento (commit `d8dbdda`) ha tenuto.

Nota tecnica: durante un primo tentativo la finestra Chromium è stata chiusa manualmente per errore dall'utente (`TargetClosedError`), senza conseguenze — nessun tentativo era stato registrato in `coda_follow` prima del crash, ritentato senza problemi.

✅ **Secondo lotto reale completato (2026-08-25, 12:xx): `follow --platform=facebook --n=10`.** Risultato: **6 profili seguiti realmente** (`prolocodivinchio`, `ass.turistica`, `noi.rocchettapalafea`, `festa.cappelletto`, `Belveglio`, `ProLocoBorgomale`), 2 già seguiti in precedenza, **2 segnalati "handle non corrisponde alla pagina aperta"** — indagati e **corretti** (commit `45576b6`): bug reale nel controllo di `_apri_e_segui`, non nei dati. Per gli URL `facebook.com/people/Nome/ID`, l'handle salvato è `"Nome-ID"` (trattino unito), ma l'URL reale della pagina resta `"Nome/ID"` con slash — la stringa unita non compare mai letteralmente, scartando candidati in realtà corretti. **Corretto**: il controllo ora accetta anche il solo ID numerico finale (sempre presente, indipendentemente dal formato di unione). Le 2 righe scartate per errore riportate a `da_seguire`.

✅ **Terzo lotto reale completato (2026-08-25, ~15:05): `follow --platform=facebook --n=10`.** Risultato: **7 profili seguiti realmente** (`Pro-Loco-Montiglio-Monferrato-100091965315966`, `Pro-Loco-Incisa-1514-61573401493311`, `Pro-Loco-Monastero-Bormida-100066622596287`, `prolocomongardino1976`, `ProLocoTreiso`, `prolocogovone`, `proloco.castagnito`), 3 già seguiti in precedenza, nessun errore/blocco. **Conferma diretta del fix precedente**: le due righe `proloco-montiglio-monferrato-facebook` e `proloco-incisa-scapaccino-facebook` (scartate per errore nel lotto precedente per il bug "Nome-ID" vs "Nome/ID") sono state seguite correttamente questa volta.

**Totale Facebook seguiti finora: 64 profili** (`SELECT COUNT(*) FROM coda_follow WHERE piattaforma='facebook' AND stato='seguito'`). Solo 1 riga `non_valido` residua, 1 `fallito`, 4 in `quarantena` — tutto il resto (609) ancora `da_seguire`.

⚠️ **Tetti raddoppiati su richiesta esplicita (2026-08-25, commit `362b1ac`)**: `follow_per_lotto` 10→20, `follow_max_giornalieri` 50→100. Rischio accettato consapevolmente dall'utente nonostante il riscaldamento (14.3, "5-20 follow/giorno crescenti") non sia ancora concluso (~2026-09-05) — stesso tipo di scelta già fatta per i primi tentativi di follow in questa sessione.

⚠️ **Schedulazione automatica ogni 2 ore aggiunta su richiesta esplicita (2026-08-25)** — in tensione diretta col principio 14.3/14.5 ("mai automazione silenziosa sui blocchi", browser sempre non-headless proprio per essere supervisionato): rischio accettato consapevolmente. `eventi/schedulazione_follow.bat` lancia in sequenza `run.py follow --platform=facebook` poi `--platform=instagram`, loggando tutto in `data/log_follow_schedulato.txt` (non tracciato da git) — le precondizioni/circuito esistenti fermano da soli il lotto se non è il momento giusto, senza bisogno di logica aggiuntiva. Registrato con `schtasks` (Utilità di pianificazione Windows), nome attività `EventiLangheFollow`, ogni 2 ore, con l'utente Windows dell'utente (non SYSTEM, necessario perché la sessione Playwright/browser è legata al profilo). **Raccomandazione**: controllare periodicamente `data/log_follow_schedulato.txt` per accorgersi di blocchi/captcha che altrimenti passerebbero inosservati fino al prossimo controllo manuale.

Nota tecnica dal collaudo dello script: durante il test, lanci con timeout artificiali brevi (<120s) producevano `TargetClosedError` — falso allarme dovuto solo al timeout del comando di test che troncava il processo Python a metà (le pause tra follow reali sono 25-70s, un lotto di 2+ follow supera facilmente 120s). Isolato passo-passo: il codice funziona correttamente, nessun bug reale nello script o in `follow.py`.

**Prossimo passo:**
1. **Instagram**: circuito ancora aperto per il captcha reale del 2026-08-23 fino al **2026-08-26 ~08:06** — non forzare, attendere la riapertura naturale.
2. **Facebook**: aspettare i 45 minuti dall'ultimo lotto (~15:50 del 2026-08-25) prima del prossimo `follow --platform=facebook`.

Comandi pronti:
```
python run.py follow --platform=facebook --dry-run       # verifica l'elenco, nessuna azione
python run.py follow --platform=facebook --n=3           # dopo i 45 minuti di attesa
python run.py follow --platform=instagram --dry-run      # verifica l'elenco, sessione già loggata
python run.py follow --platform=instagram --n=3          # dopo la riapertura del circuito (2026-08-26)
python run.py populate-coda-follow --publish              # quando pronti: scrive il foglio CodaFollow reale su Sheets
```

## M7 — Canali push: adattatori costruiti (2026-08-25)

Ricerca preliminare nella documentazione (doc 05 mancante, dettagli dedotti da 04/08/10/13/14): confermato che email e Telegram sono **fonti da ingerire** (newsletter a cui ci si iscrive manualmente, canali Telegram di Pro Loco/comuni di cui il bot è membro), non canali di notifica in uscita — il sistema non manda mai nulla all'utente via email/Telegram (08: "niente notifiche push, la diagnostica vive nel foglio").

**Fatto:**
- `src/adapters/email_imap.py`: `EmailImapAdapter` legge la casella IMAP (`Config.imap_host/user/password`), filtra per mittente atteso (`fonte["endpoint"]`), estrae oggetto+corpo (preferendo `text/plain`, fallback `text/html`) e salva gli allegati immagine su disco (`data/cache/images/{source_id}/`) senza interpretarli — l'estrazione visiva resta compito del VLM a valle (M10), coerente con 10-roadmap.md ("estrazione da immagini allegate alle email, già usa il VLM").
- `src/adapters/telegram.py`: `TelegramAdapter` usa l'API bot ufficiale via `getUpdates` (httpx, nessuna libreria SDK aggiuntiva), filtra per canale atteso.
- Entrambi seguono il contratto esistente (funzione pura di parsing testabile senza rete + classe Adapter che fa I/O), producono `Artefatto` senza campi strutturati precompilati (stesso ramo T1-like dell'adattatore html: passano dal pre-filtro testuale e dall'estrattore LLM).
- Integrati in `pipeline.esegui_fonte` con due nuovi metodi (`fonte["metodo"]`): `T0_email`, `T0_telegram` — istanziati per fonte (richiedono `Config` per le credenziali), a differenza degli adapter esistenti che sono stateless e condivisi in `_ADAPTER_PER_TIER`.
- 10 nuovi test su fixture (email MIME costruite in memoria, update Telegram JSON simulati), nessuna rete/IMAP reale. Suite completa: 101/101.

**Manca, in ordine di priorità:**
1. **Collaudo end-to-end reale**: `config/.env` ha già `IMAP_USER=eventi.langa@gmail.com` ma `IMAP_HOST` e `IMAP_PASSWORD` sono vuoti (serve una "app password" Gmail se la 2FA è attiva) e `TELEGRAM_BOT_TOKEN` è vuoto (da BotFather). Finché mancano, gli adattatori sono verificati solo su fixture.
2. **Rilevazione automatica dei moduli newsletter** (criterio di accettazione M7: "il foglio `Newsletter` contiene una lista ordinata di soggetti con link di iscrizione") — dipende da funzionalità di discovery/fingerprinting collocate in M8 (`run.py discover`, ancora un placeholder "non ancora implementato"). Rimandata a quella tappa per scelta esplicita, per non anticipare M8 dentro M7.
3. Nessuno schema/tabella per il foglio `Newsletter` esiste ancora in `store.py` — da modellare quando si affronta il punto 2, verosimilmente sul pattern di `coda_follow` (coda con stato di avanzamento manuale).

## Primo giro di ricerca eventi multi-fonte — pronto (2026-08-26)

Domanda: "cosa manca per fare un primo giro di ricerca eventi?" Risposta trovata: mancava solo il "passo 1" di 12.8 (import dell'elenco fonti in `sources`) — `pipeline.esegui_fonte` era già collaudata più volte su singole fonti (`--fonte/--endpoint/--metodo`), ma `sources` era vuota, quindi `run.py run` senza argomenti non processava nulla.

✅ **Nuovo comando `run.py import-fonti`** (commit `02569fa`): importa da `Comuni.csv` (colonna `SitoIstituzionale`, copertura 683/683 già verificata) e `ProLoco.csv` (colonna `Sito`, solo 28/761 — la maggioranza delle Pro Loco vive solo su Facebook, fuori scope finché non esiste `feed_social.py` di M10). Tutte importate con metodo `T1_html`. Collaudato dal vivo: **703 fonti importate**.

✅ **Aggiunto `--limite` a `run.py run`** (commit `f2f6a4b`), coerente con quello già su `fingerprint-comuni`.

✅ **Collaudo su 10 fonti reali del campione**: fetch, pre-filtro, estrazione LLM ed isolamento errori funzionano tutti correttamente (2 errori di rete isolati senza fermare le altre 8). Nessun evento pubblicato nel campione — motivo verificato e legittimo: le homepage istituzionali sono spesso avvisi amministrativi (trasporto scolastico, gare d'appalto), non calendari eventi, coerente con "vuoto non è un errore" (04.7). Dati di test ripuliti da SQLite.

🐛 **Bug critico trovato durante il primo lancio reale dell'utente, corretto (2026-08-26, commit `575a9ae`).** Il run si è fermato del tutto su `comune-castellinaldo-d'alba`: l'LLM ha restituito `giorni_settimana=["mercoledì"]` (nome per esteso) invece del codice RFC5545 `WE`, nonostante il prompt lo richiedesse — `regola_leggibile` ha sollevato `KeyError`, mai catturato, fermando l'intero giro su 700+ fonti (violazione di 15.1 regola 4). L'utente ha chiesto esplicitamente: mai più fermarsi, segnare l'errore e proseguire con le altre fonti per poi fare un riciclo mirato su quelle fallite. **Corretto su 5 livelli** (difesa in profondità): prompt chiarito, nuova `recurrence.normalizza_giorno_settimana` (accetta anche varianti italiane/inglesi, mai solleva), `series.upsert_serie` normalizza prima di usare, `pipeline.esegui_fonte` ora isola anche la gestione del singolo evento estratto (mancava), `run.py cmd_run` ha un'ultima rete di sicurezza attorno a ogni fonte nel loop. 2 nuovi test mirati. Suite: 111/111 dopo questo fix.

✅ **Verifica a campione richiesta dall'utente**: esaminato in dettaglio `comune-asti` (script `dettaglio_fonte.py`, creato per questo scopo) — URL, testo grezzo scaricato, chiamata LLM, evento salvato (**"Palio di Asti", 2026-09-06**, coerente con la tradizione reale della manifestazione, verificabile a mano sul sito). Ha rivelato però un limite: **il sistema interroga solo la homepage istituzionale**, dove eventi come questo compaiono solo per caso in un comunicato generico, non su una vera sezione eventi.

💡 **Osservazione dell'utente, rivelatasi un gap reale documentato ma mai implementato (04.2, "il prober")**: ha senso analizzare solo l'homepage, o conviene trovare la vera pagina eventi/calendario e analizzare quella? **Confermato e risolto** (commit `e1a7754`): nuovo `src/prober.py` + comando `run.py prober`. Verificato empiricamente su un comune per famiglia CMS (WordPress, Drupal, PA design system): tutti hanno un link testuale "Eventi" in homepage con path diversissimi (`/vivere/eventi/`, `/vivere-comune/eventi`, ecc.) — trovarlo nella homepage già scaricata (zero richieste extra) e seguirlo è molto più efficace che indovinare pattern URL fissi (i path standard di 04.2 come `/eventi` hanno dato 404/timeout su Asti). Trovato e corretto anche un bug di risoluzione URL (comune.calosso.at.it usa `href="Eventi"` senza slash iniziale — sostituita la logica manuale con `urllib.parse.urljoin`). Collaudato: **8/10 fonti reali** hanno trovato una vera pagina eventi diversa dalla homepage.

**Prossimo passo naturale**: lanciare `python run.py prober` su tutte le 703 fonti per arricchire `sources.endpoint` con le vere pagine eventi, POI rilanciare `python run.py run` — dovrebbe alzare sensibilmente la resa rispetto al primo giro sulle sole homepage. Il "riciclo mirato sugli errori" richiesto dall'utente (rilanciare solo le fonti fallite) non è stato ancora implementato come comando dedicato — oggi si rilancia l'intero giro, che grazie al dedup non duplica nulla ma rifà del lavoro; una vera coda di retry mirata è materia di M11 (operatività).

## M10 — Feed social: costruito, non ancora collaudato dal vivo (2026-08-27)

Richiesta esplicita dell'utente: affrontare gli eventi sui social. Prima ricerca nella documentazione (doc 05 mancante, dedotto da 04/06/08/12/14): confermato che il feed va letto con Playwright (stessa infrastruttura del follow), sessione persistente, scroll cronologico ("Feed → Più recenti" su Facebook, vista "Seguiti" su Instagram) fino all'ultimo post già visto, mai interazioni. Tre decisioni non specificate nella documentazione, chiarite con l'utente prima di scrivere codice:

1. **Design**: script standalone come `follow.py`/`sync_seguiti.py`, non un `Adapter` nella pipeline.
2. **Attribuzione handle sconosciuti**: riuso di `coda_follow` con nuovo stato `candidato_da_feed` (non una tabella dedicata).
3. **Verifica identità in lettura**: sì, stessa verifica già scritta per il follow (mai specificata esplicitamente per la sola lettura nella doc, ma coerente col principio generale).

**Costruito**: `src/feed_social.py` — `verifica_separazione_da_follow` (14.5b: mai follow e lettura nella stessa sessione, almeno un'ora), `attribuisci_post` (12.3: handle noto→comune della fonte, sconosciuto→candidato mai scartato), `elabora_post` (attribuzione + pre-filtro + estrazione LLM + pubblicazione, riusando `pipeline._pubblica_o_metti_in_quarantena`/`_registra_artefatto` invece di duplicare logica — gestisce esplicitamente i gruppi Facebook, 14.6: comune mai inferito dall'autore, solo da `comune_testuale` esplicito), scroll con change detection sul post ID persistita in `app_state`. Nuovo comando `run.py feed-social --platform=X`.

✅ **Collaudo dal vivo completato (2026-08-27), con 3 giri di bug/fix reali** — esattamente come già successo per `follow.py`/`sync_seguiti.py`, coerente col principio di questo progetto (indovinare al massimo 2 volte, poi fermarsi e ispezionare i dati reali):

1. **`div[role="article"]` non esiste più nel feed principale di Facebook** — i soli 2 elementi trovati con quel ruolo erano skeleton di caricamento residui (`aria-label="Caricamento..."`, mai contenuto reale). Riscritto partendo da `h3 a[href]` (affidabile per l'autore) e risalendo fino al vero contenitore del post, riconosciuto perché ha molte parole uniche (>8) — a differenza dei contenitori intermedi che ripetono solo "Facebook" (alt-text di un carosello) o dei tag di localizzazione geografica.
2. **`_handle_da_href_profilo` prendeva `"https:"` come falso handle**: l'href reale nel feed è un URL assoluto con parametri di tracking (`__cft__`), non relativo come nella pagina "seguiti" — sostituito lo split manuale con `urlparse`. Aggiunto anche il caso `profile.php?id=NNN` (stesso bug già risolto in `bonifica_social.py` per il follow).
3. **`_post_id_da_permalink` avrebbe rotto la change detection**: l'unico link disponibile per un post nel feed è quello dell'autore, con `__cft__`/`__tn__` diversi ad ogni caricamento — l'ID ora si basa sul testo del post (stabile) quando l'URL non contiene un ID riconoscibile. Nuova `_pulisci_testo_post` rimuove anche le righe "Facebook" ripetute (numero variabile) e le righe con caratteri Unicode "combining" con cui Facebook offusca date/timestamp (categoria Mark, es. U+034F) — testo altrimenti illeggibile.
4. **`IntegrityError` sulla foreign key `artifacts.source_id`**: mai registrata la fonte sintetica `feed-{piattaforma}-{handle}` in `sources` prima di scrivere l'artefatto — mai intercettato dai test perché la connessione di test non aveva `PRAGMA foreign_keys=ON` attivo (allineata a `store.connect()`, che lo attiva sempre in produzione).

**Risultato finale verificato sulla sessione Facebook reale**: 107 post letti in un giro di scroll, **4 eventi reali pubblicati/in quarantena** (Festival Contro, Fuochi d'artificio, Festa della Birra a Castagnole delle Lanze; una cena a Mongardino — tutti con date credibili e comune corretto), 9 nuovi candidati registrati in `coda_follow` per handle non ancora mappati.

22 nuovi test (inclusi i casi reali osservati). Suite completa: 145/145.

**Manca ancora per completare M10:**
- Collaudo dal vivo del feed **Instagram** (finora testato solo Facebook).
- `social_polling.py` per le ~100 fonti `polling_diretto` (visita individuale 2-3×/settimana come rete di sicurezza sul feed, che non è garantito completo).
- Priorità della quota LLM per fascia (soglie 70/85/100% di 08.5) — non ancora implementata, dipende da M11.
- Collegamento diretto tra `estrai_da_immagine` (VLM, prompt già scritto in `testo_v1.py`) e i post con immagini lette dal feed — oggi `elabora_post` passa `image_paths` all'`Artefatto` ma chiama sempre `estrai_da_testo`, non `estrai_da_immagine`.
- Limite noto non risolto (impatto nullo): alcuni post senza testo utile producono occasionalmente `post_id` duplicati nello stesso giro di scroll — sempre scartati, mai pubblicati due volte, solo rumore nell'elenco stampato a schermo.

## M8 — Fingerprinting: motore costruito e verificato su comuni reali (2026-08-25)

`src/fingerprint.py`: `classifica_html` (funzione pura, testabile su HTML già scaricato) + `fingerprint_sito` (scarica con User-Agent da browser esplicito e classifica). Tre firme reali verificate empiricamente contro comuni del perimetro (non ipotizzate):

| Piattaforma | Indizio | Comune verificato |
|---|---|---|
| `wordpress` | `wp-content` nel markup | comune.cuneo.it (con commento "Yoast SEO" a conferma) |
| `drupal` | `<meta name="Generator" content="Drupal 9...">` | comune.asti.it, comune.alessandria.it |
| `pa_design_system` | `bootstrap-italia` + `agid.css` (template istituzionale AGID) | comune.alba.cn.it |

**Scoperta pratica non documentata esplicitamente**: le richieste HTTP senza User-Agent da browser ricevono spesso **403** dai siti comunali reali (verificato: comune.cuneo.it risponde 403 con lo user-agent di default httpx, 200 con uno User-Agent Chrome) — coerente col punto 4 della guida M8 ("il dato attuale, HTTPStatusError quasi ovunque, non è credibile ed è probabilmente un blocco"). `fingerprint_sito` usa uno User-Agent esplicito.

Aggiunta `sources.piattaforma` (colonna già citata nel modello dati documentale — 03-modello-dati.md — ma mai presente nello schema SQLite reale). 7 nuovi test su fixture HTML basate sugli indizi reali. Suite completa: 108/108.

**Ambito volutamente limitato inizialmente** (scelta esplicita dell'utente, per non costruire a vuoto senza dati reali): solo il motore di classificazione. Completato subito dopo, vedi sotto.

✅ **Elenco URL + classificazione batch completati (2026-08-25).** Scoperta chiave: `Comuni.csv` (dataset ereditato, usato anche da `bonifica_social.py`) ha già una colonna `SitoIstituzionale` con URL reali **verificati per tutti i 992 comuni**, non un pattern indovinato — copertura **683/683** (100%) sul perimetro caricato in SQLite. Non è servito costruire nulla da zero per l'elenco URL.

- Aggiunta tabella `fingerprint_comuni` (distinta da `sources`, pensata per il censimento di tutti i comuni anche senza una fonte configurata) e migrazione automatica per `sources.piattaforma` sui database locali esistenti (`ALTER TABLE`, dato che `CREATE TABLE IF NOT EXISTS` non tocca tabelle già create).
- Nuovo comando `run.py fingerprint-comuni` (`--limite`, `--pausa`): legge gli URL dal CSV, filtra sul perimetro, fingerprinta e salva.
- **Collaudo reale sui 683 comuni**: **11 errori/irraggiungibili (1.6%)**, distribuzione:

  | Piattaforma | Comuni | % sul totale |
  |---|---|---|
  | `pa_design_system` (template AGID) | 435 | 63.7% |
  | `sconosciuta` | 139 | 20.4% |
  | `wordpress` | 92 | 13.5% |
  | `drupal` | 6 | 0.9% |

  **Criterio di accettazione M8 superato ampiamente sulla sola fascia A**: 189/255 comuni fascia A (**74.1%**) coperti da `pa_design_system` da sola, contro il ≥60% richiesto — sommando anche WordPress (14) si arriva a **203/255 (79.6%)** con due sole famiglie.

**Manca ancora:**
1. **Adattatori per famiglia** (12.5, passo 3): uno per `pa_design_system` (la più diffusa, 63.7%) e uno per `wordpress` (13.5%) — non ancora scritti. Ogni adattatore deve conoscere il percorso della sezione eventi e, spesso, l'endpoint strutturato nascosto (RSS/iCal) che questi template espongono di solito.
2. Ritestare le sitemap con lo User-Agent da browser (punto 4 della guida M8) — non ancora fatto separatamente, ma lo stesso fix (User-Agent esplicito) già applicato qui ha eliminato ogni 403 osservato nei test.

## Dati operativi fissati

| Voce | Valore |
|---|---|
| Casa | Calosso (AT) |
| Pagina Facebook dedicata | https://www.facebook.com/profile.php?id=61593736766094 |
| Account Instagram dedicato | https://www.instagram.com/eventi.langa/ |
| Email dedicata | eventi.langa@gmail.com |
| Data creazione account social | 2026-08-22 (da confermare se diversa) |
| Fine riscaldamento minimo (+14gg) | ~2026-09-05 |

⚠️ Nessun follow massivo prima della fine del riscaldamento ([14.3](Documentazione/14-account-social.md#143-riscaldamento--2-settimane-prima-di-qualunque-follow-massivo)).

---

## Esito verifica PiemonteItalia / VisitLMR (2026-08-22)

Verifica da remoto (ricerca web + fetch pagine pubbliche), non un'ispezione manuale del sorgente HTML: da **confermare con view-source manuale** in Fase 0.2 prima di escludere definitivamente il T0.

| Fonte | Esito | Dettaglio |
|---|---|---|
| **piemonteitalia.eu/it/eventi** | T1, non T0 | 606 eventi, filtri per categoria/comune/provincia/data via URL, ma **nessun RSS/iCal/JSON-LD** rilevato sulla pagina lista né su una pagina di dettaglio campione |
| **visitlmr.it/it/calendario-eventi** | T1, non T0 | Filtri lato server (territorio, mese, date check-in/out) ma **nessun feed machine-readable** |
| **visitpiemonte.com/eventi** | Inconcludente | Pagina sembra caricata via JS (contenuto non renderizzato nel fetch statico) — da verificare con browser reale |
| **Geoportale Piemonte — "Manifestazioni fieristiche"** | **T0 parziale, trovato** | Dataset scaricabile: `https://www.datigeo-piem-download.it/direct/Geoportale/RegionePiemonte/Commercio/Manifestazioni_fieristiche.zip` (Shapefile), anche via WMS. Licenza **CC BY 4.0**, aggiornamento **semestrale**. Copre l'intera regione ma **solo manifestazioni fieristiche/commerciali**, non l'intero spettro di eventi (niente concerti, teatro, sagre gastronomiche minori) |
| **Calendario fieristico regionale** (regione.piemonte.it) | Complementare | PDF annuale con fiere e sagre regionali/locali — utile come lista di partenza per il regime curato/`Feste`, non come feed |

**Verdetto:** nessuno dei due portali principali espone un canale T0 diretto per il calendario eventi generico. Il dataset del Geoportale è un T0 vero ma a copertura ristretta (fiere/manifestazioni commerciali, semestrale). **Non cambia l'ordine di lavoro previsto in [15](Documentazione/15-guida-implementazione.md):** M3 (aggregatori) tratterà piemonteitalia.eu e visitlmr.it come **adattatori HTML con parametri di query** (lista filtrabile per comune/data → scraping strutturato via parametri URL, non full-text), e il dataset Geoportale come fonte T0 aggiuntiva a bassa frequenza (semestrale) per il regime massivo/fiere.

**Nota metodologica:** questa verifica è stata fatta via fetch remoto automatizzato, non con "view-source" manuale come raccomandato dal doc 04.2 ("vale la pena farlo anche a mano"). Il fetch automatico converte HTML→markdown e può non rilevare `<script type="application/ld+json">` in tutti i casi. Raccomandabile un controllo manuale rapido (5 minuti, browser + Ctrl+F "ld+json") su una pagina di dettaglio evento di piemonteitalia.eu prima di escludere definitivamente il JSON-LD in M3.

---

## 15.0 — Prima di scrivere una riga

- [x] Creazione dei due account social dedicati (FB pagina + IG) — fatto 2026-08-22
- [x] Casella email dedicata — eventi.langa@gmail.com
- [ ] Riscaldamento account (2 settimane, in corso — usare a mano, 5-20 follow/giorno crescenti, mai automazione)
- [x] Verifica PiemonteItalia e VisitLMR (dati strutturati?) — **fatto 2026-08-22, esito: nessun T0 diretto, vedi sezione dedicata sotto**

## Fase 0 / M0-M11 (ordine da [15-guida-implementazione.md](Documentazione/15-guida-implementazione.md))

- [x] M0 — Fondamenta **completate e verificate** 2026-08-22 sera. Workbook reali creati, criterio di accettazione superato: 500 righe scritte in 2.1s (<10s richiesti), modifica manuale di `note` sopravvissuta a un secondo rilancio della pubblicazione. Righe di test ripulite dal foglio
- [x] M1 — Import Perimetro, fasce, alias, risoluzione comune — **completato e testato** 2026-08-22 (SQLite + foglio `Perimetro` reale pubblicato: 683 righe, ordinate per km, A=255 B=200 C=228)
- [x] M2 — **Completato**, sia per T0 puro (ical/jsonld) sia per T1 (html→LLM): `src/pipeline.py` orchestra fetch→pre-filtro→estrazione→normalizzazione→dedup→SQLite in isolamento totale per fonte. `run.py run --fonte X --endpoint Y --metodo Z` costruisce l'estrattore automaticamente se `LLM_API_KEY` è configurata (`--no-llm` per il vecchio comportamento pre-M5)
- [~] M3 — Aggregatori: adattatore HTML generico collaudato su fonti reali (vedi sotto). **Manca:** collaudo su piemonteitalia.eu/visitlmr.it stessi (solo verificati per struttura, non ancora interrogati con l'adattatore) e adattatori specifici con filtri URL per i portali regionali
- [~] M4 — Pre-filtro testuale fatto e testato (`src/prefilter.py`: schema non-evento, segnali di data/parole chiave, date passate, lunghezza minima). **Manca:** pre-filtro grafico (densità di testo/Sobel) e cache pHash — richiedono immagini reali per calibrare le soglie
- [x] M5 — Estrazione LLM: **client completo, collaudato contro Gemini reale, collegato end-to-end alla pipeline**. Provider intercambiabile via `LLM_PROVIDER` in `.env`. Schema Pydantic, prompt v1, retry, contatore quota, controlli di sanità, soglia di confidenza con instradamento in quarantena (06.6). Collaudo reale: `run.py run` contro ScavalcaMontagne → **4 eventi pubblicati** (Alzati e Cammina, Summertime, Ok il Pezzo è Giusto, Ricette e Sinfonie), tutti con date future e dati plausibili. Due bug reali trovati e corretti nel collaudo (vedi sotto). **Manca ancora:** dedup L3 fuzzy, `run.py reprocess`
- [x] M6 — **Completato ed end-to-end**: `src/series.py` collega il campo `ricorrenza` dell'estrattore a `RegolaRicorrenza`/RRULE (`recurrence.py`), con upsert della `Serie` (dedup per titolo+comune+luogo, rispetto di `bloccata`, stato di decadimento) ed espansione delle occorrenze nell'orizzonte scorrevole. `pipeline.esegui_fonte` ora instrada gli eventi ricorrenti in Serie invece di pubblicarli come singoli. 8 nuovi test (7 su `series.py`, 1 end-to-end nella pipeline). **Manca ancora:** collegamento al foglio `Serie` reale su Sheets (solo SQLite per ora) e supporto alla frequenza `annuale` (oggi solo settimanale/mensile)
- [~] M7 — Canali push (email IMAP, newsletter, Telegram): **adattatori costruiti e integrati**, `src/adapters/email_imap.py` + `src/adapters/telegram.py`, seguono il contratto esistente (funzione pura testabile + classe Adapter), integrati in `pipeline.esegui_fonte` con i metodi `T0_email`/`T0_telegram`. 10 nuovi test su fixture, suite 101/101. **Manca:** collaudo end-to-end reale (servono `IMAP_HOST`/`IMAP_PASSWORD` in `.env`, e `TELEGRAM_BOT_TOKEN`, non ancora configurati), e la rilevazione automatica dei moduli newsletter (dipende da funzionalità di discovery/fingerprinting di M8, non ancora scritta) — vedi sezione dedicata sotto
- [~] M8 — Fingerprinting e adattatori di piattaforma (famiglie di CMS): **motore di classificazione costruito e verificato**, `src/fingerprint.py` — 3 firme (wordpress, drupal, pa_design_system) verificate empiricamente contro comuni reali del perimetro (comune.cuneo.it, comune.asti.it, comune.alba.cn.it). Aggiunta `sources.piattaforma` allo schema. 7 test, suite 108/108. **Manca:** elenco URL dei 683 comuni (non esiste ancora in SQLite), classificazione batch, adattatori per famiglia — vedi sezione dedicata sotto
- [~] M9 — Follow: **preparazione completa, nessuna azione reale ancora eseguita**. Bonifica (896 fonti pulite), logica di stato/circuito testata senza browser, `run.py login`/`follow --dry-run`/`follow` pronti. L'utente ha provato `--dry-run` senza login: corretto un bug di istruzione (il dry-run non apre mai il browser) aggiungendo `run.py login --platform=X` dedicato. **Manca:** login reale mai fatto, follow reale mai eseguito — vedi sezione dedicata sopra per l'ordine esatto dei comandi
- [~] M10 — Feed social e locandine: **script `src/feed_social.py` costruito** (lettura cronologica, attribuzione handle→comune, estrazione LLM riusando la pipeline), `run.py feed-social --platform=X`. 15 nuovi test, suite 138/138. **Manca:** collaudo reale (selettori DOM mai testati contro l'interfaccia vera, a differenza di sync_seguiti.py), `social_polling.py` per le ~100 fonti `polling_diretto`, priorità della quota per fascia (M11) — vedi sezione dedicata sotto
- [ ] M11 — Operatività (coda, scheduling coalescente, lock file, Stato, backup, doctor)

---

## Collaudo su 10 fonti reali fornite dall'utente (2026-08-22 sera)

L'utente ha fornito 10 fonti reali (teatri, portali, aggregatori del Piemonte). Verificate una per una:

| Fonte | Tier riscontrato | Esito |
|---|---|---|
| Paesaggi e Oltre (PDF cartellone) | T1/T3-PDF | PDF valido (4.3MB), da passare all'estrattore multimodale in M5, non all'adattatore HTML |
| ScavalcaMontagne | T1 | **Adattatore HTML funziona**: estrae date/orari/comuni reali dalla pagina tournée |
| TeatroAlessandria | T1 | **Adattatore HTML funziona** |
| TeatroCuneo (comune.cuneo.it) | T1 | **Adattatore HTML funziona** |
| PiemonteDalVivo | — | Timeout di rete durante la verifica, da riprovare |
| PaesaggiVitivinicoli | T2 | Contenuto eventi caricato via JavaScript, HTML statico vuoto — nessuna REST API pubblica trovata |
| CanelliEventi | T2 | Idem: WordPress con `wp-json` attivo ma nessuna route per eventi esposta; RSS esistente ma vuoto (blog, non eventi) |
| TeatroAsti (Alfieri) | T1 potenziale | **The Events Calendar rilevato** (endpoint REST `/wp-json/tribe/events/v1/events` risponde 200) ma calendario vuoto al momento della verifica — endpoint da tenere, riprovare quando il teatro pubblica la stagione |
| TeatroTorino (eventi.comune.torino.it) | T2? | Nessun artefatto prodotto dall'adattatore HTML, da indagare (probabile rendering JS) |
| TeatroSavona (Chiabrera) | T1 | RSS esiste ma è il feed del blog, vuoto di eventi |

**Verdetto:** 3 fonti su 10 già coperte dall'adattatore HTML esistente **senza modifiche al codice** — buona conferma che l'approccio generico (04.3) funziona. Le fonti T2 (JS-rendered) sono il caso in cui il doc 04.3 prevede Playwright headless, ma solo per fonti in `polling_diretto` e con parsimonia: non ancora giustificato per queste 3.

---

## Google Sheets — riferimenti (creati 2026-08-22 sera)

Progetto Google Cloud: `calendario-eventi-504712` (numero 773254001050, nome "Calendario Eventi").
Autenticazione OAuth utente attiva (`eventi/config/token.json`, si rinnova da solo).

| Workbook | ID |
|---|---|
| Principale (Eventi, Quarantena, Config, Tipologie, Log, Serie, Stato, Newsletter, CodaFollow) | `1pqdusWT2e3JNQ9RQ7qapBM5FGLaHJ0hl6HB_n2mq0bI` |
| Anagrafiche (Perimetro, Fonti) | `1pFz9jIVNjYwGQ8Zh5Y9NfV0RpUk16bSi6sMhMy8Buy8` |
| Esteso (Eventi_estesi, Archivio) | `1ZGgRfCZK_S_rcQNBMYrGuxymYkUwbFSRCQ3BWDzA9vc` |

Salvati anche in `eventi/config/.env`. Il foglio `Eventi` è vuoto (solo intestazione): le 500 righe di test dell'accettazione M0 sono state scritte e poi ripulite.

---

## Log delle attività

| Data | Attività | Esito |
|---|---|---|
| 2026-08-22 | Lettura completa documentazione (00,03,04,06,07,08,10,11,12,13,14,15) | Fatto |
| 2026-08-22 | Ricevuti account dedicati FB/IG/email, salvati in memoria e in questo file | Fatto |
| 2026-08-22 | Verifica PiemonteItalia e VisitLMR completata | Nessun T0 diretto sui due portali; trovato dataset T0 (Geoportale, fiere, CC BY 4.0, semestrale). Dettagli in sezione dedicata sopra |
| 2026-08-22 | Creata struttura repo `eventi/` (git init), `config.py`, `store.py` (schema SQLite 10 tabelle, testato), `registry.py`, `publisher.py`, `sheets_client.py`, `run.py` | Fatto |
| 2026-08-22 | Trovate credenziali OAuth in `VecchioProgetto/Eventi/credentials.json` (client "installed", non service account) — copiate in `eventi/config/credentials.json`, adattato il codice per flusso OAuth utente invece di service account | Fatto |
| 2026-08-22 | `run.py init --skip-sheets` testato: DB SQLite creato correttamente con tutte le tabelle | Fatto |
| 2026-08-22 | `run.py init` (creazione reale 3 spreadsheet Google) avviato in background: fallito (timeout, exit 124). Il flusso OAuth `run_local_server()` non può completarsi in questo ambiente sandboxed/non presidiato: serve che l'utente lo lanci dal proprio terminale locale per vedere l'URL e autorizzare nel browser | Bloccato — azione richiesta all'utente, vedi sezione dedicata sopra |
| 2026-08-22 | M1 implementato (`src/perimetro.py`): import di `Perimetro.txt` (683 comuni entro 100km: A=255, B=200, C=228, 309 esclusi oltre soglia), risoluzione comune case-insensitive + alias, `run.py import-perimetro`. Test automatici in `tests/test_perimetro.py`, 2/2 passati | Fatto — M1 completato, non dipende dal blocco Sheets |
| 2026-08-22 | Commit git iniziale (`c9e5d34`) con M0+M1, escludendo segreti (`.env`, `credentials.json`, `token.json`) | Fatto |
| 2026-08-22 | M2 (parte deterministica): adattatori `ical.py`/`rss.py`/`jsonld.py` (parsing su fixture offline, T0 puro senza LLM), `normalizer.py` (titolo, orario, risoluzione comune livelli 1-2-5), `dedup.py` livello 1 (upsert per chiave esatta, rispetto di `bloccato`, archiviazione per `data_fine`). 12/12 test passati (`tests/test_adapters.py`, `tests/test_normalizer_dedup.py`) | Fatto — componenti pronte, integrazione end-to-end con fonti reali e Sheets ancora da fare |
| 2026-08-22 | Commit `13495a7` con M2 deterministico | Fatto |
| 2026-08-22 | M3/M5: adattatore `src/adapters/html.py` (trafilatura + pattern di data, nessun selettore per sito, 04.3), testato su fixture (3/3) | Fatto |
| 2026-08-22 | M4 (testuale): `src/prefilter.py` — schema non-evento, segnale data/parola chiave, date passate remote, lunghezza minima. 5 test mirati al criterio di accettazione (richiamo ≥95% su eventi veri), 2 bug trovati e corretti in fase di test (bypass lunghezza minima con immagine; rilevamento anno da solo come segnale di data) | Fatto — 20/20 test totali del progetto passati |
| 2026-08-22 | Commit `7a439a5` con M3/M5 adattatore HTML + M4 pre-filtro testuale | Fatto |
| 2026-08-22 | M6: `src/recurrence.py` — costruzione RRULE da campi strutturati (mai generata dall'LLM, 07.9), `regola_leggibile` in italiano, espansione con orizzonte scorrevole + eccezioni, calcolo stato di decadimento (attiva/da_verificare/sospesa). 6 test sul criterio di accettazione M6 (prima domenica del mese escluso agosto, soppressione persistente). 1 bug di codice trovato e corretto (stringa FREQ malformata), 1 errore di test corretto (BYMONTH omesso quando tutti i 12 mesi sono inclusi, coerente con la tabella 07.9) | Fatto — 26/26 test totali passati |
| 2026-08-22 (sera) | Utente ha lanciato `run.py init` dal proprio terminale: login OAuth riuscito (`token.json` creato), ma creazione spreadsheet fallita con 403 — Google Drive API non abilitata sul progetto Cloud collegato. Identificato l'ID progetto corretto: `calendario-eventi-504712` (numero 773254001050, nome "Calendario Eventi") | Bloccato — link diretti forniti all'utente per abilitare Drive API e Sheets API |
| 2026-08-22 (sera) | Utente ha abilitato le API e rilanciato `run.py init`: 3 workbook creati con successo. ID salvati in `config/.env` | Fatto |
| 2026-08-22 (sera) | Criterio di accettazione M0 eseguito contro Sheets reali (`tests/manual_m0_acceptance.py`): 500 righe scritte in 2.1s, modifica manuale di `note` sopravvissuta a un secondo rilancio. Righe di test ripulite dal foglio | **PASS — M0 completato** |
| 2026-08-22 (sera) | Aggiunta `publisher.pubblica_perimetro` e flag `--publish` a `run.py import-perimetro`. Rilanciato l'import con pubblicazione reale: foglio `Perimetro` su Sheets ora contiene 683 righe ordinate per km | **M1 completato anche lato Sheets** |
| 2026-08-22 (sera) | Utente ha fornito 10 fonti reali (teatri/portali Piemonte). Verificate una per una con httpx diretto: 3/10 producono artefatti utili con l'adattatore HTML esistente (ScavalcaMontagne, TeatroAlessandria, TeatroCuneo), 3/10 sono T2 con contenuto caricato via JavaScript (CanelliEventi, PaesaggiVitivinicoli, TeatroTorino), 2/10 hanno RSS ma vuoti di eventi (TeatroSavona, e i primi due), 1 endpoint REST rilevato ma vuoto (TeatroAsti/Alfieri, The Events Calendar), 1 PDF valido (Paesaggi e Oltre), 1 timeout di rete (PiemonteDalVivo, da riprovare) | Fatto — dettagli in tabella dedicata sopra |
| 2026-08-22 (sera) | Costruito `src/pipeline.py`: orchestrazione fetch→normalizzazione→dedup per una fonte isolata, con `run.py run --fonte/--endpoint/--metodo`. Testato contro ScavalcaMontagne reale: funziona, si ferma correttamente al pre-filtro in attesa dell'estrattore LLM (M5). 3 nuovi test end-to-end su fixture (fonte T0 produce eventi, rilancio non duplica, errore isolato) | Fatto — 29/29 test totali passati |
| 2026-08-22 (sera) | Verificato: doc 09 (stack-costi), 01, 02, 05 non esistono nella cartella Documentazione (mai scritti). Utente ha chiesto raccomandazione LLM e stato dei follow social | Fatto |
| 2026-08-22 (sera) | Confermato: procedura follow social (M9) non implementata — solo parametri di `Config` esistono. Corretto, arriva dopo M0-M8 in roadmap | Verificato, nessuna azione richiesta ora |
| 2026-08-22 (sera) | Utente ha scelto Gemini come provider di default, ma vuole poter cambiare (Claude, ChatGPT) senza riscrivere la pipeline — coerente con l'astrazione già prevista in 15.1 (`extractor/client.py`) | Decisione registrata |
| 2026-08-22 (sera) | M5: costruiti `extractor/schema.py` (Pydantic, 06.2), `extractor/prompts/testo_v1.py` (06.3/06.4), `extractor/providers.py` (Gemini/Anthropic/OpenAI, stesso contratto, provider scelto da `LLM_PROVIDER` in `.env`), `extractor/client.py` (retry su 429, contatore quota su `extractions`, controlli di sanità 06.8). 6 test con provider fittizio (nessuna chiamata reale), tutti passati al primo colpo | Fatto — 35/35 test totali passati |
| 2026-08-22 (sera) | Utente ha fornito una API key Gemini reale (progetto Cloud 773254001050). Salvata in `config/.env` (verificato: ignorato da git) | Fatto |
| 2026-08-22 (sera) | Collaudo contro Gemini reale: `gemini-2.0-flash` risultava deprecato (404, suggerito `gemini-3.6-flash`) e il package `google-generativeai` deprecato in favore di `google-genai`. Migrato `GeminiProvider` al nuovo SDK con modello `gemini-flash-latest` | Fatto |
| 2026-08-22 (sera) | **Bug reale trovato**: con solo `response_mime_type="application/json"`, Gemini rispondeva un array nudo `[]` invece dell'oggetto atteso `{"eventi": [...], "non_e_un_evento": ...}` — la validazione Pydantic falliva silenziosamente (intercettata come "json non valido", mascherando la causa reale). **Corretto** aggiungendo `response_schema=RispostaEstrazione` alla config Gemini (06.2: "se il provider supporta l'output JSON vincolato a schema, va usato") | **Bug corretto** |
| 2026-08-22 (sera) | Collaudo finale riuscito: testo integrale di ScavalcaMontagne (6098 caratteri) → **5 eventi estratti correttamente** (Ricette e Sinfonie 22/08 Prazzo, Alzati e Cammina 23/08 Celle di Macra, Summertime 27/08 Fenestrelle, Ok il Pezzo è Giusto 28/08 Fenestrelle, Ricette e Sinfonie 29/08 Lago Laux), tutte con date future, confidenza 90-95. Suite completa: 35/35 test passati dopo il fix | **PASS — M5 (client) collaudato contro provider reale** |
| 2026-08-23 | Collegato `src/pipeline.py` all'estrattore LLM: gli artefatti T1 (html) che superano il pre-filtro vengono ora passati a `ExtractorClient`, con instradamento in quarantena sotto `soglia_confidenza` (06.6) o per comune non risolvibile (07.3.7), senza mai sollevare eccezioni (15.1 regola 4). `run.py run` costruisce l'estrattore automaticamente se `LLM_API_KEY` è configurata (`--no-llm` per disabilitarlo) | Fatto |
| 2026-08-23 | **Bug reale trovato**: `extractor/client.py` salvava i timestamp di `extractions` in UTC (`datetime.now(timezone.utc)`) mentre il conteggio del budget giornaliero confronta con `date.today()` (locale) — a cavallo di mezzanotte tra i due fusi il conteggio si azzerava silenziosamente, facendo fallire il test `test_budget_esaurito_blocca_la_chiamata` (scoperto perché la data di sistema è passata da 22 a 23 agosto durante la sessione). **Corretto**: tutti i timestamp del modulo usano ora l'ora locale, coerente con 07.2 ("si lavora sempre in ora locale italiana") | **Bug corretto** |
| 2026-08-23 | 4 nuovi test per il percorso T1+LLM (pubblicazione sopra soglia, quarantena sotto soglia, quarantena per comune irrisolvibile senza eccezioni, `--no-llm` non chiama l'estrattore). Suite completa: 39/39 test passati | Fatto |
| 2026-08-23 | Collaudo end-to-end reale: `run.py run --fonte scavalcamontagne ...` con Gemini attivo → **4 eventi pubblicati** in SQLite (1 chiamata LLM, 0 in quarantena). I comuni delle tappe estratte (Celle di Macra, Fenestrelle) sono risultati fuori dal perimetro dei 683 comuni caricati (~95-101 km da Calosso, verificato con distanza aerea): la cascata di risoluzione è correttamente scesa al `comune_riferimento` della fonte con penalità -10 di confidenza (07.3.5) — comportamento corretto, non un difetto. Dati di test ripuliti da SQLite dopo la verifica | **PASS — M5 completato end-to-end** |
| 2026-08-23 | Segnato nella todo-list dedicata: TeatroAlessandria e TeatroCuneo restano da collaudare end-to-end come ScavalcaMontagne (comandi pronti in sezione dedicata) | Rimandato, non dimenticato |
| 2026-08-23 | M6 collegato alla pipeline: `src/series.py` converte il campo `ricorrenza` dell'estrattore in `RegolaRicorrenza`/RRULE, gestisce upsert della Serie (dedup, rispetto di `bloccata`, decadimento) ed espansione delle occorrenze. `pipeline.esegui_fonte` instrada gli eventi ricorrenti in Serie invece che come eventi singoli | Fatto |
| 2026-08-23 | Aggiunto supporto `serie_id`/`occorrenza` a `dedup.upsert_evento` (mancava nell'INSERT/UPDATE). Trovato e corretto lo stesso bug di timezone UTC/locale già visto in `extractor/client.py`, questa volta in `dedup._registra_fonte` | **Bug corretto** |
| 2026-08-23 | 8 nuovi test (7 in `tests/test_series.py`, 1 end-to-end in `tests/test_pipeline.py`): creazione serie, non-duplicazione, rispetto di `bloccata`, frequenza annuale non supportata, espansione occorrenze, eccezioni rispettate, comune fuori perimetro non genera eventi fantasma. Suite completa: 47/47 test passati | **PASS — M6 completato end-to-end** |
| 2026-08-23 | Richiesta utente: procedura di follow semiautomatica (M9), tetto 50/giorno (non 40 come da doc), elenco fonti da bonificare dal vecchio workbook. Trovati `Comuni.csv` (992 righe, con Facebook comunale) e `ProLoco.csv` (761 righe, Facebook+Instagram) in `VecchioProgetto`, copiati in `eventi/data/raw_import/` (non tracciato da git) | Fatto |
| 2026-08-23 | `src/bonifica_social.py`: livelli 1-2 di 13.4. **2 bug di falsi positivi trovati e corretti** durante il collaudo contro i dati reali: "igliano" annidato in "vigliano" e "bormida" annidato in "monasterobormida" venivano segnalati come entità sbagliata da un semplice match a sottostringa. Corretto con matching a token (per handle con separatori, tipo "Pro-loco-Garbagna") e a prefisso/suffisso (per handle a parola unica) — verificato che il caso reale documentato (Garbagna, doc 13.2) resti intercettato | **2 bug corretti** |
| 2026-08-23 | `python run.py populate-coda-follow` eseguito (senza `--publish`): **896 fonti pulite** importate in `coda_follow` su SQLite locale (323 fascia A, 263 B, 311 C). Foglio Sheets reale non ancora toccato | Fatto |
| 2026-08-23 | `src/follow.py`: logica di stato/circuito (precondizioni, limite giornaliero, intervallo minimo tra lotti, apertura circuito su blocco) interamente testata senza browser. Interazione Playwright reale isolata, mai eseguita. `follow_max_giornalieri` 40→50. `run.py populate-coda-follow` e `run.py follow --dry-run` pronti. 22 nuovi test (11+11), suite completa 69/69 | Fatto — **nessun login o follow reale ancora eseguito, serve azione dell'utente, vedi sezione dedicata** |
| 2026-08-23 (sera) | Installato playwright (`pip install`) e browser Chromium (`playwright install chromium`), mai fatto prima. Dato all'utente il comando `run.py follow --platform=instagram --dry-run` come "primo login" | **Istruzione errata**, corretta di seguito |
| 2026-08-23 (sera) | Utente ha lanciato `--dry-run` su Instagram e Facebook: **nessuna richiesta di login**, solo l'elenco stampato. **Bug reale**: `follow_batch` ritorna prima di aprire qualsiasi sessione browser quando `dry_run=True` — il dry-run non ha mai potuto servire da login, era un'istruzione sbagliata data all'utente. Notato anche un bug secondario nell'output: handle `people` invece del nome reale per alcuni profili Facebook (`facebook.com/people/Nome/ID`) | **2 problemi trovati** |
| 2026-08-23 (sera) | Corretto: aggiunto `run.py login --platform=X` dedicato al solo login manuale (apre il browser sulla pagina di login, aspetta la chiusura della finestra). Semplificato `_apri_sessione_browser` (rimosso uno `storage_state` ridondante con `launch_persistent_context`). Corretto l'estrattore di handle per il pattern `facebook.com/people/Nome/ID`. Verificato sui dati reali: 0 handle `people` residui su 896 righe dopo il fix. Suite completa: 69/69 test passati | **2 bug corretti, comando corretto fornito** |
| 2026-08-23 (sera) | Utente ha chiarito: l'account Facebook dedicato è una **Pagina** gestita dal profilo personale, non un secondo profilo (14.2 opzione A) — il login va fatto con le credenziali personali dell'utente | Chiarimento registrato |
| 2026-08-23 (sera) | Rischio identificato: senza gestione esplicita, dopo il login personale i follow partirebbero dal profilo personale invece che dalla Pagina, esattamente il problema che il design vuole evitare (14.1). Aggiunto `Config.facebook_page_url` e `follow._assicura_identita_pagina`: prima di ogni sessione di follow su Facebook, verifica l'indicatore "Gestisci" (visibile solo al gestore della Pagina) e tenta il cambio se non attivo; se non riesce a confermarlo, solleva `IdentitaPaginaNonAttivaError` e non esegue alcun follow. 4 nuovi test. Suite completa: 72/72 test passati | Fatto |
| 2026-08-23 (sera) | **Utente ha eseguito `run.py login --platform=instagram` e `run.py login --platform=facebook`**: login manuale completato su entrambe le piattaforme, sessioni salvate in `data/sessions/{instagram,facebook}_profile/` | **Fatto — primo traguardo operativo reale di M9** |
| 2026-08-23 (sera) | Utente ha eseguito `run.py follow --platform=instagram --dry-run` post-login: elenco di 10 Pro Loco fascia A, handle puliti | Fatto |
| 2026-08-23 (sera) | Utente ha scelto consapevolmente di procedere con un primo follow reale nonostante il riscaldamento non concluso ("procedi comunque, mi assumo il rischio"). Lanciato `run.py follow --platform=instagram --n=3`: **Instagram ha mostrato un captcha sul primo candidato** | Rischio accettato dall'utente, evento reale verificatosi |
| 2026-08-23 (sera) | Il sistema di sicurezza ha reagito correttamente (circuito aperto, lotto interrotto), ma il comando ha stampato "Nessun candidato in coda_follow" — messaggio fuorviante. **Bug reale**: `follow_batch` non appendeva alcun esito alla lista quando il blocco scattava sul primo candidato, quindi `esiti=[]` veniva scambiato per coda vuota | **Bug corretto**: esito `bloccato_da_circuito` sempre visibile |
| 2026-08-23 (sera) | Utente ha chiesto se mostrare il captcha per risolverlo a mano. Spiegato perché il progetto lo vieta esplicitamente (14.5: risolvere un captcha e continuare è il modo più rapido di perdere l'account) — nessuna funzionalità di questo tipo è stata implementata | Chiarito, nessuna azione richiesta |
| 2026-08-23 (sera) | Stato reale: **circuito Instagram aperto fino al 2026-08-26**. Nessun follow ripartirà prima di allora | In attesa, comportamento corretto |
| 2026-08-23 (sera) | Utente ha segnalato in chat 9+25 follow fatti a mano su Instagram (34 profili). Verificati uno per uno contro il perimetro e la coda esistente: 22 aggiornamenti su righe esistenti (con 3 correzioni di handle sbagliati nel dataset ereditato), 12 nuove righe inserite (inclusi 2 comuni chiariti dall'utente: Ricca e Valle Talloria come frazioni di Diano d'Alba) | Fatto — 35 profili marcati `seguito` |
| 2026-08-23 (sera) | Trovata un'anomalia nel dataset ereditato durante la verifica: riga `proloco-bormida-instagram` (comune Bormida, SV) con l'handle di Monastero Bormida (AT) — stessa classe di errore documentata in 13.2. **Corretta**: spostata in `stato='quarantena'` con nota esplicativa, non seguibile finché non chiarita | **Bug dati corretto** |
| 2026-08-23 (sera) | Notato encoding corrotto sul nome del comune "Montà" (`Mont�`) in SQLite locale — probabile problema di codifica nei CSV originali. Segnato in STATO-PROGETTO.md come bonifica da fare, non ancora corretto | Segnalato per bonifica futura |
| 2026-08-23 (sera) | Utente ha chiesto una procedura per leggere automaticamente i "seguiti" reali invece di riportarli a mano — troppo scomodo su tanti follow. Costruito `src/sync_seguiti.py`: lettura passiva (nessun click, coerente con 14.5b) della lista "seguiti"/"following", confronto con `coda_follow` (handle noti -> marcati seguiti, handle sconosciuti -> quarantena con comune da verificare, mai scartati). `run.py sync-seguiti --platform=X`. 6 test sulla logica di confronto, suite completa 79/79. **Non ancora collaudata contro un vero profilo**: solo la logica di confronto è testata, l'interazione con la pagina reale (scroll, selettori) no | Fatto — da collaudare al prossimo utilizzo |
| 2026-08-25 | Collaudo end-to-end di TeatroAlessandria e TeatroCuneo (rimasto in sospeso dal 23/08). TeatroAlessandria: trovato e corretto un bug reale — il limite anti-allucinazione fisso (20 eventi/artefatto) scartava un vero cartellone stagionale di 46 spettacoli reali; spostato in `Config.max_eventi_per_artefatto` (default 60). Rilanciato: 46/46 pubblicati. TeatroCuneo: 0 eventi, motivo verificato legittimo (stagione già passata). Dati di test ripuliti da SQLite | **PASS — entrambe le fonti collaudate end-to-end, 1 bug reale corretto** |

---

## Webapp mappa — cronaca dettagliata di sviluppo e collaudo (2026-08-31)

Spostata qui da Documentazione/16-webapp-mappa.md il 2026-09-11, in occasione
della riorganizzazione della documentazione. Contenuto originale invariato.

### Tasklist di sviluppo (v1)

- **T1 — publisher.righe_eventi_per_mappa**: JOIN dedicato tra `events` e `comuni` per `lat`/`lon`/`km`, solo eventi non archiviati. Un comune senza coordinate viene escluso, mai forzato a 0,0 (04.7). 3 test.

- **T2 — publisher.scrivi_eventi_mappa_json(righe, percorso)**: scrive `data/eventi_mappa.json` nel formato 16.3.1. Collegata a `cmd_publish` in `run.py`, subito dopo la pubblicazione di `Archivio`. L'array è sempre presente (vuoto se non ci sono eventi con coordinate), mai un file assente. 2 test. Collaudata dal vivo: 162 eventi con coordinate scritti da `run.py publish` sul database reale.

- **T3 — deciso di saltare lo spike isolato**: invece di verificare a parte l'affidabilità di un URL Drive, `mappa.html` supporta da subito entrambi i percorsi di caricamento: un `fetch()` automatico opzionale (URL configurabile in cima al file, vuoto di default) con fallback su un pulsante "Carica eventi_mappa.json..." (`<input type="file">` + `FileReader`, nessuna dipendenza di rete). Il secondo percorso funziona sempre, indipendentemente da CORS o dalla stabilità di un URL Drive.

- **T4 — API key Google Maps**: fornita dall'utente, salvata solo in `webapp/mappa.html` (mai committata: il file è in `.gitignore`). Tracciato invece `webapp/mappa.template.html`, identico ma con `YOUR_API_KEY_HERE` al posto della key reale, per lasciare la struttura visibile nel repository.

- **T5 — webapp/mappa.html**: pagina singola autosufficiente (CSS/JS inline, nessuna build): mappa centrata su Calosso (stessi `casa_lat`/`casa_lon` di `config.py`, con un marker dedicato per "Casa"), selettore data con default oggi + pulsante "Oggi", caricamento dati con entrambi i percorsi di T3.

- **T6 — Filtro per data + marker per comune**: implementato: alla selezione di una data, raggruppa gli eventi attivi quel giorno per comune e disegna un marker per gruppo (non uno per evento).

- **T7 — Popup con l'elenco eventi del comune/giorno**: click su un marker mostra titolo/tipologia/link di ogni evento di quel comune in quella data. Testo escapato contro XSS (i titoli vengono da fonti esterne non fidate). Sola consultazione: nessuna scrittura di stato/note dalla mappa, resta responsabilità esclusiva del foglio Sheets. Collaudo eseguito con Playwright: aperta `mappa.html` reale (con la key vera) da `file://`, bloccata da `RefererNotAllowedMapError` — prova diretta che le restrizioni HTTP referrer impostate dall'utente sono davvero attive. La logica di filtro/marker/popup è stata collaudata separatamente iniettando un mock minimale di `google.maps`, caricando il JSON reale generato da T2 (162 eventi): 12 comuni con marker alla data odierna, 1 comune (Cortemilia, popup con titolo e link corretti) alla data del primo evento nel dataset, 0 comuni e nessun errore su una data senza eventi (1999-01-01). Nessun errore JavaScript in nessuno scenario.

- **T8 — Collaudo dal vivo, esito: Drive non esegue né serve la pagina, usare l'apertura locale**: l'utente ha caricato `mappa.html` e `eventi_mappa.json` reali su Drive e fornito gli ID dei due file. Verificato con Playwright: il link "view" di Drive per un .html mostra il sorgente come testo, non esegue la pagina; il link `uc?export=download` forza un download, non risponde a un `fetch()`, oltre a essere comunque bloccato da CORS. Conclusione, confermata con l'utente: Drive non è adatto a servire `mappa.html` come pagina eseguibile né a un `fetch()` diretto del JSON. Scartata l'alternativa di un hosting statico dedicato (GitHub Pages) in quel momento, per restare nel vincolo di budget zero/nessun servizio esterno da mantenere. Percorso adottato: apertura locale di `mappa.html` con `eventi_mappa.json` caricato tramite il pulsante "Carica eventi_mappa.json...". Un problema aggiuntivo emerso: la key con restrizioni HTTP referrer non riconosce un referrer per un file aperto con `file://` (nessun header Referer tracciabile). Risolto servendo `mappa.html` da un piccolo webserver locale (`python -m http.server 8000`), con `http://localhost:8000/*` aggiunto ai referrer autorizzati. Collaudo finale riuscito su `http://localhost:8000/mappa.html` con la key reale: nessun `RefererNotAllowedMapError`, mappa centrata su Calosso con marker "Casa" visibile, caricamento di 168 eventi da file locale, marker distribuiti correttamente. Nessun errore JavaScript.

- **T9 — Documento e tasklist aggiornati con l'esito di T8** (superato dall'esito di T10: l'uso quotidiano finale non è più quello locale, ma l'URL pubblico).

- **T10 — Pubblicata su GitHub Pages, blocco CORS risolto alla radice**: l'utente ha chiesto esplicitamente se il blocco CORS di Drive fosse risolvibile — non lo è, è un limite della piattaforma. Scelto un hosting statico dedicato. Implementato: nuova cartella `docs/index.html`, stessa pagina di `webapp/mappa.html` con `URL_DATI_REMOTI` come path relativo (`eventi_mappa.json`) invece dell'URL Drive — HTML e JSON sullo stesso dominio, nessun `fetch()` cross-origin, nessun CORS possibile per costruzione. `run.py publish` scrive `data/eventi_mappa.json` e una copia in `docs/eventi_mappa.json`. Repository GitHub creato dall'utente (`github.com/MarcoMancini78/Eventi`), collegato come remote. Key pubblica per design: `docs/index.html` contiene la API key reale (deciso esplicitamente con l'utente, dato che GitHub Pages serve tutto in chiaro comunque — la protezione reale restano le restrizioni HTTP referrer, estese a `https://marcomancini78.github.io/*`). Pages attivato su Settings, Deploy from branch master, cartella /docs. Collaudo reale su `https://marcomancini78.github.io/Eventi/`: HTTP 200, caricamento automatico riuscito (172 eventi), nessun errore CORS, nessun `RefererNotAllowedMapError`.

### Miglioramenti richiesti dopo la v1 (2026-08-31)

- Data in formato italiano con navigazione: il selettore `<input type="date">` nativo mostra il formato del sistema operativo del visitatore. Sostituito con un controllo custom: testo "GG mese AAAA" più due pulsanti per spostarsi di un giorno, e un pulsante "Oggi".
- Dettaglio evento esteso nel popup: oltre a titolo/tipologia/link, ora mostra descrizione, periodo, distanza e fonte. Richiesta una modifica a `publisher.righe_eventi_per_mappa` (JOIN su `event_sources`) e propagazione in `scrivi_eventi_mappa_json`. 3 nuovi test.

### Fix e automazione richiesti dopo il giro precedente (2026-08-31)

- Bug trovato dall'utente: il calendario nativo non si apriva più, perché nascondere l'input date con `pointer-events:none` aveva eliminato anche il modo per aprirlo. Corretto trasformando il box della data in un bottone che chiama `input.showPicker()`.
- Data e ora in italiano nel messaggio di stato, corretto un bug per cui l'ora era sempre fissa a mezzanotte.
- Pubblicazione automatica della mappa nello script schedulato: `ricerca_eventi_automatica.bat` ora fa git add/commit/push del solo `docs/eventi_mappa.json` dopo ogni run-publish, senza interrompere lo script su fallimento del push.

### Eventi in quarantena su Eventi/mappa (2026-08-31)

Verificato che gli eventi in quarantena comparivano già, senza segnale, mescolati agli eventi confermati sulla mappa. Deciso di non nasconderli ma segnalarli: aggiunto un booleano `quarantena` al JSON e un badge giallo "Da verificare" nel popup. Collaudato sui dati reali: 29 eventi marcati, badge verificato con Playwright.

## Webapp elenco eventi — sviluppo (2026-09-10/11)

Nata il 2026-09-10 con 9 commit in meno di 24 ore, un decimo commit di fix l'11/09:

1. Redesign mobile-first, header più compatto.
2. Ordinamento su Km crescente di default, frecce indicatore, restyling.
3. Conteggio spostato nella riga filtri, restyling più moderno.
4. Numero progressivo (1..N) sugli eventi visualizzati.
5. Fix intestazione tabella che spariva durante lo scroll: `thead` aveva `position:sticky` ma il contenitore `.tabella-scroll` usava `overflow:hidden` — lo sticky funziona solo se l'antenato scrollabile (qui `main`, non `.tabella-scroll`) può mostrare l'elemento oltre i bordi del contenitore diretto. Corretto passando `.tabella-scroll` a `overflow:visible` e calcolando dinamicamente in JS il `top` dello sticky dall'altezza reale di header/filtri.
6. Fix link mappa 404 su GitHub Pages, mostra data aggiornamento dati.
7. Un solo filtro data invece di dal/al.
8. Filtro data preimpostato su oggi all'apertura.
9. Unifica Eventi ed Eventi_estesi in un unico foglio.
10. (11/09) Fix residuo: `main` restava `flex:1` senza `min-height:0`, quindi non si comprimeva mai sotto l'altezza della tabella — a quel punto scrollava la pagina intera invece di `main`, e il thead sticky restava fermo mentre header/barra-filtri apparivano fissi. Il fix del punto 5 era stato applicato solo a `webapp/elenco.html`/`elenco.template.html`, non alla copia in `docs/elenco.html` effettivamente pubblicata — propagato.
