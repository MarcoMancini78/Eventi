# Stato del progetto — Aggregatore Eventi Locali

> Cruscotto sempre aggiornato: cosa funziona oggi, cosa è in corso, prossimi
> passi. Niente cronaca di debug qui — quella vive in [CRONACA.md](CRONACA.md).
> Vedi [CLAUDE.md](eventi/CLAUDE.md) per la regola su come mantenerlo aggiornato.

Ultimo aggiornamento: 2026-09-14

---

## Cosa funziona oggi

- **Pipeline di raccolta**: 703 fonti censite (comuni + Pro Loco), multi-tier
  (T0 diretto: iCal/RSS/JSON-LD/email/Telegram/pa_design_system; T1 HTML
  generico con estrazione LLM; aggregatori regionali via Playwright).
  Orchestrata da `run.py run` / `run.py run-publish`, isolamento totale degli
  errori per fonte.
- **Estrazione LLM**: Gemini in produzione, provider intercambiabile
  (`LLM_PROVIDER`). Gestisce ricorrenze (RRULE), confidenza con instradamento
  automatico in quarantena, tetto eventi/artefatto configurabile
  (`Config.max_eventi_per_artefatto`, non più un numero fisso). Priorità
  della quota per fascia già implementata
  (`extractor.client.decidi_degradazione_quota`: sopra 85% solo fascia A,
  sopra 70% niente estrazioni da immagine per le altre fasce) — corretto
  qui il 2026-09-14, prima segnata per errore come mancante.
- **Follow social**: operativo su Facebook e Instagram (identità verificata
  prima di ogni sessione, circuito di sicurezza su blocco/captcha). Tetti
  alzati su richiesta esplicita a `follow_per_lotto=20`,
  `follow_max_giornalieri=100` — rischio accettato consapevolmente, non il
  default prudente originale. Schedulato ogni 2 ore (`schedulazione_follow.bat`).
- **Feed social**: lettura passiva del feed Facebook collaudata dal vivo
  (eventi reali pubblicati). Instagram: script pronto, mai collaudato dal vivo.
- **Fingerprinting comuni**: tutti i 683 comuni del perimetro classificati per
  famiglia CMS (`pa_design_system` 63.7%, `wordpress` 13.5%, `drupal` 0.9%,
  sconosciuta 20.4%). Adattatori dedicati `jsonld` e `pa_design_system` in
  produzione, con comandi di promozione automatica (`promuovi-jsonld`,
  `promuovi-pa-design-system`). L'adattatore `pa_design_system` copre ora
  anche la variante di markup trovata sulla maggioranza dei comuni
  classificati `wordpress` (stessa famiglia di template Bootstrap Italia,
  card-calendar con data testuale invece di `.category-top .data` numerica)
  — nessun adattatore WordPress separato serviva: il vero endpoint REST
  eventi non è esposto (0/15 in un campione), ma il markup sì. Corretto in
  questo passaggio (2026-09-14) anche un bug nel prober che scambiava il
  feed RSS generico di WordPress (`/feed/`, presente su ogni pagina del
  sito) per l'endpoint eventi, sovrascrivendo la pagina corretta già
  trovata. Risultato: 68 fonti promosse da T1_html (con LLM) a
  T0_pa_design_system (senza LLM), totale passato da ~324 a 392 — verificato
  end-to-end su comuni reali con zero chiamate LLM per evento pubblicato.
- **Canali email/Telegram**: adattatori scritti e integrati nella pipeline
  (`T0_email`, `T0_telegram`), mai collaudati con credenziali reali (IMAP e
  bot token ancora da configurare in `.env`).
- **Pubblicazione su Google Sheets**: `run.py publish` scrive
  Eventi/Quarantena/Archivio/Serie/Fonti/Stato/Log; `run.py pull-fonti`
  riporta indietro le modifiche manuali (categoria, comune, azioni su
  quarantena) — unico verso Sheets→SQLite del sistema.
- **Tre webapp pubbliche su GitHub Pages**, stesso dominio:
  - **Mappa**: https://marcomancini78.github.io/Eventi/ — filtro per data,
    marker per comune, popup con dettaglio. Dati: `eventi_mappa.json`.
  - **Elenco** (tabellare, nata il 2026-09-10): https://marcomancini78.github.io/Eventi/elenco.html
    — filtri data/comune/tipologia, ordinamento per colonna, vista a schede
    su mobile. Stesso `eventi_mappa.json` della mappa.
  - **Perimetro** (elenco comuni, nata il 2026-09-11): https://marcomancini78.github.io/Eventi/perimetro.html
    — un comune per riga con sito/social del comune, sito/social Pro Loco,
    e "Altro" per teatri/attività collegate. Dati: `perimetro.json`,
    rigenerato ad ogni `publish`.
  - Repository: `github.com/MarcoMancini78/Eventi`, cartella pubblicata
    `docs/`. Aggiornamento dati: automatico via commit schedulati
    ("Aggiorna dati mappa"); modifiche di codice alle pagine richiedono un
    `git push` manuale.
