"""L3 (12.5, 17-lavoro-residuo.md): adattatore per la variante legacy del
template AGID pa_design_system (endpoint tipo .../Eventi), su fixture
offline basata sulla struttura reale (15.1 regola 8)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.pa_design_system import (
    _anno_dal_titolo,
    _anno_piu_vicino_nel_futuro,
    _estrai_date,
    _estrai_date_testuale,
    _estrai_giorno_mese_senza_anno,
    _pagina_usa_data_pubblicazione_non_evento,
    parse_pa_design_system,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_estrae_evento_con_date_titolo_e_url_assoluto():
    html = (FIXTURES / "esempio_pa_design_system.html").read_text(encoding="utf-8")
    artefatti = parse_pa_design_system(html, source_id="comune-prova", fetch_url="https://comune-prova.it/Eventi")

    assert len(artefatti) == 1
    art = artefatti[0]
    assert art.titolo == "Sagra della Nocciola"
    assert art.data_inizio == "2026-09-12"
    assert art.data_fine == "2026-09-14"
    assert art.url == "https://comune-prova.it/Dettaglionews?IDNews=12345"
    assert "stand gastronomici" in art.descrizione


def test_parse_ignora_card_wrapper_senza_card_title():
    """Bug reale trovato ispezionando comuni con 0 eventi pubblicati: il
    widget 'feedback pagina' condivide la classe .card-wrapper con le
    card evento ma non ha mai un .card-title — deve essere scartato, non
    trattato come un evento senza titolo."""
    html = """<html><body>
    <div class="card shadow card-wrapper" id="feedback">
      <div class="card-header"><h2>Quanto sono chiare le informazioni?</h2></div>
    </div>
    </body></html>"""
    artefatti = parse_pa_design_system(html, source_id="comune-prova", fetch_url="https://x.it/Eventi")
    assert artefatti == []


def test_parse_ignora_card_senza_data_riconoscibile():
    """04.7: senza una data valida non è un evento pubblicabile, non se
    ne indovina una arbitraria."""
    html = """<html><body>
    <div class="card-wrapper">
      <a href="Dettaglionews?IDNews=1"><h3 class="card-title">Evento senza data</h3></a>
      <span class="text-paragraph-card">Testo</span>
    </div>
    </body></html>"""
    artefatti = parse_pa_design_system(html, source_id="comune-prova", fetch_url="https://x.it/Eventi")
    assert artefatti == []


def test_parse_html_malformato_non_solleva():
    """15.1 regola 4: un HTML corrotto non deve far fallire la fonte."""
    artefatti = parse_pa_design_system("<<<non e html>>>", source_id="comune-prova", fetch_url="https://x.it/Eventi")
    assert isinstance(artefatti, list)


def test_estrai_date_giorno_singolo():
    inizio, fine = _estrai_date("12/08/2026")
    assert inizio == "2026-08-12"
    assert fine == "2026-08-12"


def test_estrai_date_intervallo():
    inizio, fine = _estrai_date("20/10/2025 - 27/10/2025")
    assert inizio == "2025-10-20"
    assert fine == "2025-10-27"


def test_estrai_date_testo_senza_data():
    inizio, fine = _estrai_date("nessuna data qui")
    assert inizio is None
    assert fine is None


def test_parse_riconosce_variante_wordpress_con_card_calendar():
    """2026-09-14: la maggior parte dei comuni classificati 'wordpress' dal
    fingerprinting non espone un endpoint REST eventi (verificato: 0/15 in
    un campione), ma 56/91 usano di fatto la stessa famiglia di template
    Bootstrap Italia con markup leggermente diverso (.card-calendar
    .card-day invece di .category-top .data, titolo in
    .cmp-list-card-img__body-title invece di .card-title) — trovato
    ispezionando dal vivo Dogliani, confermato su Albisola Superiore e
    Bergeggi. Un solo parser gestisce entrambe le varianti."""
    html = (FIXTURES / "esempio_pa_design_system_wordpress.html").read_text(encoding="utf-8")
    artefatti = parse_pa_design_system(html, source_id="comune-prova", fetch_url="https://comune-prova.it/vivere-il-comune/")

    assert len(artefatti) == 1
    art = artefatti[0]
    assert art.titolo == "Manifestazioni Estate 2026"
    assert art.data_inizio == "2026-06-11"
    assert art.data_fine == "2026-11-01"
    assert art.url == "https://comune-prova.it/eventi/manifestazioni-estate-2026/"
    assert "musica e sagre" in art.descrizione


def test_estrai_date_testuale_giorno_singolo():
    inizio, fine = _estrai_date_testuale("20 Maggio 2000")
    assert inizio == "2000-05-20"
    assert fine == "2000-05-20"


def test_estrai_date_testuale_intervallo():
    inizio, fine = _estrai_date_testuale("11 Giugno 2026 - 1 Novembre 2026")
    assert inizio == "2026-06-11"
    assert fine == "2026-11-01"


def test_estrai_date_testuale_case_insensitive():
    inizio, fine = _estrai_date_testuale("5 MARZO 2027")
    assert inizio == "2027-03-05"


def test_estrai_date_testuale_senza_data():
    inizio, fine = _estrai_date_testuale("nessuna data qui")
    assert inizio is None
    assert fine is None


def test_parse_riconosce_data_testuale_con_giorno_settimana_in_categoria_top():
    """Bug reale trovato 2026-09-17 (comune-acqui-terme, sezione
    /Notizie?idCat=1, stesso template 'card-wrapper'): '.category-top .data'
    può contenere un formato testuale con giorno della settimana davanti
    ('Martedì, 08 Settembre 2026'), non solo GG/MM/AAAA. Prima del fix, si
    tentava solo il pattern numerico su questo campo e, fallito, si passava
    subito a '.card-day' (che qui contiene solo l'abbreviazione del mese,
    "set", non l'intera data) — la card veniva scartata pur avendo una
    data perfettamente leggibile in '.data'."""
    html = """<html><body>
    <div class="card-wrapper">
      <div class="card-calendar"><span class="card-date">08</span><span class="card-day">set</span></div>
      <div class="category-top">
        <a href="Notizie?idCat=1">Notizie</a><span class="data">Martedì, 08 Settembre 2026</span>
      </div>
      <a href="Dettaglionews?IDNews=415084"><h3 class="card-title">Festa dello Sport</h3></a>
      <span class="text-paragraph-card">Un appuntamento sportivo</span>
    </div>
    </body></html>"""
    artefatti = parse_pa_design_system(html, source_id="comune-acqui-terme", fetch_url="https://x.it/Notizie?idCat=1")

    assert len(artefatti) == 1
    art = artefatti[0]
    assert art.titolo == "Festa dello Sport"
    assert art.data_inizio == "2026-09-08"
    assert art.data_fine == "2026-09-08"


# --- 2026-09-17, sesta/settima variante trovata nell'audit del parser
# pa_design_system (comuni Cuneo, Carcare, Tiglieto, Pozzolo Formigaro,
# Albissola Marina, Collegno): il box calendario può non riportare mai
# l'anno, e in alcuni casi la data del box è di PUBBLICAZIONE, non
# dell'evento. ---


def test_anno_piu_vicino_nel_futuro_stesso_giorno_resta_anno_corrente():
    oggi = date(2026, 9, 16)
    assert _anno_piu_vicino_nel_futuro(16, 9, oggi) == 2026


def test_anno_piu_vicino_nel_futuro_data_gia_passata_va_all_anno_dopo():
    oggi = date(2026, 9, 16)
    assert _anno_piu_vicino_nel_futuro(28, 8, oggi) == 2027


def test_anno_piu_vicino_nel_futuro_data_ancora_da_venire_resta_anno_corrente():
    oggi = date(2026, 9, 16)
    assert _anno_piu_vicino_nel_futuro(20, 12, oggi) == 2026


def test_anno_piu_vicino_nel_futuro_29_febbraio_non_solleva():
    oggi = date(2026, 9, 16)  # 2026 non bisestile
    assert _anno_piu_vicino_nel_futuro(29, 2, oggi) == 2026


def test_anno_dal_titolo_trova_anno_a_4_cifre():
    assert _anno_dal_titolo("Antica Fiera del Bestiame dal 28 Agosto al 1° Settembre 2026") == 2026


def test_anno_dal_titolo_nessun_anno_ritorna_none():
    assert _anno_dal_titolo("Festa d'agosto") is None


def test_estrai_giorno_mese_senza_anno_usa_deduzione_se_non_esplicito():
    oggi = date(2026, 9, 16)
    inizio, fine = _estrai_giorno_mese_senza_anno("16 Settembre", oggi=oggi)
    assert inizio == fine == "2026-09-16"


def test_estrai_giorno_mese_senza_anno_preferisce_anno_esplicito():
    """Caso reale Carcare: '28 Agosto' nel box calendario, ma il titolo
    dice esplicitamente 2026 — la deduzione 'prossimo futuro' da sola
    sbaglierebbe (28 agosto già passato a metà settembre -> 2027)."""
    oggi = date(2026, 9, 16)
    inizio, fine = _estrai_giorno_mese_senza_anno("28 Agosto", anno_esplicito=2026, oggi=oggi)
    assert inizio == fine == "2026-08-28"


def test_estrai_giorno_mese_senza_anno_testo_non_valido():
    assert _estrai_giorno_mese_senza_anno("qualcosa d'altro") == (None, None)


def test_pagina_usa_data_pubblicazione_rileva_stessa_data_su_tutte_le_card():
    """Caso reale Tiglieto: ogni card della pagina mostra la stessa
    identica data odierna — segnale che è la data di pubblicazione della
    notizia, non dell'evento (un vero calendario eventi varia)."""
    import lxml.html

    oggi = date(2026, 9, 16)
    html = """<html><body>
    <div class="card-wrapper"><span class="card-date">16</span><span class="card-day">Settembre</span></div>
    <div class="card-wrapper"><span class="card-date">16</span><span class="card-day">Settembre</span></div>
    <div class="card-wrapper"><span class="card-date">16</span><span class="card-day">Settembre</span></div>
    </body></html>"""
    albero = lxml.html.fromstring(html)
    cards = albero.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " card-wrapper ")]')
    assert _pagina_usa_data_pubblicazione_non_evento(cards, oggi) is True


