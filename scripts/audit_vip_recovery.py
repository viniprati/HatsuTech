
"""Read-only VIP recovery audit for Coffee Security MongoDB.

This script only uses read operations: list collections, count documents, and
find. It does not update, insert, delete, replace, or migrate anything.
"""

from __future__ import annotations

import os
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError


DB_NAMES = ("DiscordBotDB", "coffee_security")
COLLECTIONS = ("vip_roles", "temproles", "eco_logs", "eco_limits", "eco_shop")
VIP_SKUS = ("vip_berserk_30d", "vip_mugetsu_30d", "vip_monarch_30d")
MAIN_GUILD_ID_DEFAULT = "609159041499004982"
TEST_GUILD_ID_DEFAULT = "1442105700246491189"
MAX_EXAMPLES = 5
OUTPUT_DIR = Path("scripts/output")
PLAN_PATH = OUTPUT_DIR / "vip_recovery_plan.json"
REPORT_PATH = OUTPUT_DIR / "vip_recovery_report.md"


@dataclass
class VipRolesAudit:
    total: int = 0
    docs_by_user: dict[str, dict[str, Any]] = field(default_factory=dict)
    current_users: set[str] = field(default_factory=set)
    legacy_users: set[str] = field(default_factory=set)
    mixed_users: set[str] = field(default_factory=set)
    role_id_users: set[str] = field(default_factory=set)
    highlight_id_users: set[str] = field(default_factory=set)
    examples_current: list[dict[str, Any]] = field(default_factory=list)
    examples_legacy: list[dict[str, Any]] = field(default_factory=list)
    examples_mixed: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TempRolesAudit:
    total: int = 0
    active_total: int = 0
    main_total: int = 0
    test_total: int = 0
    active_users: set[str] = field(default_factory=set)
    users: set[str] = field(default_factory=set)
    examples_active: list[dict[str, Any]] = field(default_factory=list)
    examples_main: list[dict[str, Any]] = field(default_factory=list)
    examples_test: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EcoLogsAudit:
    total: int = 0
    vip_purchase_total: int = 0
    vip_reward_total: int = 0
    vip_related_users: set[str] = field(default_factory=set)
    vip_purchase_examples: list[dict[str, Any]] = field(default_factory=list)
    vip_reward_examples: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DatabaseAudit:
    name: str
    collection_counts: dict[str, int] = field(default_factory=dict)
    vip_roles: VipRolesAudit = field(default_factory=VipRolesAudit)
    temproles: TempRolesAudit = field(default_factory=TempRolesAudit)
    eco_logs: EcoLogsAudit = field(default_factory=EcoLogsAudit)


@dataclass
class RoleCheck:
    checked: bool = False
    existing_role_ids: set[str] = field(default_factory=set)
    unknown_role_ids: set[str] = field(default_factory=set)
    error: str = ""


def _mask(value: Any, keep_tail: int = 4) -> str:
    text = str(value)
    if len(text) <= keep_tail:
        return text
    return "*" * (len(text) - keep_tail) + text[-keep_tail:]


def _id(value: Any) -> str:
    return str(value) if value is not None else ""


def _role_id(value: Any) -> str:
    return str(value) if value not in (None, "") else ""


