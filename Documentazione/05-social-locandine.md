# 05 — Social e locandine

Questo documento era citato da molti altri (04, 06, 08, 11, 12, 14) ma non era
mai stato scritto — il contenuto era rimasto disperso tra quei documenti e le
scoperte fatte in corsa durante l'implementazione. Qui si raccoglie la
strategia unificata, con rimandi al documento che tratta ciascun dettaglio.

## 5.1 Il problema

Gran parte degli eventi locali (feste, sagre, serate) non vive su un sito con
un calendario: vive **solo sui social**, spesso **solo come immagine**
(locandina), pubblicata da centinaia di Pro Loco/comuni/associazioni diverse.
Visitare ogni profilo uno per uno non scala (migliaia di soggetti) e rischia
il blocco della piattaforma se automatizzato ingenuamente.

## 5.2 La leva: inversione del feed

Non si visitano i profili uno per uno: **un account dedicato li segue tutti**
(Facebook Pagina + Instagram, mai il profilo personale) e si legge il proprio
feed cronologico in un'unica sessione — un fattore di riduzione di circa 20×
rispetto a visitare ogni fonte singolarmente, e un profilo di rischio più
basso perché scorrere il proprio feed è un comportamento da utente normale.

Dettagli implementativi:
- Creazione, riscaldamento e coda di follow: [14-account-social.md](14-account-social.md).
- Perché l'inversione conviene a scala: [12-scala-e-copertura.md §12.3](12-scala-e-copertura.md#123-l1--inversione-del-feed-social-).
- Lettura passiva del feed (mai follow e lettura nella stessa sessione, almeno
  un'ora di distanza): modulo `src/feed_social.py`, comando
  `run.py feed-social --platform=X`.

## 5.3 La locandina è il formato principale, non un'eccezione

Niente OCR + regole scritte a mano: un **modello visuale multimodale** legge
l'immagine e restituisce lo stesso schema JSON usato per il testo. Con
l'hashing percettivo (`image_cache.phash`), la stessa locandina ripubblicata
su più canali viene analizzata una volta sola.

- Prompt e schema di estrazione: [06-estrazione-llm.md](06-estrazione-llm.md).
- Un carosello Instagram multi-immagine viene trattato come una sequenza di
  eventi potenzialmente indipendenti (una locandina per serata), non come un
  unico evento con più foto.
- La data di un post social è **quella di pubblicazione**, non quella di
  lettura del feed — su Facebook si ottiene solo con l'hover sul tooltip
  della data (non è nel markup statico), su Instagram dall'attributo
  `datetime` del post.

## 5.4 I due canali alternativi

Oltre ai social, alcuni soggetti pubblicano solo su newsletter via email o su
un canale Telegram. Questi non sono canali di notifica in uscita del
sistema — restano **fonti da ingerire**, con lo stesso contratto degli altri
adapter (funzione pura di parsing testabile + classe Adapter che fa I/O).

- **`src/adapters/email_imap.py`** (tier `T0_email`): legge una casella IMAP
  dedicata (`eventi.langa@gmail.com`), filtra per mittente atteso
  (`fonte["endpoint"]`) per isolare la newsletter di un soggetto specifico
  dalle altre email nella stessa casella condivisa. Preferisce `text/plain`,
  fallback `text/html`; gli allegati immagine finiscono in
  `data/cache/images/{source_id}/` per l'estrazione VLM a valle, senza essere
  interpretati dall'adapter stesso.
- **`src/adapters/telegram.py`** (tier `T0_telegram`): bot ufficiale via API
  HTTP (`getUpdates`, polling, nessun webhook), il bot deve essere già membro
  del canale (passo manuale). Filtra per chat_id/`@username` atteso tra gli
  update ricevuti (il bot riceve update da tutti i canali di cui è membro).

**Stato**: entrambi integrati in `pipeline.esegui_fonte`, mai collaudati con
credenziali reali — `IMAP_HOST`/`IMAP_PASSWORD`/`TELEGRAM_BOT_TOKEN` non
ancora configurati in produzione. La rilevazione automatica dei moduli
newsletter (trovare da soli i moduli di iscrizione sui siti) dipende dalla
discovery/fingerprinting (vedi [04-fonti-ingestione.md](04-fonti-ingestione.md))
e non è ancora stata costruita.

## 5.7 Piano di degradazione

Se una piattaforma social blocca l'accesso automatizzato (captcha persistente,
account sospeso) il sistema **non deve fermarsi nel complesso**: i social non
sono il fondamento della raccolta, solo un canale aggiuntivo.

- **Circuito aperto** (`follow.py`): su blocco/captcha, il lotto di follow si
  ferma immediatamente e il circuito resta aperto per un tempo fisso (72 ore
  su un blocco reale) prima di riprovare — mai un retry immediato, mai un
  bypass manuale del captcha per poi continuare (14.5: è il modo più rapido
  di far disabilitare l'account).
- **Feed e follow restano isolati**: un blocco sul follow non impedisce la
  lettura passiva del feed (rischio molto più basso), e viceversa.
- **Le altre fonti proseguono indipendentemente**: budget e coda per fonte
  (vedi [08-orchestrazione-operativita.md](08-orchestrazione-operativita.md))
  isolano ogni fallimento — un canale social bloccato non consuma il budget
  di tempo delle fonti T0/T1 che non dipendono da esso.
- **Nessuna automazione silenziosa sui blocchi**: un blocco va sempre visibile
  nell'output del comando che lo incontra, mai solo loggato in un file che
  nessuno guarda.

## 5.8 Cosa resta esplicitamente fuori scope

- Interazioni sui social oltre a follow e lettura passiva (commenti, like,
  messaggi) — mai previste, aumenterebbero il rischio di blocco senza
  benefici per la raccolta.
- Un canale di notifica in uscita via email/Telegram verso l'utente — il
  sistema non manda mai nulla attivamente, la consultazione resta sul foglio
  Sheets e sulle webapp ([16-webapp-mappa.md](16-webapp-mappa.md)).
