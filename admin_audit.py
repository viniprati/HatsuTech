from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

import discord

from database import admin_audit_logs_col

try:
    from config import ADMIN_AUDIT_DM_USER_IDS
except ImportError:
    ADMIN_AUDIT_DM_USER_IDS = (983870132063453235, 459064218088374293)


log = logging.getLogger(__name__)
AUDIT_DM_MAX_ATTEMPTS = 2
AUDIT_DM_MAX_RETRY_DELAY_SECONDS = 10


def _display_user(user: discord.abc.User | None, fallback_id: int | str | None = None) -> str:
    user_id = getattr(user, "id", fallback_id)
    mention = getattr(user, "mention", None)
    if mention and user_id is not None:
        return f"{mention} (`{user_id}`)"
    if user_id is not None:
        return f"ID `{user_id}`"
    return "Não identificado"


def _bounded_details(details: dict[str, object] | None) -> dict[str, str]:
    bounded = {}
    for name, value in (details or {}).items():
        if len(bounded) >= 8:
            break
        field_name = str(name or "Detalhe")[:256]
        field_value = str(value if value is not None else "-")[:1024]
        bounded[field_name] = field_value or "-"
    return bounded


async def _record_delivery(audit_id: str, recipient_id: int, payload: dict):
    result = await asyncio.to_thread(
        admin_audit_logs_col.update_one,
        {"_id": audit_id},
        {
            "$set": {
                f"deliveries.{recipient_id}": payload,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    if not getattr(result, "acknowledged", False):
        log.warning(
            "admin_audit_delivery_persist_failed audit_id=%s status=%s",
            audit_id,
            payload.get("status"),
        )


async def _send_admin_audit_dm(
    bot: discord.Client,
    *,
    category: str,
    action: str,
    guild: discord.Guild | None,
    actor: discord.abc.User | None,
    target: discord.abc.User | None = None,
    target_id: int | str | None = None,
    target_label: str | None = None,
    reason: str | None = None,
    details: dict[str, object] | None = None,
    source: str,
) -> dict[str, int | str]:
    """Persiste e envia uma auditoria administrativa por DM sem propagar falhas."""
    audit_id = str(uuid4())
    created_at = datetime.now(timezone.utc)
    safe_details = _bounded_details(details)
    actor_id = getattr(actor, "id", None)
    resolved_target_id = getattr(target, "id", target_id)
    recipients = tuple(dict.fromkeys(int(user_id) for user_id in ADMIN_AUDIT_DM_USER_IDS if user_id))

    event_doc = {
        "_id": audit_id,
        "type": "admin_audit_dm",
        "category": str(category),
        "action": str(action),
        "source": str(source),
        "guild_id": str(guild.id) if guild else None,
        "actor_id": str(actor_id) if actor_id is not None else None,
        "target_id": str(resolved_target_id) if resolved_target_id is not None else None,
        "target_label": target_label,
        "reason": str(reason)[:1024] if reason else None,
        "details": safe_details,
        "recipient_ids": [str(user_id) for user_id in recipients],
        "deliveries": {},
        "created_at": created_at,
        "updated_at": created_at,
    }
    try:
        result = await asyncio.to_thread(admin_audit_logs_col.insert_one, event_doc)
        if not getattr(result, "acknowledged", False):
            log.warning("admin_audit_event_persist_failed audit_id=%s action=%s", audit_id, action)
    except Exception:
        log.exception("admin_audit_event_persist_error audit_id=%s action=%s", audit_id, action)

    embed = discord.Embed(
        title=f"Auditoria Administrativa • {category.title()}",
        description="Uma ação administrativa foi concluída e registrada.",
        color=discord.Color.orange(),
        timestamp=created_at,
    )
    embed.add_field(name="Ação", value=str(action)[:1024], inline=False)
    embed.add_field(name="Responsável", value=_display_user(actor, actor_id), inline=False)
    target_value = target_label or _display_user(target, resolved_target_id)
    embed.add_field(name="Usuário afetado", value=str(target_value)[:1024], inline=False)
    if reason:
        embed.add_field(name="Motivo", value=str(reason)[:1024], inline=False)
    for name, value in safe_details.items():
        embed.add_field(name=name, value=value, inline=False)
    guild_label = f"{guild.name} • {guild.id}" if guild else "Servidor não identificado"
    embed.set_footer(text=f"{guild_label} • Auditoria {audit_id[:8]}")

    started_at = time.monotonic()
    summary = {"audit_id": audit_id, "sent": 0, "blocked": 0, "failed": 0}
    log.info(
        "admin_audit_dm_started audit_id=%s category=%s action=%s recipients=%s",
        audit_id,
        category,
        action,
        len(recipients),
    )

    for recipient_id in recipients:
        attempts = 0
        status = "failed"
        error_text = None
        while attempts < AUDIT_DM_MAX_ATTEMPTS:
            attempts += 1
            try:
                recipient = bot.get_user(recipient_id) or await bot.fetch_user(recipient_id)
                await recipient.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                status = "sent"
                break
            except discord.Forbidden as exc:
                status = "blocked"
                error_text = str(exc)
                break
            except discord.NotFound as exc:
                status = "not_found"
                error_text = str(exc)
                break
            except discord.HTTPException as exc:
                error_text = str(exc)
                if attempts >= AUDIT_DM_MAX_ATTEMPTS:
                    break
                retry_after = float(getattr(exc, "retry_after", 0) or 1)
                delay = min(max(retry_after, 1), AUDIT_DM_MAX_RETRY_DELAY_SECONDS)
                log.warning(
                    "admin_audit_dm_retry audit_id=%s action=%s attempt=%s status=%s delay_seconds=%.2f",
                    audit_id,
                    action,
                    attempts,
                    getattr(exc, "status", None),
                    delay,
                )
                await asyncio.sleep(delay)
            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"
                break

        if status == "sent":
            summary["sent"] += 1
        elif status == "blocked":
            summary["blocked"] += 1
        else:
            summary["failed"] += 1

        try:
            await _record_delivery(
                audit_id,
                recipient_id,
                {
                    "status": status,
                    "attempts": attempts,
                    "error": error_text[:300] if error_text else None,
                    "completed_at": datetime.now(timezone.utc),
                },
            )
        except Exception:
            log.exception("admin_audit_delivery_persist_error audit_id=%s status=%s", audit_id, status)

    log.info(
        "admin_audit_dm_finished audit_id=%s category=%s action=%s sent=%s blocked=%s failed=%s duration_seconds=%.3f",
        audit_id,
        category,
        action,
        summary["sent"],
        summary["blocked"],
        summary["failed"],
        time.monotonic() - started_at,
    )
    return summary


async def send_admin_audit_dm(
    bot: discord.Client,
    *,
    category: str,
    action: str,
    guild: discord.Guild | None,
    actor: discord.abc.User | None,
    target: discord.abc.User | None = None,
    target_id: int | str | None = None,
    target_label: str | None = None,
    reason: str | None = None,
    details: dict[str, object] | None = None,
    source: str,
) -> dict[str, int | str]:
    """Envia auditoria sem permitir que uma falha de DM afete a ação original."""
    try:
        return await _send_admin_audit_dm(
            bot,
            category=category,
            action=action,
            guild=guild,
            actor=actor,
            target=target,
            target_id=target_id,
            target_label=target_label,
            reason=reason,
            details=details,
            source=source,
        )
    except Exception:
        log.exception("admin_audit_dm_unexpected_failure category=%s action=%s", category, action)
        return {"audit_id": "unavailable", "sent": 0, "blocked": 0, "failed": len(ADMIN_AUDIT_DM_USER_IDS)}
