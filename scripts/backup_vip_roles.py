
"""Export DiscordBotDB.vip_roles to a local JSON backup.

Read-only script: it only reads the vip_roles collection and writes a local
backup file under backups/vip_roles.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import db


BACKUP_DIR = Path("backups/vip_roles")


def json_safe(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def main() -> int:
    if db is None:
        print("ERRO: MongoDB indisponivel pelo database.py.")
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_path = BACKUP_DIR / f"vip_roles_antes_relink_{timestamp}.json"

    docs = list(db["vip_roles"].find({}).sort("_id", 1))
    payload = {
        "database": "DiscordBotDB",
        "collection": "vip_roles",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(docs),
        "documents": [json_safe(doc) for doc in docs],
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Backup criado: {output_path}")
    print(f"Documentos exportados: {len(docs)}")
    print("Operacao somente leitura no MongoDB; nenhum documento foi alterado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