def test_pagina_usa_data_pubblicazione_falso_se_le_date_variano():
    import lxml.html

    oggi = date(2026, 9, 16)
    html = """<html><body>
    <div class="card-wrapper"><span class="card-date">28</span><span class="card-day">Agosto</span></div>
    <div class="card-wrapper"><span class="card-date">8</span><span class="card-day">Dicembre</span></div>
    </body></html>"""
    albero = lxml.html.fromstring(html)
    cards = albero.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " card-wrapper ")]')
    assert _pagina_usa_data_pubblicazione_non_evento(cards, oggi) is False


def test_pagina_usa_data_pubblicazione_falso_con_una_sola_card():
    """Una sola card con la data odierna non è un segnale sufficiente:
    potrebbe essere davvero l'unico evento di oggi."""
    import lxml.html

    oggi = date(2026, 9, 16)
    html = """<html><body>
    <div class="card-wrapper"><span class="card-date">16</span><span class="card-day">Settembre</span></div>
    </body></html>"""
    albero = lxml.html.fromstring(html)
    cards = albero.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " card-wrapper ")]')
    assert _pagina_usa_data_pubblicazione_non_evento(cards, oggi) is False


def test_parse_estrae_data_da_card_text_variante_cuneo():
    """Caso reale Cuneo: la data vive in '.card-text' col formato
    'GG mese AAAA - GG mese AAAA', un terzo campo mai controllato prima
    (né '.data' né '.card-day')."""
    html = """<html><body>
    <div class="card-wrapper">
      <p class="card-text font-serif">18 Settembre 2026 - 20 Settembre 2026</p>
      <h3 class="card-title"><a href="/eventi/inaugurazione-sclab/">Inaugurazione Sclab</a></h3>
    </div>
    </body></html>"""
    artefatti = parse_pa_design_system(html, source_id="comune-cuneo", fetch_url="https://x.it/eventi/")

    assert len(artefatti) == 1
    assert artefatti[0].data_inizio == "2026-09-18"
    assert artefatti[0].data_fine == "2026-09-20"