def _has_any(doc: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(key in doc and doc.get(key) not in (None, "") for key in keys)


def _limit_append(target: list[dict[str, Any]], doc: dict[str, Any]) -> None:
    if len(target) < MAX_EXAMPLES:
        target.append(_short_doc(doc))


def _format_ts(value: Any) -> str:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return str(value)
    try:
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return str(value)


def _short_doc(doc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"_id": _mask(doc.get("_id"))}
    for key in (
        "user_id",
        "guild_id",
        "role_id",
        "highlight_id",
        "friend",
        "owner",
        "type",
        "sku",
        "box_id",
        "status",
        "price_essencia",
    ):
        if key in doc:
            value = doc.get(key)
            out[key] = _mask(value) if key in {"user_id", "owner"} else str(value)
    if "end_time" in doc:
        out["end_time"] = str(doc.get("end_time"))
        out["end_time_utc"] = _format_ts(doc.get("end_time"))
    if "payload" in doc and isinstance(doc["payload"], dict):
        payload = doc["payload"]
        out["payload_keys"] = sorted(str(k) for k in payload.keys())
        for key in ("user_id", "guild_id", "role_id", "sku", "box_id", "reward", "rewards"):
            if key in payload:
                value = payload.get(key)
                out[f"payload.{key}"] = _mask(value) if key == "user_id" else str(value)
    if "vip_rewards" in doc:
        out["vip_rewards"] = str(doc.get("vip_rewards"))
    return out


def _print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def _print_list(title: str, values: set[str], limit: int = 25) -> None:
    print(f"{title}: {len(values)}")
    for value in sorted(values)[:limit]:
        print(f"  - {_mask(value)}")
    if len(values) > limit:
        print(f"  ... +{len(values) - limit} usuarios")


def _print_examples(title: str, docs: list[dict[str, Any]]) -> None:
    if not docs:
        return
    print(title)
    for idx, doc in enumerate(docs, start=1):
        print(f"  {idx}. {doc}")


def _count_or_zero(col: Collection, query: dict[str, Any] | None = None) -> int:
    return int(col.count_documents(query or {}))


def _collection_exists(db, name: str) -> bool:
    return name in db.list_collection_names()


def audit_vip_roles(col: Collection) -> VipRolesAudit:
    audit = VipRolesAudit(total=_count_or_zero(col))
    projection = {"_id": 1, "role_id": 1, "highlight_id": 1, "friend": 1, "owner": 1}

    for doc in col.find({}, projection):
        uid = _id(doc.get("_id"))
        audit.docs_by_user[uid] = {
            "_id": uid,
            "role_id": _role_id(doc.get("role_id")),
            "highlight_id": _role_id(doc.get("highlight_id")),
            "friend": _role_id(doc.get("friend")),
            "owner": _role_id(doc.get("owner")),
        }
        has_current = _has_any(doc, ("role_id", "highlight_id"))
        has_legacy = _has_any(doc, ("friend", "owner"))

        if "role_id" in doc and doc.get("role_id") not in (None, ""):
            audit.role_id_users.add(uid)
        if "highlight_id" in doc and doc.get("highlight_id") not in (None, ""):
            audit.highlight_id_users.add(uid)
        if has_current:
            audit.current_users.add(uid)
            _limit_append(audit.examples_current, doc)
        if has_legacy:
            audit.legacy_users.add(uid)
            _limit_append(audit.examples_legacy, doc)
        if has_current and has_legacy:
            audit.mixed_users.add(uid)
            _limit_append(audit.examples_mixed, doc)

    return audit


def audit_temproles(col: Collection, main_guild_id: str, test_guild_id: str) -> TempRolesAudit:
    now = time.time()
    main_values = [main_guild_id, int(main_guild_id)]
    test_values = [test_guild_id, int(test_guild_id)]
    audit = TempRolesAudit(
        total=_count_or_zero(col),
        active_total=_count_or_zero(col, {"end_time": {"$gt": now}}),
        main_total=_count_or_zero(col, {"guild_id": {"$in": main_values}}),
        test_total=_count_or_zero(col, {"guild_id": {"$in": test_values}}),
    )
    projection = {"_id": 1, "user_id": 1, "guild_id": 1, "role_id": 1, "end_time": 1}

    for doc in col.find({}, projection):
        uid = _id(doc.get("user_id"))
        if uid:
            audit.users.add(uid)
        try:
            is_active = float(doc.get("end_time", 0)) > now
        except (TypeError, ValueError):
            is_active = False
        if is_active and uid:
            audit.active_users.add(uid)
            _limit_append(audit.examples_active, doc)

    for doc in col.find({"guild_id": {"$in": main_values}}, projection).limit(MAX_EXAMPLES):
        _limit_append(audit.examples_main, doc)
    for doc in col.find({"guild_id": {"$in": test_values}}, projection).limit(MAX_EXAMPLES):
        _limit_append(audit.examples_test, doc)

    return audit


def _contains_vip_reward(value: Any) -> bool:
    if isinstance(value, dict):
        if str(value.get("kind", "")).lower() == "vip_temp":
            return True
        return any(_contains_vip_reward(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_vip_reward(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "vip_temp" in lowered or any(sku in lowered for sku in VIP_SKUS)
    return False


def _extract_user_from_log(doc: dict[str, Any]) -> str:
    for key in ("user_id", "target_user_id"):
        if doc.get(key) is not None:
            return _id(doc.get(key))
    payload = doc.get("payload")
    if isinstance(payload, dict):
        for key in ("user_id", "target_user_id"):
            if payload.get(key) is not None:
                return _id(payload.get(key))
    return ""


def audit_eco_logs(col: Collection) -> EcoLogsAudit:
    audit = EcoLogsAudit(total=_count_or_zero(col))
    sku_query = {"sku": {"$in": list(VIP_SKUS)}}
    payload_sku_query = {"payload.sku": {"$in": list(VIP_SKUS)}}
    title_query = {"title": {"$regex": "vip", "$options": "i"}}
    type_query = {"type": {"$regex": "vip|shop_buy", "$options": "i"}}
    vip_query = {"$or": [sku_query, payload_sku_query, title_query, type_query]}

    projection = {
        "_id": 1,
        "type": 1,
        "title": 1,
        "user_id": 1,
        "guild_id": 1,
        "sku": 1,
        "role_id": 1,
        "end_time": 1,
        "box_id": 1,
        "vip_rewards": 1,
        "payload": 1,
        "created_at": 1,
    }

    for doc in col.find(vip_query, projection):
        uid = _extract_user_from_log(doc)
        if uid:
            audit.vip_related_users.add(uid)

        is_purchase = doc.get("sku") in VIP_SKUS or (
            isinstance(doc.get("payload"), dict) and doc["payload"].get("sku") in VIP_SKUS
        )
        is_reward = _contains_vip_reward(doc.get("vip_rewards")) or _contains_vip_reward(doc.get("payload"))

        if is_purchase:
            audit.vip_purchase_total += 1
            _limit_append(audit.vip_purchase_examples, doc)
        if is_reward:
            audit.vip_reward_total += 1
            _limit_append(audit.vip_reward_examples, doc)

    return audit


def audit_database(client: MongoClient, db_name: str, main_guild_id: str, test_guild_id: str) -> DatabaseAudit:
    db = client[db_name]
    audit = DatabaseAudit(name=db_name)
    existing = set(db.list_collection_names())

    for col_name in COLLECTIONS:
        if col_name not in existing:
            audit.collection_counts[col_name] = 0
            continue
        col = db[col_name]
        audit.collection_counts[col_name] = _count_or_zero(col)

    if _collection_exists(db, "vip_roles"):
        audit.vip_roles = audit_vip_roles(db["vip_roles"])
    if _collection_exists(db, "temproles"):
        audit.temproles = audit_temproles(db["temproles"], main_guild_id, test_guild_id)
    if _collection_exists(db, "eco_logs"):
        audit.eco_logs = audit_eco_logs(db["eco_logs"])

    return audit


def print_database_report(audit: DatabaseAudit) -> None:
    _print_section(f"Banco: {audit.name}")
    print("Collections principais:")
    for name in COLLECTIONS:
        print(f"  - {name}: {audit.collection_counts.get(name, 0)} registros")

    vip = audit.vip_roles
    print("\nvip_roles:")
    print(f"  total: {vip.total}")
    print(f"  usuarios com VIP atual (role_id/highlight_id): {len(vip.current_users)}")
    print(f"  usuarios com role_id: {len(vip.role_id_users)}")
    print(f"  usuarios com highlight_id: {len(vip.highlight_id_users)}")
    print(f"  usuarios com legado friend/owner: {len(vip.legacy_users)}")
    print(f"  usuarios mistos atual + legado: {len(vip.mixed_users)}")
    _print_examples("  exemplos atuais:", vip.examples_current)
    _print_examples("  exemplos legados:", vip.examples_legacy)
    _print_examples("  exemplos mistos:", vip.examples_mixed)

    temp = audit.temproles
    print("\ntemproles:")
    print(f"  total: {temp.total}")
    print(f"  ativos: {temp.active_total}")
    print(f"  guild principal: {temp.main_total}")
    print(f"  guild teste: {temp.test_total}")
    print(f"  usuarios com temprole ativo: {len(temp.active_users)}")
    _print_examples("  exemplos ativos:", temp.examples_active)
    _print_examples("  exemplos guild principal:", temp.examples_main)
    _print_examples("  exemplos guild teste:", temp.examples_test)

    logs = audit.eco_logs
    print("\neco_logs:")
    print(f"  total: {logs.total}")
    print(f"  compras/logs com SKUs VIP: {logs.vip_purchase_total}")
    print(f"  rewards/logs com VIP de lootbox: {logs.vip_reward_total}")
    print(f"  usuarios relacionados a VIP nos logs: {len(logs.vip_related_users)}")
    _print_examples("  exemplos compra VIP:", logs.vip_purchase_examples)
    _print_examples("  exemplos reward VIP:", logs.vip_reward_examples)


def print_conflicts(current: DatabaseAudit, legacy: DatabaseAudit) -> None:
    _print_section("Possiveis Conflitos")

    current_vip_users = current.vip_roles.current_users
    current_legacy_users = current.vip_roles.legacy_users
    current_temprole_users = current.temproles.active_users
    old_vip_users = legacy.vip_roles.current_users | legacy.vip_roles.legacy_users
    new_vip_any = current.vip_roles.current_users | current.vip_roles.legacy_users

    mixed_current = current.vip_roles.mixed_users
    temp_without_vip = current_temprole_users - new_vip_any
    old_not_new = old_vip_users - new_vip_any

    _print_list("usuario com role_id/highlight_id atual e friend/owner antigo no banco atual", mixed_current)
    _print_list("usuario com temprole ativo mas sem vip_roles no banco atual", temp_without_vip)
    _print_list("usuario com dados no banco antigo e nao no banco atual", old_not_new)

    legacy_only_current_shape = legacy.vip_roles.current_users - current_vip_users
    legacy_only_friend_owner = legacy.vip_roles.legacy_users - new_vip_any
    _print_list("usuario com formato atual no banco antigo e ausente no atual", legacy_only_current_shape)
    _print_list("usuario com legado friend/owner no banco antigo e ausente no atual", legacy_only_friend_owner)

    if current_legacy_users:
        _print_list("usuario com legado friend/owner ainda no banco atual", current_legacy_users)


def _legacy_role_ids(doc: dict[str, Any]) -> set[str]:
    return {rid for rid in (_role_id(doc.get("friend")), _role_id(doc.get("owner"))) if rid}


def _all_legacy_role_ids(*audits: DatabaseAudit) -> set[str]:
    role_ids: set[str] = set()
    for audit in audits:
        for doc in audit.vip_roles.docs_by_user.values():
            role_ids.update(_legacy_role_ids(doc))
    return role_ids


def fetch_discord_role_check(role_ids: set[str], guild_ids: tuple[str, ...], token: str) -> RoleCheck:
    if not role_ids:
        return RoleCheck(checked=True)
    if not token:
        return RoleCheck(checked=False, unknown_role_ids=set(role_ids), error="DISCORD_TOKEN ausente")

    found: set[str] = set()
    try:
        for guild_id in guild_ids:
            url = f"https://discord.com/api/v10/guilds/{guild_id}/roles"
            request = Request(url, headers={"Authorization": f"Bot {token}"})
            with urlopen(request, timeout=20) as response:
                roles = json.loads(response.read().decode("utf-8"))
            if isinstance(roles, list):
                found.update(str(role.get("id")) for role in roles if isinstance(role, dict) and role.get("id"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return RoleCheck(checked=False, unknown_role_ids=set(role_ids), error=str(exc))

    return RoleCheck(
        checked=True,
        existing_role_ids=role_ids & found,
        unknown_role_ids=role_ids - found,
    )


def build_recovery_plan(
    current: DatabaseAudit,
    legacy: DatabaseAudit,
    role_check: RoleCheck,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_any = current.vip_roles.current_users | current.vip_roles.legacy_users
    current_protected = current.vip_roles.current_users
    plan: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []

    sources = (
        ("coffee_security", legacy),
        ("DiscordBotDB", current),
    )
    seen: set[tuple[str, str]] = set()

    for source_db, audit in sources:
        for user_id in sorted(audit.vip_roles.legacy_users):
            doc = audit.vip_roles.docs_by_user.get(user_id, {})
            if not _legacy_role_ids(doc):
                continue

            key = (source_db, user_id)
            if key in seen:
                continue
            seen.add(key)

            current_exists = user_id in current_any
            protected_current = user_id in current_protected
            legacy_role_ids = sorted(_legacy_role_ids(doc))
            unknown_role_ids = [rid for rid in legacy_role_ids if rid in role_check.unknown_role_ids]

            if protected_current:
                action = "manual_review"
                reason = "current_role_id_or_highlight_id_exists_do_not_overwrite"
            elif source_db == "coffee_security" and not current_exists:
                action = "review_or_migrate"
                reason = "exists_in_old_db_missing_in_current"
            elif source_db == "DiscordBotDB" and not protected_current:
                action = "manual_review"
                reason = "legacy_format_exists_in_current_db_without_current_role"
            else:
                action = "manual_review"
                reason = "legacy_data_conflicts_with_current_db"

            if unknown_role_ids:
                action = "manual_review"
                reason = f"{reason}; legacy_role_missing_or_unchecked"

            item = {
                "user_id": user_id,
                "source_db": source_db,
                "source_format": "legacy_friend_owner",
                "legacy_friend": doc.get("friend") or None,
                "legacy_owner": doc.get("owner") or None,
                "current_exists": current_exists,
                "current_has_role_id": user_id in current.vip_roles.role_id_users,
                "current_has_highlight_id": user_id in current.vip_roles.highlight_id_users,
                "legacy_role_ids_checked_in_discord": role_check.checked,
                "legacy_role_ids_existing": [rid for rid in legacy_role_ids if rid in role_check.existing_role_ids],
                "legacy_role_ids_unknown": unknown_role_ids,
                "recommended_action": action,
                "reason": reason,
            }
            plan.append(item)
            if action == "manual_review":
                manual_review.append(item)

    plan.sort(key=lambda item: (item["recommended_action"], item["source_db"], item["user_id"]))
    manual_review.sort(key=lambda item: (item["source_db"], item["user_id"]))
    return plan, manual_review


def write_recovery_plan(plan: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _masked_users(items: list[dict[str, Any]]) -> list[str]:
    return [_mask(item["user_id"]) for item in items]


def write_markdown_report(
    audits: dict[str, DatabaseAudit],
    plan: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
    role_check: RoleCheck,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    current = audits["DiscordBotDB"]
    legacy = audits["coffee_security"]
    recoverable = [item for item in plan if item["recommended_action"] == "review_or_migrate"]
    conflicts = [item for item in plan if item["recommended_action"] == "manual_review"]
    unknown_roles = sorted(
        {
            role_id
            for item in plan
            for role_id in item.get("legacy_role_ids_unknown", [])
        }
    )

    lines = [
        "# VIP Recovery Dry-Run Report",
        "",
        "Auditoria somente leitura. Nenhum update, insert, delete, replace ou migração foi executado.",
        "",
        "## Totais",
        "",
        f"- DiscordBotDB.vip_roles: {current.vip_roles.total}",
        f"- coffee_security.vip_roles: {legacy.vip_roles.total}",
        f"- Candidatos a recuperação: {len(recoverable)}",
        f"- Conflitos/revisão manual: {len(conflicts)}",
        f"- Cargos desconhecidos ou não verificados: {len(unknown_roles)}",
        f"- Checagem de cargos no Discord: {'executada' if role_check.checked else 'não executada'}",
    ]
    if role_check.error:
        lines.append(f"- Motivo da checagem incompleta: `{role_check.error}`")

    lines.extend(
        [
            "",
            "## Collections",
            "",
            "| Banco | Collection | Registros |",
            "| --- | ---: | ---: |",
        ]
    )
    for audit in audits.values():
        for name in COLLECTIONS:
            lines.append(f"| {audit.name} | {name} | {audit.collection_counts.get(name, 0)} |")

    lines.extend(["", "## Usuários Recuperáveis", ""])
    if recoverable:
        for item in recoverable:
            roles = ", ".join(filter(None, [item.get("legacy_friend"), item.get("legacy_owner")]))
            lines.append(f"- `{_mask(item['user_id'])}` via `{item['source_db']}` roles `{roles}`")
    else:
        lines.append("- Nenhum candidato seguro encontrado no dry-run.")

    lines.extend(["", "## Revisão Manual", ""])
    if manual_review:
        for item in manual_review:
            roles = ", ".join(filter(None, [item.get("legacy_friend"), item.get("legacy_owner")]))
            lines.append(
                f"- `{_mask(item['user_id'])}` via `{item['source_db']}` roles `{roles}`: {item['reason']}"
            )
    else:
        lines.append("- Nenhum item exigindo revisão manual.")

    lines.extend(["", "## Cargos Desconhecidos", ""])
    if unknown_roles:
        for role_id in unknown_roles:
            lines.append(f"- `{role_id}`")
    else:
        lines.append("- Nenhum cargo legado ficou desconhecido na checagem disponível.")

    lines.extend(
        [
            "",
            "## Plano Seguro de Migração",
            "",
            "1. Fazer backup/export de `vip_roles`, `temproles`, `eco_logs`, `eco_limits` e `eco_shop` antes de qualquer escrita.",
            "2. Revisar manualmente `scripts/output/vip_recovery_plan.json`.",
            "3. Migrar somente usuários com `recommended_action = review_or_migrate` após validação humana.",
            "4. Nunca sobrescrever `role_id` ou `highlight_id` já existentes no banco atual.",
            "5. Não converter `temproles` em VIP permanente.",
            "6. Resolver manualmente cargos desconhecidos antes de qualquer migração real.",
            "7. Criar uma etapa futura separada para migração, com dry-run e confirmação explícita.",
        ]
    )

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_migration_plan() -> None:
    _print_section("Plano Seguro de Migracao Sugerido (nao executado)")
    print("1. Fazer backup/export das collections vip_roles, temproles, eco_logs, eco_limits e eco_shop.")
    print("2. Migrar apenas candidatos revisados manualmente em modo dry-run primeiro.")
    print("3. Nunca sobrescrever role_id/highlight_id atual; usar somente preenchimento quando o campo atual estiver ausente.")
    print("4. Separar VIP permanente de temprole: temproles devem continuar temporarios e nao virar vip_roles automaticamente.")
    print("5. Para friend/owner legado, mapear explicitamente qual campo vira role_id ou highlight_id antes de qualquer escrita.")
    print("6. Preservar vinculos manuais atuais e registrar origem em campos novos/log separado quando a migracao real for criada.")
    print("7. Validar conflitos usuario por usuario antes de qualquer update em producao.")


def main() -> int:
    load_dotenv()
    mongo_uri = os.getenv("MONGO_URI", "").strip()
    discord_token = os.getenv("DISCORD_TOKEN", "").strip()
    main_guild_id = os.getenv("MAIN_GUILD_ID", MAIN_GUILD_ID_DEFAULT).strip()
    test_guild_id = os.getenv("TEST_GUILD_ID", TEST_GUILD_ID_DEFAULT).strip()

    if not mongo_uri:
        print("ERRO: MONGO_URI nao encontrado no ambiente.")
        return 1

    print("Coffee Security VIP Recovery Audit (READ ONLY)")
    print(f"Bancos: {', '.join(DB_NAMES)}")
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

        audits = {
            db_name: audit_database(client, db_name, main_guild_id, test_guild_id)
            for db_name in DB_NAMES
        }
        role_ids = _all_legacy_role_ids(audits["DiscordBotDB"], audits["coffee_security"])
        role_check = fetch_discord_role_check(role_ids, (main_guild_id, test_guild_id), discord_token)
        plan, manual_review = build_recovery_plan(
            audits["DiscordBotDB"],
            audits["coffee_security"],
            role_check,
        )
        write_recovery_plan(plan)
        write_markdown_report(audits, plan, manual_review, role_check)

        for audit in audits.values():
            print_database_report(audit)

        print_conflicts(audits["DiscordBotDB"], audits["coffee_security"])
        _print_section("Arquivos Gerados")
        print(f"Plano JSON: {PLAN_PATH}")
        print(f"Relatorio Markdown: {REPORT_PATH}")
        print(f"Candidatos a recuperacao: {sum(1 for item in plan if item['recommended_action'] == 'review_or_migrate')}")
        print(f"Itens para revisao manual: {len(manual_review)}")
        if role_check.checked:
            print(f"Cargos legados existentes no Discord: {len(role_check.existing_role_ids)}")
            print(f"Cargos legados desconhecidos: {len(role_check.unknown_role_ids)}")
        else:
            print(f"Checagem de cargos no Discord nao executada: {role_check.error}")
        print_migration_plan()
        return 0
    except PyMongoError as exc:
        print(f"ERRO Mongo durante auditoria somente leitura: {exc}")
        return 1
    except Exception as exc:
        print(f"ERRO inesperado durante auditoria: {exc}")
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
