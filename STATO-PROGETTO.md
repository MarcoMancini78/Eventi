# Stato del progetto — Aggregatore Eventi Locali

> Cruscotto sempre aggiornato: cosa funziona oggi, cosa è in corso, prossimi
> passi. Niente cronaca di debug qui — quella vive in [CRONACA.md](CRONACA.md).
> Vedi [CLAUDE.md](eventi/CLAUDE.md) per la regola su come mantenerlo aggiornato.

Ultimo aggiornamento: 2026-09-11

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
  (`Config.max_eventi_per_artefatto`, non più un numero fisso).
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
  `promuovi-pa-design-system`).
- **Canali email/Telegram**: adattatori scritti e integrati nella pipeline
  (`T0_email`, `T0_telegram`), mai collaudati con credenziali reali (IMAP e
  bot token ancora da configurare in `.env`).
- **Pubblicazione su Google Sheets**: `run.py publish` scrive
  Eventi/Quarantena/Archivio/Serie/Fonti/Stato/Log; `run.py pull-fonti`
  riporta indietro le modifiche manuali (categoria, comune, azioni su
  quarantena) — unico verso Sheets→SQLite del sistema.
- **Due webapp pubbliche su GitHub Pages**, stesso dominio, stesso file dati
  (`eventi_mappa.json`, rigenerato ad ogni publish):
  - **Mappa**: https://marcomancini78.github.io/Eventi/ — filtro per data,
    marker per comune, popup con dettaglio.
  - **Elenco** (tabellare, nata il 2026-09-10): https://marcomancini78.github.io/Eventi/elenco.html
    — filtri data/comune/tipologia, ordinamento per colonna, vista a schede
    su mobile.
  - Repository: `github.com/MarcoMancini78/Eventi`, cartella pubblicata
    `docs/`. Aggiornamento dati: automatico via commit schedulati
    ("Aggiorna dati mappa"); modifiche di codice alle pagine richiedono un
    `git push` manuale.
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
- Priorità della quota LLM per fascia (soglie 70/85/100%) — non implementata.
- Adattatori dedicati per le famiglie CMS `wordpress` (13.5% dei comuni) —
  solo `pa_design_system` e `jsonld` esistono oggi.
- Newsletter come fonte automatica (discovery/fingerprinting dei moduli di
  iscrizione) — non iniziato.
- Retry mirato sulle sole fonti fallite — oggi si rilancia l'intero giro
  (il dedup evita duplicati, ma rifà lavoro).

## Prossimi passi (in ordine)

1. Collaudare `feed-social --platform=instagram` dal vivo.
2. Scrivere un adattatore dedicato per il template WordPress (13.5% dei comuni).
3. Configurare IMAP/Telegram reali e collaudare i due canali email/newsletter.
4. Costruire il retry mirato sulle fonti fallite (comando dedicato).

## Link utili

- Cronaca dettagliata (bug, collaudi, decisioni prese in corsa):
  [CRONACA.md](CRONACA.md) — copre 2026-08-22 → 2026-08-27. Per il periodo
  successivo, consultare `git log` in `eventi/`.
- Documentazione architetturale: [Documentazione/](Documentazione/00-README.md)
- Regole di processo per Claude su questo progetto: [eventi/CLAUDE.md](eventi/CLAUDE.md)