def test_parse_unisce_due_card_day_per_leggere_mese_e_anno_variante_collegno():
    """Bug reale Collegno: due elementi '.card-day' sulla stessa card, uno
    col mese ('Novembre') uno con l'anno ('2026') — il vecchio codice
    leggeva solo il primo con [0], scartando l'anno."""
    html = """<html><body>
    <div class="card-wrapper">
      <div class="card-calendar">
        <span class="card-date">14</span>
        <span class="card-day">Novembre</span>
        <span class="card-day">2026</span>
      </div>
      <h3 class="cmp-list-card-img__body-title"><a href="/eventi/luce-di-lanterna/">Luce di lanterna</a></h3>
    </div>
    </body></html>"""
    artefatti = parse_pa_design_system(html, source_id="comune-collegno", fetch_url="https://x.it/eventi/")

    assert len(artefatti) == 1
    assert artefatti[0].data_inizio == "2026-11-14"
    assert artefatti[0].data_fine == "2026-11-14"


def test_parse_deduce_anno_da_calendario_senza_anno_variante_carcare():
    """Caso reale Carcare/Pozzolo Formigaro/Albissola Marina: '.card-date'
    + '.card-day' senza alcun anno da nessuna parte nella card — l'anno
    va dedotto (stessa regola del prompt LLM: prossimo anno nel futuro)."""
    html = """<html><body>
    <div class="card-wrapper">
      <div class="card-calendar"><span class="card-date">20</span><span class="card-day">Dicembre</span></div>
      <h3 class="card-title"><a href="/eventi/luna-park/">Luna Park di Carcare</a></h3>
    </div>
    </body></html>"""
    oggi = date(2026, 9, 16)
    artefatti = parse_pa_design_system(html, source_id="comune-carcare", fetch_url="https://x.it/eventi/", oggi=oggi)

    assert len(artefatti) == 1
    assert artefatti[0].data_inizio == "2026-12-20"  # ancora nel futuro rispetto a oggi: stesso anno