- **Collegamento teatri↔comune**: `run.py collega-teatri` deduce e salva il
  comune dei teatri/attività da `coda_follow.soggetto` (comando manuale, non
  schedulato — da rilanciare solo se si aggiungono nuovi teatri).
- **Backup**: `run.py backup-sheets` copia lo spreadsheet principale su una
  cartella Drive dedicata.
- **Pulizia locale**: `run.py cleanup` rimuove backup manuali di `eventi.db`
  e file scratch/debug più vecchi di 7 giorni in `data/` (elenco di default,
  `--esegui` per rimuoverli davvero). Aggiunto il 2026-09-11 dopo aver
  trovato ~260 MB accumulati senza alcuna procedura di pulizia.
- **Operatività (M11)**: lock file, scheduling coalescente, foglio `Stato`,
  `run.py doctor` — tutti presenti nel codice. Non risulta un collaudo
  esplicito del criterio di accettazione completo (spegnimento reale di 3
  giorni), da verificare.
- **Comandi di correzione mirata**: `correggi-post` (ri-estrae un evento
  social), `correggi-fonte-html` (rilancia una fonte T1/aggregatore),
  `riprocessa-quarantena` (ricorregge tutta la quarantena in un colpo solo).

## In corso / a metà

- Instagram: feed sociale mai collaudato dal vivo (solo Facebook).
- `social_polling.py` per le fonti `polling_diretto` come rete di sicurezza
  sul feed — non ancora scritto.
- Residuo dei comuni `wordpress` senza la variante card-wrapper riconosciuta
  (17/85 verificati non promossi): probabilmente pagine eventi con struttura
  ancora diversa, non ispezionate singolarmente — restano su T1_html/LLM.
- Newsletter come fonte automatica (discovery/fingerprinting dei moduli di
  iscrizione) — non iniziato.
- Retry mirato sulle sole fonti fallite — oggi si rilancia l'intero giro
  (il dedup evita duplicati, ma rifà lavoro).
- **Finestra di attenzione stagionale** (04.7, 12.9): i dati per calcolarla
  esistono già in `Archivio`, ma `scheduling.py` non li aggrega —
  `bonus_stagionale` resta sempre a 0. Impatto pratico oggi basso: la
  formula di priorità decide solo l'*ordine* di elaborazione quando il
  tempo è scarso, ma ogni run analizza già tutte le 722 fonti (sia web sia
  social) senza mai esaurire il budget — quindi nessuna fonte viene saltata
  per mancanza di questo bonus. Resta un gap concettuale rispetto al design
  originale, ma non un buco di copertura reale nella situazione attuale.
- Email/Telegram: adapter pronti (`T0_email`, `T0_telegram`) ma
  `IMAP_HOST`/`IMAP_PASSWORD`/`TELEGRAM_BOT_TOKEN` restano vuoti in `.env` —
  zero copertura pratica finché non vengono configurati e collaudati.
- Altri aggregatori regionali (VisitPiemonte, Sagr.it, GuidaTorino) mai
  verificati per un possibile T0 diretto — solo VisitLMR controllato finora.
- Dizionario dei luoghi (07.4, "cresce da solo dalle conferme in quarantena")
  — nessuna tabella `luoghi` nello schema, il meccanismo non risulta
  implementato nonostante descritto come esistente in 03/07.

## Prossimi passi (in ordine)

1. Ispezionare i 17 comuni `wordpress` rimasti su T1_html dopo la
   promozione del 2026-09-14, per capire se serve una terza variante di
   markup o restano casi isolati.
2. Collaudare `feed-social --platform=instagram` dal vivo.
3. Configurare IMAP/Telegram reali e collaudare i due canali email/newsletter.
4. Costruire il retry mirato sulle fonti fallite (comando dedicato).
5. Aggregare la finestra di attenzione stagionale da `Archivio` in
   `scheduling.py` — dati già disponibili, solo da collegare, ma priorità
   bassa: nessun impatto sulla copertura reale finché il giro copre sempre
   tutte le fonti.

## Link utili

- Cronaca dettagliata (bug, collaudi, decisioni prese in corsa):
  [CRONACA.md](CRONACA.md) — copre 2026-08-22 → 2026-08-27. Per il periodo
  successivo, consultare `git log` in `eventi/`.
- Documentazione architetturale: [Documentazione/](Documentazione/00-README.md)
- Regole di processo per Claude su questo progetto: [eventi/CLAUDE.md](eventi/CLAUDE.md)
