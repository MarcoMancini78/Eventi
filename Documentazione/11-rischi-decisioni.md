# 11 — Rischi, limiti e decisioni aperte

## 11.1 Rischi tecnici

| Rischio | Prob. | Impatto | Mitigazione |
|---|---|---|---|
| Meta blocca l'accesso automatizzato | **alta** | medio | Piano di degradazione ([05](05-social-locandine.md#57-piano-di-degradazione)); social non sono il fondamento |
| Account social limitato o disabilitato | media | alto se principale | Account dedicato, sacrificabile, ritmo umano |
| Quota LLM insufficiente | media | medio | Pre-filtri, cache pHash, fallback su altro provider, coda differita |
| Cambio unilaterale delle quote gratuite | media | medio | Astrazione del client LLM; modello locale come riserva |
| Estrazione locandine sotto le attese | media | **alto** | Misurato in Fase 0 *prima* di costruire |
| Siti che cambiano struttura | alta | basso | L'LLM è robusto ai cambi di layout: questo è il vantaggio principale del design |
| Run che si allunga fino a diventare inutilizzabile | media | medio | Budget di tempo rigido + potatura mensile delle fonti |
| Foglio corrotto da un bug | bassa | alto | Backup settimanale automatico; SQLite come verità |
| Il progetto viene abbandonato per manutenzione eccessiva | **alta** | alto | Vedi 11.4 |
| Account dedicato bloccato durante il popolamento (troppi follow) | media | alto | Ritmo di 30-50/giorno, popolamento graduale per fasce |
| Il feed social omette post (algoritmo) | **alta** | medio | Vista cronologica; polling di riserva sulla fascia A; limite accettato |
| L'elenco diventa illeggibile per volume | **alta** | alto | Vista principale limitata + ordinamento per rilevanza ([12](12-scala-e-copertura.md#1211-loutput-non-deve-annegare)) |
| Omonimia tra comuni risolta male | media | medio | Disambiguazione con provincia e prossimità alla fonte; quarantena in caso di dubbio |
| Perdita degli eventi annuali per disattivazione di fonti dormienti | media | **alto** | Frequenza minima garantita + finestra di attenzione stagionale; il silenzio non disattiva mai |
| Quota LLM insufficiente nei picchi estivi | **alta** | medio | Cascata con modello locale; coda differita |

## 11.2 Aspetti legali e di conformità

Punti da conoscere, non consulenza legale.

**Termini di servizio.** Lo scraping automatizzato di Facebook e Instagram viola i
loro Termini di Servizio, indipendentemente dallo scopo. La conseguenza pratica
tipica non è legale ma tecnica: limitazione o chiusura dell'account. Questo è il
motivo per cui la strategia di [05](05-social-locandine.md) riduce la dipendenza dai
social, non per pruderie.

**Siti web.** Consultare pagine pubbliche a ritmo moderato per uso personale è
generalmente accettato. Vanno comunque rispettati `robots.txt`, i limiti di frequenza
e le eventuali condizioni d'uso del sito.

**Dati personali.** Nomi di organizzatori e artisti sono dati personali, ma sono
pubblicati dagli interessati stessi a fini di promozione. Per un uso strettamente
personale, non ridistribuito, il rischio è minimo. **Non raccogliere** commenti,
nomi di partecipanti, profili privati: non servono e cambiano la natura del
trattamento.

**Diritto d'autore sulle locandine.** Le locandine sono opere grafiche protette.
Salvarne una copia per uso personale è un conto; ripubblicarle è un altro. Il foglio
dovrebbe conservare l'**URL** dell'immagine, non copie ridistribuite.

**Ridistribuzione.** Le due webapp (mappa ed elenco, vedi
[16-webapp-mappa.md](16-webapp-mappa.md)) sono già pubblicate su GitHub Pages,
quindi tecnicamente accessibili a chiunque abbia il link — una forma di
ridistribuzione pubblica, anche se non promossa attivamente. Restano esposti
solo i campi minimi (titolo, comune, data, link alla fonte originale — vedi
[16.3.1](16-webapp-mappa.md)), non le locandine ridistribuite né i dati
grezzi delle fonti. Se in futuro si volesse una condivisione più ampia o
promossa attivamente, andrebbero comunque verificate licenze e attribuzione
delle fonti aggregatrici.