def test_parse_deduce_anno_da_calendario_data_gia_passata_va_all_anno_dopo():
    html = """<html><body>
    <div class="card-wrapper">
      <div class="card-calendar"><span class="card-date">28</span><span class="card-day">Agosto</span></div>
      <h3 class="card-title"><a href="/eventi/fiera/">Fiera senza titolo con anno</a></h3>
    </div>
    </body></html>"""
    oggi = date(2026, 9, 16)
    artefatti = parse_pa_design_system(html, source_id="comune-carcare", fetch_url="https://x.it/eventi/", oggi=oggi)

    assert len(artefatti) == 1
    assert artefatti[0].data_inizio == "2027-08-28"  # 28 agosto già passato, nessun anno nel titolo -> anno dopo


def test_parse_preferisce_anno_esplicito_del_titolo_alla_deduzione():
    """Caso reale Carcare: il titolo contiene l'anno corretto (2026),
    diverso da quello che la deduzione 'prossimo futuro' produrrebbe da
    sola (2027, perché 28 agosto è già passato a metà settembre)."""
    html = """<html><body>
    <div class="card-wrapper">
      <div class="card-calendar"><span class="card-date">28</span><span class="card-day">Agosto</span></div>
      <h3 class="card-title"><a href="/eventi/fiera/">Antica Fiera del Bestiame dal 28 Agosto al 1° Settembre 2026</a></h3>
    </div>
    </body></html>"""
    oggi = date(2026, 9, 16)
    artefatti = parse_pa_design_system(html, source_id="comune-carcare", fetch_url="https://x.it/eventi/", oggi=oggi)

    assert len(artefatti) == 1
    assert artefatti[0].data_inizio == "2026-08-28"


