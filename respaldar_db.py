import sqlite3
from datetime import datetime
from pathlib import Path

db_path = Path("portal_escolar.db")
if not db_path.exists():
    # Busca cualquier archivo .db en la carpeta del proyecto si tiene otro nombre
    candidatos = list(Path(".").glob("*.db"))
    if not candidatos:
        print("No se encontró ningún archivo .db en la carpeta actual.")
        raise SystemExit(1)
    db_path = candidatos[0]

carpeta_respaldo = Path("respaldos")
carpeta_respaldo.mkdir(exist_ok=True)

marca_tiempo = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
destino = carpeta_respaldo / f"{db_path.stem}_{marca_tiempo}.db"

origen_conn = sqlite3.connect(str(db_path))
destino_conn = sqlite3.connect(str(destino))
with destino_conn:
    origen_conn.backup(destino_conn)

destino_conn.close()
origen_conn.close()
print(f"Respaldo creado correctamente en: {destino}")
