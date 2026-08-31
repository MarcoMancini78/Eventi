"""M4 — Pre-filtro grafico (12.10 'Sulle immagini'). Immagini generate al
volo con Pillow, nessun file reale nei test — alto richiamo verificato
esplicitamente: una locandina con testo simulato non deve mai scartare."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from src import prefilter_immagini as pf


def _bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _locandina_simulata() -> Image.Image:
    """Molte righe nere ad alto contrasto: simula la densità di bordi di
    un vero manifesto con testo, senza dipendere da un file reale."""
    img = Image.new("RGB", (800, 1000), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    for y in range(50, 950, 15):
        draw.line([(50, y), (750, y)], fill=(0, 0, 0), width=3)
    return img


def test_scarta_per_dimensioni_troppo_piccole():
    piccola = Image.new("RGB", (100, 100), color=(200, 200, 200))
    scarta, motivo, _ = pf.scarta_immagine(_bytes(piccola))
    assert scarta is True
    assert motivo == "dimensioni_troppo_piccole"


def test_non_scarta_per_dimensioni_sopra_soglia():
    valida = Image.new("RGB", (500, 500), color=(200, 200, 200))
    scarta, motivo, _ = pf.scarta_immagine(_bytes(valida))
    # a 500x500 supera la soglia dimensioni, ma una foto uniforme (senza
    # bordi) scarta comunque per densita_bordi_bassa: verifica solo che
    # NON sia scartata per il motivo sbagliato
    assert motivo != "dimensioni_troppo_piccole"


def test_scarta_per_aspect_ratio_implausibile():
    largo = Image.new("RGB", (2000, 500), color=(200, 200, 200))  # entrambi i lati sopra soglia dimensioni
    scarta, motivo, _ = pf.scarta_immagine(_bytes(largo))
    assert scarta is True
    assert motivo == "aspect_ratio_implausibile"


def test_non_scarta_per_aspect_ratio_plausibile():
    verticale = Image.new("RGB", (800, 1000), color=(200, 200, 200))
    scarta, motivo, _ = pf.scarta_immagine(_bytes(verticale))
    assert motivo != "aspect_ratio_implausibile"


def test_scarta_foto_uniforme_per_densita_bordi_bassa():
    """Una foto senza contrasti (colore piatto) non ha bordi: deve
    scartare, coerente con 12.10 ('intercetta la categoria più numerosa di
    scarti: foto dell'evento dell'anno scorso')."""
    uniforme = Image.new("RGB", (800, 1000), color=(150, 150, 150))
    scarta, motivo, _ = pf.scarta_immagine(_bytes(uniforme))
    assert scarta is True
    assert motivo == "densita_bordi_bassa"


def test_non_scarta_locandina_con_testo_simulato():
    """Criterio di alto richiamo (M4, >=95%): una locandina con molto
    testo/contrasto non deve mai essere scartata dal filtro dei bordi."""
    scarta, motivo, phash = pf.scarta_immagine(_bytes(_locandina_simulata()))
    assert scarta is False
    assert phash is not None


def test_scarta_duplicato_noto_entro_soglia_hamming():
    locandina = _locandina_simulata()
    _, _, phash_originale = pf.scarta_immagine(_bytes(locandina))

    scarta, motivo, _ = pf.scarta_immagine(_bytes(locandina), phash_noti=[phash_originale])
    assert scarta is True
    assert motivo == "duplicato_di_immagine_nota"


def test_non_scarta_se_phash_noti_vuoto():
    locandina = _locandina_simulata()
    scarta, motivo, _ = pf.scarta_immagine(_bytes(locandina), phash_noti=[])
    assert motivo != "duplicato_di_immagine_nota"


def test_non_scarta_se_phash_diverso_da_tutti_i_noti():
    locandina = _locandina_simulata()
    scarta, motivo, _ = pf.scarta_immagine(_bytes(locandina), phash_noti=["0000000000000000"])
    assert motivo != "duplicato_di_immagine_nota"


def test_immagine_illeggibile_non_scarta_per_errore():
    """Alto richiamo anche sugli errori: un file corrotto/non un'immagine
    non deve bloccare l'estrazione, coerente con 'vuoto non è un errore'."""
    scarta, motivo, phash = pf.scarta_immagine(b"non e' affatto un'immagine")
    assert scarta is False
    assert "illeggibile" in motivo
    assert phash is None


def test_e_duplicato_noto_calcola_distanza_hamming_corretta():
    # 0x0F = 0b00001111, 0x00 = 0b00000000 -> distanza 4, entro la soglia 8
    assert pf.e_duplicato_noto("0f", ["00"]) is True
    # 0xff00 vs 0x0000 -> distanza 8, ancora entro la soglia (<=8, inclusiva)
    assert pf.e_duplicato_noto("ff00", ["0000"]) is True
    # 0xffff vs 0x0000 -> distanza 16, oltre la soglia
    assert pf.e_duplicato_noto("ffff", ["0000"]) is False


def test_e_duplicato_noto_ignora_hash_non_parsabili():
    assert pf.e_duplicato_noto("0f", ["non-un-hash-valido", "00"]) is True