def test_parse_scarta_intera_pagina_quando_calendario_e_data_pubblicazione():
    """Caso reale Tiglieto: tutte le card mostrano la stessa data odierna
    nel box calendario -> è la data di pubblicazione della notizia, non
    dell'evento. Nessuna card di questo tipo deve produrre un artefatto
    (04.7: meglio nessuna data che una sistematicamente sbagliata)."""
    html = """<html><body>
    <div class="card-wrapper">
      <div class="card-calendar"><span class="card-date">16</span><span class="card-day">Settembre</span></div>
      <h3 class="card-title"><a href="/n/1">Programma pro Loco 2026</a></h3>
    </div>
    <div class="card-wrapper">
      <div class="card-calendar"><span class="card-date">16</span><span class="card-day">Settembre</span></div>
      <h3 class="card-title"><a href="/n/2">Tiglieto in festa - 26 luglio 2025</a></h3>
    </div>
    </body></html>"""
    oggi = date(2026, 9, 16)
    artefatti = parse_pa_design_system(html, source_id="comune-tiglieto", fetch_url="https://x.it/eventi/", oggi=oggi)

    assert artefatti == []


# --- 2026-09-17, ottava variante trovata cercando un endpoint alternativo
# per comune-desana (endpoint precedente rotto, 404): mese abbreviato a 3
# lettere, titolo in un <h3> semplice senza classe dedicata. ---


def test_estrai_date_mese_abbreviato_giorno_singolo():
    from src.adapters.pa_design_system import _estrai_date_mese_abbreviato

    inizio, fine = _estrai_date_mese_abbreviato("25 giu 2026")
    assert inizio == fine == "2026-06-25"


def test_estrai_date_mese_abbreviato_intervallo():
    from src.adapters.pa_design_system import _estrai_date_mese_abbreviato

    inizio, fine = _estrai_date_mese_abbreviato("4 set 2026 - 6 set 2026")
    assert inizio == "2026-09-04"
    assert fine == "2026-09-06"


def test_estrai_date_mese_abbreviato_senza_data():
    from src.adapters.pa_design_system import _estrai_date_mese_abbreviato

    assert _estrai_date_mese_abbreviato("nessuna data qui") == (None, None)


def test_parse_variante_desana_mese_abbreviato_e_titolo_h3_generico():
    """Caso reale comune-desana: '.data' con mese abbreviato ("25 giu
    2026", non "25 Giugno 2026") e titolo in un <h3> senza classe
    dedicata (né '.card-title' né '.cmp-list-card-img__body-title')."""
    html = """<html><body>
    <div class="card-wrapper border border-light rounded shadow-sm cmp-list-card-img">
        <div class="card-body">
            <div class="category-top">
                <span class="text-primary">Eventi</span>
                <span class="data">25 giu 2026</span>
            </div>
            <a href="https://x.it/eventi/3589780/festa-patronale" class="text-decoration-none">
                <h3 class="text-break">Festa Patronale 2026</h3>
            </a>
            <p class="cmp-list-card-img__body-description">Dal 25 al 28 giugno</p>
        </div>
    </div>
    </body></html>"""
    artefatti = parse_pa_design_system(html, source_id="comune-desana", fetch_url="https://x.it/eventi")

    assert len(artefatti) == 1
    art = artefatti[0]
    assert art.titolo == "Festa Patronale 2026"
    assert art.data_inizio == "2026-06-25"
    assert art.url == "https://x.it/eventi/3589780/festa-patronale"


def test_parse_fallback_h3_generico_non_matcha_h2_widget_feedback():
    """Il widget 'feedback pagina' (già scartato perché non ha
    .card-title) usa <h2>, non <h3> — il nuovo fallback non deve
    riattivarlo per errore."""
    html = """<html><body>
    <div class="card shadow card-wrapper" id="feedback">
      <div class="card-header"><h2>Quanto sono chiare le informazioni?</h2></div>
    </div>
    </body></html>"""
    artefatti = parse_pa_design_system(html, source_id="comune-prova", fetch_url="https://x.it/Eventi")
    assert artefatti == []
