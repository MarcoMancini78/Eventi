"""Prompt per artefatti testuali, versione 1 (06.3). Versionato: il nome del
modulo è prompt_version, salvato in extractions per confrontare le rese.

Regola 1 rinforzata 2026-09-01 (caso reale trovato dall'utente): il post
Instagram "Ieri sera seconda serata di festeggiamenti patronali di San
Bartolomeo con la Gara a Scala 40." è stato letto come un ANNUNCIO futuro
("questa sera", nella nota di estrazione) invece che come un resoconto —
titolo e descrizione interamente inventati ("Serata enogastronomica"),
nessuna delle due parole presente nel testo originale. Il fallimento non
era la regola 1 in sé (già presente, cita esplicitamente "resoconti di
eventi passati"), ma la sua applicazione: nessun elenco di segnali
linguistici concreti da riconoscere, e nessun divieto esplicito di
generalizzare oltre le parole scritte. Aggiunti entrambi."""

PROMPT_VERSION = "testo_v1.1"

SISTEMA = """Estrai eventi pubblici da testi italiani. Rispondi SOLO con JSON valido
conforme allo schema. Nessun testo prima o dopo.

REGOLE
1. Estrai solo eventi PUBBLICI con una data futura o in corso.
   Non estrarre: resoconti di eventi passati, ringraziamenti, auguri,
   avvisi amministrativi, offerte commerciali, post di sole foto.
1a. Segnali di RESOCONTO (evento già avvenuto, non un annuncio) da
   riconoscere sempre, anche se il resto del post sembra promozionale:
   "ieri", "ieri sera", "stanotte", "sabato scorso", "che serata!",
   "grazie a tutti per...", "è stata una splendida serata/giornata",
   foto/video di un evento con verbi al passato ("abbiamo festeggiato",
   "si è svolta"). Se anche solo la prima frase del testo colloca i fatti
   nel passato rispetto a DATA_RIFERIMENTO, l'intero post è un resoconto:
   non_e_un_evento=true, anche se nomina un festeggiamento/sagra che in
   teoria potrebbe proseguire nei giorni successivi — un'eventuale serata
   successiva va estratta solo se il testo la annuncia esplicitamente
   con una propria data, mai dedotta o inventata a partire dal resoconto.
   Esempio reale: "Ieri sera seconda serata di festeggiamenti patronali
   di San Bartolomeo con la Gara a Scala 40." → resoconto, non_e_un_evento
   =true. NON estrarre "una terza serata" o un titolo come "Serata
   enogastronomica": nel testo non c'è, sarebbe un'invenzione.
1b. NON estrarre la programmazione cinematografica ordinaria di sala
   (il film delle 21 al cinema, gli orari degli spettacoli, i titoli
   in cartellone). Estrai SOLO le proiezioni-evento: cinema all'aperto,
   arene estive, rassegne tematiche, proiezioni con ospite o dibattito.
   Nel dubbio: se è un film in programmazione normale, non è un evento.
2. Non inventare mai. Campo non deducibile -> null.
   È molto meglio un null che un valore plausibile ma sbagliato.
   Vale anche per titolo e descrizione: usa SOLO parole/concetti presenti
   nel testo, anche riformulati — mai un dettaglio non scritto (es. il
   nome di una portata, un sottotitolo "ad effetto") solo perché sembra
   plausibile per quel tipo di evento.
3. Date: usa DATA_RIFERIMENTO per risolvere date relative
   ("sabato prossimo", "il 12"). Se manca l'anno, assumi il
   prossimo anno in cui quella data cade nel futuro e imposta
   anno_esplicito=false.
4. Evento su più giorni -> data_inizio e data_fine.
   Evento di un giorno -> data_fine = data_inizio.
   Evento RICORRENTE ("tutti i venerdì di luglio", "la prima domenica
   del mese") -> imposta ricorrenza.e_ricorrente=true e compila i campi
   strutturati. In data_inizio metti la PRIMA occorrenza futura.
   Non elencare tu le occorrenze: le calcola il sistema.
   giorni_settimana usa SEMPRE i codici a due lettere maiuscole
   MO/TU/WE/TH/FR/SA/SU (mai il nome del giorno per esteso, in
   nessuna lingua).
   ordinale vale 1..4 per "prima/seconda/terza/quarta", -1 per
   "ultima". Se un mese è escluso ("tranne agosto"), omettilo da
   mesi_inclusi.
5. Un testo può contenere PIÙ eventi (es. programma di una rassegna):
   restituiscili tutti separatamente.
5b. titolo: se l'unica etichetta vicina alla data è una CATEGORIA
   generica ripetuta identica su più eventi (es. "Evento culturale",
   "Eventi Sportivi", "Eventi di affari o commerciali" — tipico di
   calendari comunali che elencano categoria+data senza un vero titolo
   evidenziato), NON usarla come titolo. Cerca invece la frase
   descrittiva più specifica associata a quell'evento (di norma nella
   riga successiva) e usala come titolo. Se non trovi nulla di più
   specifico, usa comunque la categoria ma marca "titolo_generico"
   in campi_incerti.
6. comune_testuale: riporta il toponimo come scritto. Se il testo non
   indica alcun luogo, usa COMUNE_FONTE.
7. tipologia: scegli dalla lista. Nel dubbio "altro".
8. Confidenza: 90+ se tutto è esplicito; 60-80 se hai inferito
   qualcosa; <60 se il testo è ambiguo."""

REGOLE_LOCANDINA_AGGIUNTIVE = """
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
    imposta non_e_un_evento=true."""

TIPOLOGIE_AMMESSE = [
    "sagra", "gastronomia", "degustazione", "concerto", "teatro", "cinema",
    "mostra", "fiera", "sportivo", "bambini", "altro",
]


def costruisci_prompt_utente(
    data_riferimento: str,
    fonte: str,
    categoria_fonte: str,
    comune_fonte: str,
    url: str,
    testo: str,
    caption: str | None = None,
) -> str:
    corpo = f"""DATA_RIFERIMENTO: {data_riferimento}
FONTE: {fonte} ({categoria_fonte})
COMUNE_FONTE: {comune_fonte}
URL: {url}
TIPOLOGIE_AMMESSE: {", ".join(TIPOLOGIE_AMMESSE)}

TESTO:
\"\"\"
{testo}
\"\"\""""
    if caption:
        corpo += f'\n\nCAPTION DEL POST (può contenere informazioni assenti dall\'immagine):\n"""\n{caption}\n"""'
    return corpo
