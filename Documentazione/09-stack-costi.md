# 09 — Stack e costi

Scelte tecnologiche reali, dedotte dal codice in uso — non un elenco di
alternative teoriche.

## 9.1 Componenti

| Livello | Scelta | Costo |
|---|---|---|
| Esecuzione | PC personale (Windows), nessun server | zero |
| Database operativo | SQLite locale (`eventi/data/eventi.db`) | zero |
| Pannello di controllo / vista pubblicata | Google Sheets (3 spreadsheet) | zero (quota gratuita Google Workspace personale) |
| Storage/backup | Google Drive (`run.py backup-sheets`) | zero, nella quota gratuita |
| LLM di estrazione | Gemini (`LLM_PROVIDER` in `.env`, provider intercambiabile — Anthropic/OpenAI supportati dallo stesso contratto) | quota gratuita/a consumo minimo, monitorata via `budget_llm_giornaliero` |
| Automazione browser | Playwright (Chromium) | zero, libreria open source |
| Hosting webapp pubbliche | GitHub Pages (`github.com/MarcoMancini78/Eventi`, cartella `docs/`) | zero |
| Mappa (webapp mappa) | Google Maps JavaScript API | quota gratuita, key con restrizioni HTTP referrer |
| Scheduling locale | Utilità di pianificazione Windows | zero |

## 9.2 Perché niente GPU locale

Decisione D11 ([11-rischi-decisioni.md](11-rischi-decisioni.md)): nessuna GPU
disponibile nell'ambiente reale. Niente cascata con un modello locale prima
del cloud — solo pre-filtro deterministico (`prefilter.py`) per ridurre le
chiamate LLM, poi direttamente il provider cloud. Vedi anche
[12-scala-e-copertura.md §12.10](12-scala-e-copertura.md#1210-impatto-sui-volumi-llm-senza-gpu).

## 9.3 Perché Google Sheets e non un database con interfaccia dedicata

Sheets è già uno strumento che l'utente sa usare, con editing collaborativo,
formattazione condizionale per i semafori di stato, e zero costo di hosting o
manutenzione. Il prezzo è la necessità di tenere SQLite come vera fonte di
verità e Sheets come vista sincronizzata in un'unica direzione dominante
(scrittura) più un canale ristretto di rilettura (`run.py pull-fonti`) — vedi
[03-modello-dati.md](03-modello-dati.md) e
[08-orchestrazione-operativita.md §8.8](08-orchestrazione-operativita.md#88-scrittura-su-google-sheet).

## 9.4 Perché GitHub Pages e non Google Drive

Deciso dopo un tentativo fallito con Drive (non esegue `.html` come pagina
web, blocca `fetch()` con CORS — dettagli in
[16-webapp-mappa.md](16-webapp-mappa.md)). GitHub Pages è hosting statico
gratuito, stesso dominio per HTML e dati JSON (nessun problema di CORS per
costruzione), coerente col vincolo di budget zero.

## 9.5 Cosa non è mai stato preso in considerazione

- Server/VPS dedicato — in contrasto diretto con "esecuzione su PC personale,
  budget zero".
- Database cloud gestito — SQLite locale basta ai volumi del progetto
  (migliaia di fonti, non milioni).
- Modello LLM proprietario ospitato in autonomia — richiederebbe GPU e
  infrastruttura non disponibili.
