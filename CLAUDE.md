# Eventi Langhe — istruzioni per Claude

## Tenere la documentazione allineata al codice

La documentazione di questo progetto si è disallineata dal codice reale più
volte (es. `STATO-PROGETTO.md` fermo a metà agosto mentre il codice
proseguiva; un'intera webapp — l'elenco eventi tabellare — mai documentata
per giorni). Per non ripetere il problema:

- **`STATO-PROGETTO.md`** è il cruscotto: breve (circa una pagina), dice solo
  cosa funziona oggi, cosa è in corso, prossimi passi. Non aggiungere qui
  narrazione di debug o cronaca di collaudo — quella va in `CRONACA.md`.
- Quando chiudi una funzionalità, un fix rilevante, o cambi un comportamento
  descritto in `Documentazione/`, **aggiorna la sezione pertinente prima di
  concludere la sessione** — anche solo una riga nel cruscotto. Non rimandare
  "lo scrivo dopo".
- Se introduci un nuovo comando `run.py`, una nuova tabella/colonna dati, un
  nuovo adattatore/canale, verifica se `Documentazione/03-modello-dati.md`,
  `04-fonti-ingestione.md` o il documento tecnico pertinente vanno aggiornati
  di conseguenza.
- La cronaca dettagliata di bug/collaudi/tentativi falliti va in
  `CRONACA.md` (append-only), mai nei documenti architetturali o nel
  cruscotto — altrimenti tornano a gonfiarsi e a nascondere lo stato reale.
- Se noti che un documento contraddice il codice (parametro diverso, colonna
  rimossa, comando non più esistente), segnalalo o correggilo subito invece
  di lasciarlo per un audit futuro.
