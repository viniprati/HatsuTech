
"""Read-only checker for Coffee Security economy/test-guild mapping."""

from __future__ import annotations

import os
import sys
from typing import Any

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError


DB_NAME = "DiscordBotDB"
MAIN_GUILD_ID_DEFAULT = "609159041499004982"
TEST_GUILD_ID_DEFAULT = "1442105700246491189"
MAX_EXAMPLES = 5


def _mask(value: Any, keep_tail: int = 4) -> str:
    text = str(value)
    if len(text) <= keep_tail:
        return text
    return "*" * (len(text) - keep_tail) + text[-keep_tail:]


def _short_doc(doc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["_id"] = str(doc.get("_id"))
    if "guild_id" in doc:
        out["guild_id"] = str(doc.get("guild_id"))
    if "user_id" in doc:
        out["user_id"] = _mask(doc.get("user_id"))
    if "type" in doc:
        out["type"] = str(doc.get("type"))
    if "status" in doc:
        out["status"] = str(doc.get("status"))
    if "box_id" in doc:
        out["box_id"] = str(doc.get("box_id"))
    if "sku" in doc:
        out["sku"] = str(doc.get("sku"))
    if "role_id" in doc:
        out["role_id"] = str(doc.get("role_id"))
    return out


def _print_section(title: str):
    print(f"\n=== {title} ===")


def main() -> int:
    load_dotenv()

    mongo_uri = os.getenv("MONGO_URI", "").strip()
    main_guild_id = os.getenv("MAIN_GUILD_ID", MAIN_GUILD_ID_DEFAULT).strip()
    test_guild_id = os.getenv("TEST_GUILD_ID", TEST_GUILD_ID_DEFAULT).strip()

    if not mongo_uri:
        print("ERRO: MONGO_URI não encontrado no ambiente.")
        return 1

    print("Coffee Security Mongo Read-Only Check")
    print(f"DB: {DB_NAME}")
    print(f"MAIN_GUILD_ID: {main_guild_id}")
    print(f"TEST_GUILD_ID: {test_guild_id}")

    client: MongoClient | None = None
    try:
        client = MongoClient(
            mongo_uri,
            tlsCAFile=certifi.where(),
            connectTimeoutMS=15000,
            socketTimeoutMS=30000,
            serverSelectionTimeoutMS=8000,
            retryReads=True,
            retryWrites=False,
        )
        client.admin.command("ping")
        db = client.get_database(DB_NAME)
    except Exception as exc:
        print(f"ERRO: falha ao conectar no MongoDB: {exc}")
        return 1

    economy_collections = ["eco_users", "eco_limits", "eco_logs", "eco_admin_logs"]
    alerts: list[str] = []

    try:
        _print_section("Economia Compartilhada")
        total_main = 0
        total_test = 0
        for col_name in economy_collections:
            col = db[col_name]
            count_main = col.count_documents({"guild_id": main_guild_id})
            count_test = col.count_documents({"guild_id": test_guild_id})
            total_main += count_main
            total_test += count_test

            print(f"{col_name}: main={count_main} | test={count_test}")

            if count_test > 0:
                alerts.append(
                    f"{col_name}: encontrou {count_test} docs com guild_id do teste "
                    f"({test_guild_id}). Economia deveria mapear teste -> principal."
                )
                examples = list(col.find({"guild_id": test_guild_id}).limit(MAX_EXAMPLES))
                for idx, doc in enumerate(examples, start=1):
                    print(f"  exemplo test {idx}: {_short_doc(doc)}")

            if count_main > 0:
                examples = list(col.find({"guild_id": main_guild_id}).limit(MAX_EXAMPLES))
                for idx, doc in enumerate(examples, start=1):
                    print(f"  exemplo main {idx}: {_short_doc(doc)}")

        print(f"TOTAL economia em guild principal: {total_main}")
        print(f"TOTAL economia em guild teste: {total_test}")

        _print_section("Temproles (Guild Real)")
        temp_col = db["temproles"]
        temp_main = temp_col.count_documents({"guild_id": main_guild_id})
        temp_test = temp_col.count_documents({"guild_id": test_guild_id})
        print(f"temproles: main={temp_main} | test={temp_test}")

        main_examples = list(temp_col.find({"guild_id": main_guild_id}).limit(MAX_EXAMPLES))
        test_examples = list(temp_col.find({"guild_id": test_guild_id}).limit(MAX_EXAMPLES))

        for idx, doc in enumerate(main_examples, start=1):
            print(f"  exemplo temprole main {idx}: {_short_doc(doc)}")
        for idx, doc in enumerate(test_examples, start=1):
            print(f"  exemplo temprole test {idx}: {_short_doc(doc)}")

        if temp_test == 0 and temp_main > 0:
            alerts.append(
                "temproles: nenhum registro no guild_id de teste. "
                "Se você aplicou VIP no teste recentemente, isso pode indicar gravação incorreta no guild principal."
            )

        _print_section("Alertas")
        if not alerts:
            print("Nenhum alerta detectado.")
        else:
            for idx, alert in enumerate(alerts, start=1):
                print(f"{idx}. {alert}")

        _print_section("Resumo de Conformidade")
        economy_ok = total_test == 0
        print(f"Economia mapeada para guild principal: {'OK' if economy_ok else 'FALHA'}")
        print("Temproles por guild real: validar pelos exemplos e pelos testes de aplicação recente.")

    except PyMongoError as exc:
        print(f"ERRO Mongo durante leitura: {exc}")
        return 1
    finally:
        if client is not None:
            client.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
