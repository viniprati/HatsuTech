
"""Read-only status check for manual VIP relink work."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import db


MAX_PENDING = 20


def mask(value: Any, keep_tail: int = 4) -> str:
    text = str(value)
    if len(text) <= keep_tail:
        return text
    return "*" * (len(text) - keep_tail) + text[-keep_tail:]


def has_value(doc: dict[str, Any], key: str) -> bool:
    return key in doc and doc.get(key) not in (None, "")


def main() -> int:
    if db is None:
        print("ERRO: MongoDB indisponivel pelo database.py.")
        return 1

    docs = list(db["vip_roles"].find({}).sort("_id", 1))
    total = len(docs)
    active = 0
    needs_review = 0
    missing_member = 0
    missing_role = 0
    without_role_id = 0
    with_highlight_id = 0
    pending: list[dict[str, Any]] = []

    for doc in docs:
        status = doc.get("status")
        review_required = bool(doc.get("review_required"))
        is_needs_review = status == "needs_review" or review_required

        if status == "active" or (has_value(doc, "role_id") and not is_needs_review):
            active += 1
        if is_needs_review:
            needs_review += 1
            pending.append(doc)
        if doc.get("missing_member"):
            missing_member += 1
        if doc.get("missing_role"):
            missing_role += 1
        if not has_value(doc, "role_id"):
            without_role_id += 1
        if has_value(doc, "highlight_id"):
            with_highlight_id += 1

    print("Coffee Security VIP Relink Status (READ ONLY)")
    print(f"total_vip_roles: {total}")
    print(f"active: {active}")
    print(f"needs_review: {needs_review}")
    print(f"missing_member: {missing_member}")
    print(f"missing_role: {missing_role}")
    print(f"without_role_id: {without_role_id}")
    print(f"with_highlight_id: {with_highlight_id}")

    if pending:
        print("\nPendentes para revisao:")
        for doc in pending[:MAX_PENDING]:
            reasons = []
            if doc.get("missing_member"):
                reasons.append("missing_member")
            if doc.get("missing_role"):
                reasons.append("missing_role")
            if doc.get("cleanup_reason"):
                reasons.append(f"reason={doc.get('cleanup_reason')}")
            reason_text = ", ".join(reasons) if reasons else "review_required"
            print(
                f"- user={mask(doc.get('_id'))} "
                f"role_id={doc.get('role_id') or '-'} "
                f"highlight_id={doc.get('highlight_id') or '-'} "
                f"status={doc.get('status') or '-'} "
                f"{reason_text}"
            )
        if len(pending) > MAX_PENDING:
            print(f"... +{len(pending) - MAX_PENDING} pendentes")
    else:
        print("\nPendentes para revisao: 0")

    print("\nOperacao somente leitura; nenhum documento foi alterado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
