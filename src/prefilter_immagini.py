"""M4 — Pre-filtro grafico (12.10 "Sulle immagini"): scarta a costo zero
prima di spendere una chiamata VLM. Stesso principio del pre-filtro
testuale (prefilter.py): alto richiamo, non massima riduzione — un falso
negativo (locandina vera scartata) è un evento perso per sempre, un falso
positivo costa solo una chiamata in più.

Regole nell'ordine dato dalla specifica, dalla più economica (dimensioni,
quasi gratis) alla più costosa (densità di bordi, richiede decodificare i
pixel):
    1. lato minore < 400px
    2. rapporto d'aspetto fuori dall'intervallo plausibile per una locandina
    3. pHash identico (entro una soglia) a un'immagine nota (logo/foto
       profilo) — il chiamante passa l'elenco di pHash noti da escludere,
       questo modulo non conosce la fonte dei dati
    4. densità di bordi bassa (filtro di Sobel): una locandina è densa di
       testo/contrasti, una foto normale no
"""
from __future__ import annotations

import numpy as np
from PIL import Image

_LATO_MINORE_MINIMO_PX = 400
_ASPECT_RATIO_MIN = 0.4   # più stretta di un poster molto verticale è sospetta
_ASPECT_RATIO_MAX = 2.5   # più larga di un doppio banner è sospetta
_DISTANZA_HAMMING_MASSIMA_DUPLICATO = 8  # 12.10: "pHash con distanza di Hamming <= 8"
_SOGLIA_DENSITA_BORDI = 0.02  # frazione di pixel con gradiente forte, tarata empiricamente


def _apri_immagine(percorso_o_bytes) -> Image.Image:
    if isinstance(percorso_o_bytes, (bytes, bytearray)):
        import io

        return Image.open(io.BytesIO(percorso_o_bytes))
    return Image.open(percorso_o_bytes)


def dimensioni_troppo_piccole(immagine: Image.Image) -> bool:
    larghezza, altezza = immagine.size
    return min(larghezza, altezza) < _LATO_MINORE_MINIMO_PX


def aspect_ratio_implausibile(immagine: Image.Image) -> bool:
    larghezza, altezza = immagine.size
    if altezza == 0:
        return True
    rapporto = larghezza / altezza
    return not (_ASPECT_RATIO_MIN <= rapporto <= _ASPECT_RATIO_MAX)


def calcola_phash(immagine: Image.Image) -> str:
    """Wrapper sottile su imagehash.phash: isolato qui così il resto del
    modulo (e i chiamanti) dipendono da una funzione di questo progetto,
    non direttamente dalla libreria terza — più facile da sostituire."""
    import imagehash

    return str(imagehash.phash(immagine))


def e_duplicato_noto(phash_immagine: str, phash_noti: list[str]) -> bool:
    """12.10: 'immagine identica (pHash) al logo o alla foto profilo della
    pagina — molto frequente'. Confronta la distanza di Hamming tra hash
    esadecimali della stessa lunghezza (imagehash.phash produce sempre lo
    stesso formato), senza serializzare di nuovo con la libreria."""
    if not phash_noti:
        return False
    valore_immagine = int(phash_immagine, 16)
    for noto in phash_noti:
        try:
            distanza = bin(valore_immagine ^ int(noto, 16)).count("1")
        except ValueError:
            continue
        if distanza <= _DISTANZA_HAMMING_MASSIMA_DUPLICATO:
            return True
    return False


