import json
import sqlite3
import sys

source_id = sys.argv[1] if len(sys.argv) > 1 else "comune-asti"

conn = sqlite3.connect("data/eventi.db")
conn.row_factory = sqlite3.Row

print(f"=== FONTE: {source_id} ===\n")

src = conn.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
if src:
    print("URL configurato:", src["endpoint"])
    print("Metodo/tier:", src["tier"])
else:
    print("Fonte non trovata in sources!")

print()

artifacts = conn.execute(
    "SELECT artifact_id, url, kind, fetched_at, LENGTH(text) as len_testo FROM artifacts WHERE source_id=?",
    (source_id,),
).fetchall()
print(f"Artefatti scaricati: {len(artifacts)}")
for a in artifacts:
    print(f"  - artifact_id={a['artifact_id']} url={a['url']} kind={a['kind']} lunghezza_testo={a['len_testo']} scaricato={a['fetched_at']}")

print()

for a in artifacts:
    testo = conn.execute("SELECT text FROM artifacts WHERE artifact_id=?", (a["artifact_id"],)).fetchone()["text"]
    print(f"--- Testo estratto dalla pagina (artifact {a['artifact_id']}), primi 500 caratteri ---")
    print((testo or "")[:500])
    print("...\n")

    estrazioni = conn.execute(
        "SELECT extraction_id, model, confidence, created_at, parsed_json FROM extractions WHERE artifact_id=?",
        (a["artifact_id"],),
    ).fetchall()
    print(f"Chiamate LLM per questo artefatto: {len(estrazioni)}")
    for e in estrazioni:
        print(f"  - modello={e['model']} confidenza={e['confidence']} quando={e['created_at']}")
        parsed = json.loads(e["parsed_json"]) if e["parsed_json"] else {}
        print("    non_e_un_evento:", parsed.get("non_e_un_evento"))
        print("    motivo:", parsed.get("motivo"))
        print("    numero eventi estratti:", len(parsed.get("eventi", [])))
        for ev in parsed.get("eventi", []):
            print("      ->", ev.get("titolo"), "|", ev.get("data_inizio"), "|", ev.get("comune"))
    print()

print("=== EVENTI SALVATI IN 'events' per questa fonte ===")
eventi = conn.execute(
    """
    SELECT e.event_id, e.titolo, e.data_inizio, e.comune, e.luogo, e.url, e.confidenza, e.stato
    FROM events e JOIN event_sources es ON e.event_id = es.event_id
    WHERE es.source_id = ?
    """,
    (source_id,),
).fetchall()
print(f"Eventi collegati a questa fonte: {len(eventi)}")
for ev in eventi:
    print(dict(ev))
