"""L3 (12.5, 17-lavoro-residuo.md): adattatore per la variante legacy del
template AGID pa_design_system (endpoint tipo .../Eventi), su fixture
offline basata sulla struttura reale (15.1 regola 8)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.pa_design_system import _estrai_date, _estrai_date_testuale, parse_pa_design_system

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
