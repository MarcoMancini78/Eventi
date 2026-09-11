"""risolvi_comune: cascata di risoluzione livelli 1-2 (07.3)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import perimetro, store


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def test_risolvi_comune_case_insensitive_e_alias():
    conn = _conn_di_prova()
    conn.execute(
        """
        INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo)
        VALUES ('1', 'Calosso', 'Calosso', 'AT', 44.74, 8.23, 0.0, 0, 'A', 'si')
        """
    )
    conn.commit()

    assert perimetro.risolvi_comune("Calosso", conn)["comune"] == "Calosso"
    assert perimetro.risolvi_comune("CALOSSO", conn)["comune"] == "Calosso"
    assert perimetro.risolvi_comune("comune-inesistente", conn) is None

    conn.execute("UPDATE comuni SET alias = 'Calosso;Frazione Test' WHERE istat = '1'")
    assert perimetro.risolvi_comune("Frazione Test", conn)["comune"] == "Calosso"