def densita_bordi_bassa(immagine: Image.Image) -> bool:
    """12.10: 'densità di bordi/testo bassa... si stima a costo trascurabile
    con un filtro di Sobel'. Implementato con numpy puro (convoluzione
    2D manuale): il progetto non ha scipy come dipendenza e il kernel 3x3
    di Sobel su un'immagine ridotta a 200px di lato è comunque a costo
    trascurabile, coerente con la specifica."""
    scala_grigi = immagine.convert("L").resize((200, 200))
    pixel = np.asarray(scala_grigi, dtype=np.float64)

    kernel_x = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]])
    kernel_y = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]])

    gradiente_x = _convoluzione_2d(pixel, kernel_x)
    gradiente_y = _convoluzione_2d(pixel, kernel_y)
    magnitudine = np.sqrt(gradiente_x**2 + gradiente_y**2)

    # Una locandina con testo ha molti bordi netti (contrasto lettere/sfondo);
    # una foto di paesaggio ha gradienti diffusi ma pochi bordi molto forti.
    soglia_bordo_forte = 150
    frazione_bordi_forti = float(np.mean(magnitudine > soglia_bordo_forte))
    return frazione_bordi_forti < _SOGLIA_DENSITA_BORDI


def _convoluzione_2d(matrice: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Convoluzione 'valid' senza scipy: il kernel è sempre 3x3 in questo
    modulo, non serve generalizzare oltre."""
    altezza, larghezza = matrice.shape
    kh, kw = kernel.shape
    risultato = np.zeros((altezza - kh + 1, larghezza - kw + 1))
    for i in range(kh):
        for j in range(kw):
            risultato += kernel[i, j] * matrice[i : i + risultato.shape[0], j : j + risultato.shape[1]]
    return risultato


def scarta_immagine(
    percorso_o_bytes, phash_noti: list[str] | None = None
) -> tuple[bool, str, str | None]:
    """Ritorna (scarta, motivo, phash). Il phash è calcolato comunque
    quando l'immagine viene aperta con successo, così il chiamante può
    aggiungerlo alla cache/lista dei noti indipendentemente dall'esito.

    Se l'immagine non si apre affatto (file corrotto, formato non
    supportato), non si scarta per errore: si lascia procedere (stesso
    principio del pre-filtro testuale, alto richiamo) e si segnala il
    motivo per la diagnostica."""
    try:
        immagine = _apri_immagine(percorso_o_bytes)
    except Exception as exc:
        return False, f"immagine_illeggibile_non_scartata: {exc}", None

    if dimensioni_troppo_piccole(immagine):
        return True, "dimensioni_troppo_piccole", None

    if aspect_ratio_implausibile(immagine):
        return True, "aspect_ratio_implausibile", None

    phash = calcola_phash(immagine)

    if phash_noti and e_duplicato_noto(phash, phash_noti):
        return True, "duplicato_di_immagine_nota", phash

    if densita_bordi_bassa(immagine):
        return True, "densita_bordi_bassa", phash

    return False, "", phash


# --- Cache pHash (12.10: "la leva più efficace di tutte" — la stessa
# locandina compare su 5-10 canali diversi a questa scala). Usa la tabella
# image_cache già presente nello schema (mai scritta finora). Match a
# distanza di Hamming <= soglia, come per e_duplicato_noto: due copie della
# stessa locandina ricompresse/ridimensionate da piattaforme diverse
# raramente hanno lo stesso hash esatto.

def cerca_in_cache(conn, phash: str):
    """Ritorna (extraction_json, model_used) della prima voce di cache
    entro la soglia di Hamming, o None se nessun match. Un solo giro sulla
    tabella: a questa scala (poche migliaia di righe attese) non serve un
    indice specializzato per la ricerca fuzzy."""
    righe = conn.execute("SELECT phash, extraction_json, model_used FROM image_cache").fetchall()
    for riga in righe:
        if e_duplicato_noto(phash, [riga["phash"]]):
            return riga["extraction_json"], riga["model_used"]
    return None


def salva_in_cache(conn, phash: str, extraction_json: str, model_used: str, cost_tokens: int = 0) -> None:
    from datetime import datetime

    conn.execute(
        """
        INSERT INTO image_cache (phash, first_seen, extraction_json, model_used, cost_tokens)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(phash) DO NOTHING
        """,
        (phash, datetime.now().isoformat(), extraction_json, model_used, cost_tokens),
    )
    conn.commit()