**Uso dei dati da parte del fornitore LLM.** Sul tier gratuito i contenuti inviati
possono essere usati per l'addestramento. Trattandosi di contenuti pubblici è
accettabile, ma è bene esserne consapevoli.

## 11.3 Limiti accettati del design

Vale la pena metterli per iscritto ora, per non scoprirli come "bug" tra sei mesi.

- **Copertura non totale.** Alcuni eventi passano solo per il passaparola o per un
  cartello in piazza. Nessun sistema li troverà.
- **Latenza.** Un evento pubblicato la mattina compare nel foglio entro 24 ore.
  Accettabile per la pianificazione, inutile per gli eventi improvvisi.
- **Errori di estrazione residui.** Anche al 90% di accuratezza, su 200 eventi ce ne
  saranno ~20 con qualcosa di sbagliato. Il sistema è un assistente, non un oracolo.
- **Le distanze sono medie**, per comune, senza traffico.
- **Gli annullamenti si intercettano male.** Vengono comunicati con post estemporanei
  difficili da collegare all'evento originale. Per gli eventi importanti, verifica
  sempre alla fonte prima di uscire di casa.
- **Le serie ricorrenti senza scadenza decadono.** Un mercatino mensile smette di
  generare occorrenze dopo ~400 giorni senza conferme. È voluto (meglio nessuna riga
  che un evento fantasma), ma significa che una serie viva ma raramente menzionata
  può sparire: se te ne accorgi, riattivala a mano dal foglio `Serie`.

## 11.4 Il rischio principale: l'abbandono

Il rischio più concreto non è tecnico. Sistemi personali come questo muoiono così:
si rompe una fonte, poi un'altra, il proprietario non se ne accorge, il foglio si
svuota gradualmente e un giorno smette di aprirlo.

Le tre contromisure previste dal design:

1. **Il foglio `Stato` con l'indicatore "zero eventi nuovi in 7 giorni" in rosso.**
   È il segnale di allarme precoce che manca quasi sempre; essendo dentro il file che
   apri comunque, non richiede notifiche.
