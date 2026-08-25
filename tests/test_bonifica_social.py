"""Bonifica dei link social ereditati (13.4): livello 1 sintattico, livello 2 coerenza entità."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bonifica_social import bonifica_url

COMUNI_PERIMETRO = [
    "Calosso", "Asti", "Refrancore", "Vigliano d'Asti", "Igliano",
    "Monastero Bormida", "Castelnuovo Bormida", "Cengio", "Garbagna", "Montemarzino",
]


def test_livello1_scarta_widget_di_condivisione():
    assert bonifica_url("https://facebook.com/sharer/sharer.php?u=x", "Calosso", COMUNI_PERIMETRO) is None
    assert bonifica_url("https://twitter.com/intent/tweet?text=x", "Calosso", COMUNI_PERIMETRO) is None


def test_livello1_scarta_concatenazione_di_url():
    url = "https://comune.porte.to.it/rss.aspxhttps://www.facebook.com/borgo"
    assert bonifica_url(url, "Calosso", COMUNI_PERIMETRO) is None


def test_livello1_normalizza_deep_link_a_profilo():
    b = bonifica_url("https://www.facebook.com/prolococalosso/events", "Calosso", COMUNI_PERIMETRO)
    assert b is not None
    assert b.url == "https://www.facebook.com/prolococalosso"
    assert b.stato == "ok"


def test_livello1_marca_permalink_instagram_da_risolvere():
    b = bonifica_url("https://instagram.com/p/DRHIBFfDZfV", "Calosso", COMUNI_PERIMETRO)
    assert b.stato == "quarantena"
    assert b.motivo == "permalink_post_da_risolvere"


def test_livello1_marca_profilo_numerico_da_risolvere():
    b = bonifica_url("https://www.facebook.com/100064467713275", "Calosso", COMUNI_PERIMETRO)
    assert b.stato == "quarantena"
    assert b.motivo == "id_numerico_da_risolvere"


def test_livello1_marca_gruppo_facebook():
    b = bonifica_url("https://www.facebook.com/groups/sagrepiemonte", "Calosso", COMUNI_PERIMETRO)
    assert b.stato == "quarantena"
    assert b.motivo == "gruppo_facebook"


# Bug reale trovato in coda_follow (2026-08-25): 46 righe con handle
# inutilizzabile ('p', 'pages', 'events', 'explore', 'reel') ereditate dal
# dataset originale — frammenti di URL che il pattern generico prendeva
# letteralmente, producendo handle identici e inutili per righe diverse.

def test_livello1_recupera_handle_da_profilo_p_facebook():
    b = bonifica_url(
        "https://www.facebook.com/p/Pro-Loco-Montechiaro-dAcqui-100045573854924",
        "Calosso", COMUNI_PERIMETRO,
    )
    assert b.stato == "ok"
    assert b.handle == "Pro-Loco-Montechiaro-dAcqui-100045573854924"


def test_livello1_recupera_handle_da_profilo_pages_facebook():
    b = bonifica_url(
        "https://www.facebook.com/pages/Pro-Loco-Monchiero/144965495559893",
        "Calosso", COMUNI_PERIMETRO,
    )
    assert b.stato == "ok"
    assert b.handle == "Pro-Loco-Monchiero-144965495559893"


def test_livello1_marca_evento_standalone_facebook():
    b = bonifica_url(
        "https://www.facebook.com/events/pro-loco-refrancore/festa-cerro-tanaro/1900301450258547",
        "Calosso", COMUNI_PERIMETRO,
    )
    assert b.stato == "quarantena"
    assert b.motivo == "link_a_evento_non_a_pagina"


def test_livello1_marca_location_tag_instagram():
    b = bonifica_url(
        "https://www.instagram.com/explore/locations/1021219573/pro-loco-ponti",
        "Calosso", COMUNI_PERIMETRO,
    )
    assert b.stato == "quarantena"
    assert b.motivo == "tag_di_localita_non_e_un_profilo"


def test_livello1_marca_reel_standalone_instagram():
    b = bonifica_url("https://www.instagram.com/reel/ABC123xyz", "Calosso", COMUNI_PERIMETRO)
    assert b.stato == "quarantena"
    assert b.motivo == "link_a_reel_non_a_profilo"


def test_livello2_intercetta_entita_sbagliata_caso_reale_documentato():
    """13.2: Pro Loco Asti con link a prolocodiRefrancore."""
    b = bonifica_url("https://www.facebook.com/prolocodiRefrancore", "Asti", COMUNI_PERIMETRO)
    assert b.stato == "quarantena"
    assert "Refrancore" in b.motivo


def test_livello2_intercetta_garbagna_caso_reale_documentato():
    b = bonifica_url("https://www.facebook.com/Pro-loco-Garbagna-Al", "Montemarzino", COMUNI_PERIMETRO)
    assert b.stato == "quarantena"
    assert "Garbagna" in b.motivo


def test_livello2_non_produce_falso_positivo_su_nome_annidato():
    """'igliano' è sottostringa di 'viglianodasti' per puro accidente ortografico: non è un errore."""
    b = bonifica_url("https://www.facebook.com/prolocoviglianodasti", "Vigliano d'Asti", COMUNI_PERIMETRO)
    assert b.stato == "ok"


def test_livello2_non_produce_falso_positivo_su_comune_composto():
    """'Bormida' è parte legittima del nome 'Monastero Bormida': non è un comune diverso."""
    b = bonifica_url("https://www.instagram.com/proloco_monasterobormida", "Monastero Bormida", COMUNI_PERIMETRO)
    assert b.stato == "ok"


def test_url_vuoto_ritorna_none():
    assert bonifica_url("", "Calosso", COMUNI_PERIMETRO) is None
    assert bonifica_url("   ", "Calosso", COMUNI_PERIMETRO) is None
