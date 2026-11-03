"""Audit recorded VIP owner activity without starting the bot or changing data.

A dedicated MongoClient is intentional: importing database.py would connect and
initialize indexes. This script only pings and reads vip_roles, and fails rather
than treating a database outage as an empty result. It can also read the JSON
produced by scripts/backup_vip_roles.py without any external connection.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "scripts" / "output" / "vip_activity"
DB_NAME = "DiscordBotDB"
# Version of the activity history schema written by the VIP cog.
ACTIVITY_POLICY = "observed_activity_10_days_v1"
BRT = timezone(timedelta(hours=-3))
COLUMNS = ("usuario_id", "cargo_id", "tipo", "ultima_atividade_brt", "dias_sem_registro", "situacao", "historico")
SNAPSHOT_FIELDS = (
    "_id", "guild_id", "user_id", "role_id", "highlight_id",
    "last_activity_at", "inactivity_observed_at", "inactivity_policy",
    "highlight_last_activity_at", "highlight_inactivity_observed_at", "highlight_inactivity_policy",
)


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Informe um número inteiro maior que zero.")
    return number


def parse_datetime(value) -> datetime | None:
    if isinstance(value, dict):
        value = value.get("$date")
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def document_scope(doc: dict, guild_id: str) -> str:
    explicit = doc.get("guild_id")
    if explicit is not None:
        return "servidor" if str(explicit) == guild_id else "outro_servidor"
    document_id = str(doc.get("_id", ""))
    if ":" in document_id:
        return "servidor" if document_id.split(":", 1)[0] == guild_id else "outro_servidor"
    return "legado_sem_servidor"


def build_report(documents: list[dict], guild_id: str, days: int, now: datetime, include_legacy: bool = False):
    rows = []
    skipped_legacy = 0
    cutoff = now - timedelta(days=days)
    for doc in documents:
        scope = document_scope(doc, guild_id)
        if scope == "outro_servidor":
            continue
        if scope == "legado_sem_servidor" and not include_legacy:
            skipped_legacy += 1
            continue
        user_id = str(doc.get("user_id") or str(doc.get("_id", "")).rsplit(":", 1)[-1])
        for role_field, prefix, kind in (("role_id", "", "personalizado"), ("highlight_id", "highlight_", "destaque")):
            role_id = doc.get(role_field)
            if role_id in (None, ""):
                continue
            activity = parse_datetime(doc.get(f"{prefix}last_activity_at"))
            observed = parse_datetime(doc.get(f"{prefix}inactivity_observed_at"))
            policy = doc.get(f"{prefix}inactivity_policy")
            if scope != "servidor":
                history = "servidor_nao_confirmado"
            elif activity is None:
                history = "sem_data_de_atividade"
            elif activity > now or (observed is not None and observed > now):
                history = "data_no_futuro"
            elif policy != ACTIVITY_POLICY:
                history = "regra_antiga_ou_desconhecida"
            elif observed is None or observed < activity:
                history = "observacao_insuficiente"
            elif now - observed > timedelta(minutes=30):
                history = "monitoramento_interrompido"
            else:
                history = "regra_atual"

            if activity is None or activity > now or scope != "servidor":
                situation = "HISTORICO_INSUFICIENTE"
            elif activity > cutoff:
                situation = "ATIVIDADE_RECENTE"
            elif history == "regra_atual":
                situation = "SEM_ATIVIDADE_REGISTRADA"
            else:
                situation = "POSSIVEL_INATIVO"
            rows.append({
                "usuario_id": user_id or "desconhecido",
                "cargo_id": str(role_id),
                "tipo": kind,
                "ultima_atividade_brt": activity.astimezone(BRT).strftime("%Y-%m-%d %H:%M:%S") if activity else "-",
                "dias_sem_registro": f"{(now - activity).total_seconds() / 86400:.2f}" if activity and activity <= now else "-",
                "situacao": situation,
                "historico": history,
            })
    rows.sort(key=lambda row: (row["situacao"], row["usuario_id"], row["tipo"]))
    return rows, skipped_legacy


def read_mongodb() -> list[dict]:
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri:
        raise ValueError("Configure MONGO_URI no .env da raiz do projeto ou use --input com um backup JSON.")
    with MongoClient(
        uri, tlsCAFile=certifi.where(), tz_aware=True,
        connectTimeoutMS=8000, serverSelectionTimeoutMS=8000, socketTimeoutMS=15000,
        retryReads=True, retryWrites=False,
    ) as client:
        client.admin.command("ping")
        projection = {key: 1 for key in SNAPSHOT_FIELDS}
        return list(client[DB_NAME]["vip_roles"].find({}, projection).max_time_ms(15000))


def read_backup(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    documents = payload.get("documents") if isinstance(payload, dict) else payload
    if not isinstance(documents, list) or any(not isinstance(doc, dict) for doc in documents):
        raise ValueError("JSON inválido: informe uma lista de documentos ou um backup com a chave documents.")
    return documents


def write_json_report(documents, rows, skipped, guild_id, days, now, include_legacy, input_path):
    snapshots = []
    for doc in documents:
        scope = document_scope(doc, guild_id)
        if scope == "outro_servidor" or (scope == "legado_sem_servidor" and not include_legacy):
            continue
        if doc.get("role_id") in (None, "") and doc.get("highlight_id") in (None, ""):
            continue
        snapshots.append({key: doc[key] for key in SNAPSHOT_FIELDS if key in doc})
    payload = {
        "schema_version": 1,
        "exported_at": now.isoformat(),
        "guild_id": guild_id,
        "threshold_days": days,
        "read_only": True,
        "source": "json_backup" if input_path else "mongodb",
        "summary": {
            "roles": len(rows),
            "owners": len({row["usuario_id"] for row in rows}),
            "by_status": dict(Counter(row["situacao"] for row in rows)),
            "skipped_unscoped_legacy": skipped,
        },
        "limitations": [
            "Baseado em registros do bot; não reconstrói atividade anterior.",
            "Histórico insuficiente não comprova inatividade.",
            "Não confirma a existência atual dos cargos no Discord.",
        ],
        "rows": rows,
        "documents": snapshots,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORT_DIR / f"vip_activity_{now:%Y%m%d_%H%M%S_%f}_UTC.json"

    def encode(value):
        return value.isoformat() if isinstance(value, datetime) else str(value)

    with output_path.open("x", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2, default=encode)
        output.write("\n")
    return output_path


def print_report(rows: list[dict], skipped_legacy: int, guild_id: str, days: int, now: datetime):
    print(f"Auditoria de atividade VIP | servidor {guild_id} | prazo {days} dias")
    print(f"Referência: {now.astimezone(BRT):%Y-%m-%d %H:%M:%S} (Brasília)")
    print("Somente leitura. Cargos e banco de dados não serão alterados.")
    print("Relatório baseado em registros do bot; não reconstrói atividade passada nem confirma a existência atual dos cargos.")
    print("POSSIVEL_INATIVO exige revisão: histórico antigo/incompleto não prova ausência de atividade.")
    if not rows:
        print("\nNenhum vínculo de cargo encontrado para este filtro.")
    for status, count in sorted(Counter(row["situacao"] for row in rows).items()):
        print(f"{status}: {count} cargo(s)")
    if skipped_legacy:
        print(f"Legados sem servidor confirmado, omitidos: {skipped_legacy}. Use --include-legacy para consultar.")
    print()
    writer = csv.DictWriter(sys.stdout, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=positive_int, default=10, help="Prazo em dias (padrão: 10).")
    parser.add_argument("--guild-id", default=os.getenv("MAIN_GUILD_ID", "609159041499004982"), help="ID do servidor.")
    parser.add_argument("--input", type=Path, help="Ler um backup JSON em vez de conectar ao MongoDB.")
    parser.add_argument("--csv", type=Path, help="Salvar também um relatório CSV local.")
    parser.add_argument("--include-legacy", action="store_true", help="Incluir vínculos antigos sem servidor confirmado.")
    args = parser.parse_args(argv)
    if not str(args.guild_id).isdigit() or int(args.guild_id) <= 0:
        parser.error("--guild-id deve ser um ID numérico positivo.")
    if args.input and args.csv and args.input.resolve() == args.csv.resolve():
        parser.error("O CSV deve usar um caminho diferente do backup de entrada.")
    try:
        documents = read_backup(args.input) if args.input else read_mongodb()
        now = datetime.now(timezone.utc)
        rows, skipped = build_report(documents, str(args.guild_id), args.days, now, args.include_legacy)
        json_path = write_json_report(
            documents, rows, skipped, str(args.guild_id), args.days, now, args.include_legacy, args.input
        )
        print_report(rows, skipped, str(args.guild_id), args.days, now)
        print(f"\nJSON local salvo em: {json_path}")
        if args.csv:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            with args.csv.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            print(f"\nCSV salvo em: {args.csv}")
        return 0
    except (PyMongoError, OSError) as exc:
        # Do not print connection errors containing credentials or private hosts.
        print(f"ERRO: consulta ou arquivo indisponível ({type(exc).__name__}). Confira a conexão e os caminhos informados.", file=sys.stderr)
        return 1
    except ValueError as exc:
        # MongoClient may reject a URI with a ValueError. Only surface our own messages.
        message = str(exc) if args.input or not os.getenv("MONGO_URI", "").strip() else "Configuração inválida do MongoDB. Confira MONGO_URI."
        print(f"ERRO: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