2. **Restringimento delle fasce, non potatura delle fonti.** Il sistema deve
   *rimpicciolire* quando peggiora — riducendo il perimetro servito, cioè spostando
   comuni da B a C o da C a D. Non eliminando le fonti silenziose: quelle sono
   dormienti, non inutili ([04](04-fonti-ingestione.md#47-fonti-dormienti--fonti-inutili)).
3. **Utilità anche in modalità degradata.** Se restano solo i T0 e le newsletter, il
   foglio contiene comunque qualcosa di utile ogni settimana.

Se dopo tre mesi il sistema richiede più di 30 minuti di manutenzione al mese,
la risposta corretta è ridurre lo scope, non aggiungere funzionalità.

## 11.5 Decisioni chiuse

| # | Decisione | Esito |
|---|---|---|
| D1 | Instagram nella v1? | **Sì, incluso.** Via feed invertito, non via polling |
| D2 | Account social dedicato o personale? | **Dedicato.** Seguire ~1.400 account dal profilo personale ne stravolge il feed |
| D3 | Provider LLM primario | ~~Ibrido: modello locale per il pre-filtro binario, cloud per l'estrazione~~ — **superata da D11** (nessuna GPU disponibile nell'ambiente reale): pre-filtro deterministico, non un modello locale |
| D4 | Soglie delle fasce | Prima ipotesi 20/40/70; **rivista in D14** |
| D5 | Espansione delle ricorrenze | **Una riga per occorrenza**, generate da una regola RRULE nel foglio `Serie` ([07](07-normalizzazione-geo-dedup.md#79-ricorrenze-espansione-in-occorrenze)) |
| D6 | Eventi sportivi | **No.** `sportivo` presente in tassonomia ma `attiva = no` |
| D7 | Eventi per bambini | **No.** Idem |
| D8 | Notifiche | **Nessuna.** Diagnostica nel foglio `Stato` ([08](08-orchestrazione-operativita.md#89-monitoraggio-senza-notifiche)) |
| D9 | PC acceso ogni giorno? | **Quasi.** Recupero **coalescente**: un solo run al riavvio, mai uno per giorno perso |
| D10 | Mappatura delle fonti | **Elenco già disponibile**, ma solo il foglio `Perimetro` è affidabile ([13](13-audit-fonti.md)) |
| D12 | Popolamento dell'account social | **Graduale**, 30-50 follow/giorno per fasce |
| D13 | Comuni in fascia A | Con soglia 20 km erano ~40; soglia rivista, vedi D14 |
| D14 | Soglie delle fasce | **A ≤ 50 km** (include Alba, Acqui, Alessandria), B ≤ 75, C ≤ 100 |
| D15 | Estensione del perimetro | **Taglio a 100 km.** Oltre: fuori perimetro |
| D16 | Uso del workbook esistente | **Solo il foglio `Perimetro`.** Il resto è punto di partenza da rifare |

| D11 | GPU per modello locale | **Non disponibile.** Nessuna cascata locale: pre-filtro deterministico aggressivo + cloud ([12.10](12-scala-e-copertura.md#1210-impatto-sui-volumi-llm-senza-gpu)) |
| D17 | Account social dedicato | **Da creare.** Guida operativa in [14](14-account-social.md). Da avviare **subito**: 6-10 settimane di lead time |
| D18 | Programmazione cinematografica ordinaria | **Esclusa.** Solo arene estive, cinema all'aperto e rassegne |
| D19 | Attività commerciali (cantine, agriturismi, locali) | **Incluse ma in regime curato**: liste manuali, tetto ~200 fonti. Nessuna discovery massiva ([12.4b](12-scala-e-copertura.md#124b-due-regimi-di-copertura)) |
| D20 | Limiti di distanza per categoria | **Nessuno.** Massivo su comuni e Pro Loco su tutto il perimetro; il resto via aggregatori e liste manuali |
| D21 | Newsletter | Rilevazione **automatica** in discovery → foglio `Newsletter` con link di iscrizione; iscrizione manuale ([05.4](05-social-locandine.md#54-i-due-canali-alternativi)) |
| D22 | Gruppi e pagine di ripubblicazione | **Fonti a sé**, con ruolo di scoperta di organizzatori non mappati (alpini, parrocchie, comitati). Comune mai inferito ([14.6](14-account-social.md#146-gruppi-facebook--il-caso-che-giustifica-il-rischio)) |
| D23 | Feste, compagnie, locali | **Gestione manuale** |
| D24 | Workbook | **Nuovo.** Dei dati precedenti si esporta solo ciò che serve |
| D25 | Finestra temporale | **Nessun limite sugli eventi trovati.** Limite solo su espansione ricorrenze (120 gg) e sanità (2 anni) ([07.7](07-normalizzazione-geo-dedup.md#77-filtro-di-perimetro-e-di-interesse)) |

**Nessuna decisione bloccante rimane aperta.**

## 11.6 Domande da porsi prima di scrivere codice

Tre domande di sanità, da riprendere alla fine della Fase 0:

1. **Se Facebook diventasse inaccessibile domani, il sistema sarebbe ancora utile?**
   Se no, la strategia delle fonti va rivista.

2. **Quanti degli eventi a cui sono andato nell'ultimo anno sarebbero stati trovati
   da questo sistema?** Ripercorri mentalmente gli ultimi 10. È il test di realtà
   più onesto disponibile.

3. **Sono disposto a dedicare 20 minuti al mese di manutenzione, per sempre?**
   Se no, il progetto va ridotto a una versione minima — solo T0 e newsletter — che
   non ne richiede quasi.
