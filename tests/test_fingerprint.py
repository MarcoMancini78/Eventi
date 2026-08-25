"""M8: fingerprinting per famiglia di piattaforma, su HTML campione (15.1 regola 8).

I frammenti usati qui riproducono indizi reali verificati empiricamente
(2026-08-25) su siti comunali del perimetro: comune.cuneo.it (WordPress +
Yoast), comune.asti.it/comune.alessandria.it (Drupal 9), comune.alba.cn.it
(Bootstrap Italia / design system AGID).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fingerprint import classifica_html, url_prevedibile_comune


def test_classifica_wordpress_da_wp_content():
    html = """
    <html><head>
    <!-- This site is optimized with the Yoast SEO Premium plugin v28.2 -->
    <link rel="stylesheet" href="/wp-content/themes/comune/style.css">
    </head><body>Comune di Prova</body></html>
    """
    fp = classifica_html(html)
    assert fp.piattaforma == "wordpress"
    assert fp.indizi


def test_classifica_drupal_da_meta_generator():
    html = """
    <html><head>
    <meta name="Generator" content="Drupal 9 (https://www.drupal.org)" />
    <meta name="MobileOptimized" content="width" />
    </head><body>Comune di Prova</body></html>
    """
    fp = classifica_html(html)
    assert fp.piattaforma == "drupal"


def test_classifica_pa_design_system_da_bootstrap_italia_e_agid():
    html = """
    <html><head>
    <link rel="stylesheet" href="/bootstrap-italia/dist/css/bootstrap-italia.min.css">
    <link rel="stylesheet" href="/css/agid.css?id=8e7e936f4bacc1509d74">
    </head><body>Comune di Prova</body></html>
    """
    fp = classifica_html(html)
    assert fp.piattaforma == "pa_design_system"


def test_classifica_sconosciuta_senza_indizi():
    html = "<html><head><title>Sito generico</title></head><body>Nessun indizio qui</body></html>"
    fp = classifica_html(html)
    assert fp.piattaforma == "sconosciuta"
    assert fp.indizi == []


def test_ordine_priorita_wordpress_prima_di_altri():
    """Un tema WordPress potrebbe includere per caso Bootstrap: wp-content
    resta il segnale più specifico e va riconosciuto per primo."""
    html = """
    <html><head>
    <link rel="stylesheet" href="/wp-content/themes/comune/bootstrap.min.css">
    </head><body>Comune di Prova</body></html>
    """
    fp = classifica_html(html)
    assert fp.piattaforma == "wordpress"


def test_url_prevedibile_comune_costruisce_pattern_noto():
    url = url_prevedibile_comune("Cuneo", "CN")
    assert url == "https://www.comune.cuneo.cn.it/"


def test_url_prevedibile_comune_normalizza_nome_con_spazi():
    url = url_prevedibile_comune("Isola d'Asti", "AT")
    assert url == "https://www.comune.isoladasti.at.it/"
