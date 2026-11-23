"""Notify personal VIP owners and administrators of capacity violations."""
import asyncio
import logging
from collections import defaultdict
from time import monotonic

import aiohttp
import discord
from discord.utils import escape_markdown

from admin_audit import send_admin_audit_dm
from cogs.economia.slot_upgrades import vip_extras
from database import get_db_failure_generation, is_db_online, vip_col

log = logging.getLogger(__name__)
OWNER_REMINDER_SECONDS = 5 * 60


def snowflake_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class VipCapacityAlerts:
    def __init__(self, cog, document_owner):
        self.cog = cog
        self.document_owner = document_owner
        self.reported: set[int] = set()
        self.owner_reminders: dict[int, tuple[int, float]] = {}

    def clear(self, role_id):
        self.reported.discard(role_id)
        self.owner_reminders.pop(role_id, None)

    async def remind_owner(self, owner, role, total, limit, complete_count):
        now = monotonic()
        previous = self.owner_reminders.get(role.id)
        if previous and previous[0] == owner.id and now < previous[1]:
            return
        reminder = (owner.id, now + OWNER_REMINDER_SECONDS)
        self.owner_reminders[role.id] = reminder
        minimum = "" if complete_count else "pelo menos "
        try:
            await owner.send(
                f"Seu cargo VIP **{escape_markdown(role.name)}** está acima do limite. "
                f"Há **{minimum}{total} membros** no cargo e o limite é **{limit}**, incluindo as vagas extras.\n\n"
                f"Em `/vip` → **Membros**, retire **{minimum}{total - limit}** para voltar ao limite, "
                "ou consulte `/vip_vagas` para aumentar a capacidade. "
                "Você receberá lembretes enquanto o cargo estiver acima do limite.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.NotFound):
            if self.owner_reminders.get(role.id) == reminder:
                self.owner_reminders[role.id] = (owner.id, float("inf"))
            log.info("vip_capacity_owner_dm_unavailable role_id=%s", role.id)
        except (discord.HTTPException, discord.RateLimited, aiohttp.ClientError, OSError, TimeoutError) as error:
            retry_after = getattr(error, "retry_after", 0) or 0
            if retry_after > OWNER_REMINDER_SECONDS and self.owner_reminders.get(role.id) == reminder:
                self.owner_reminders[role.id] = (owner.id, now + retry_after)
            log.warning("vip_capacity_owner_dm_failed role_id=%s error_type=%s", role.id, type(error).__name__)

    async def check(self, guild, role_ids=None):
        query = {
            "role_id": {"$exists": True} if role_ids is None else {"$in": [value for rid in role_ids for value in (rid, str(rid))]},
            "status": {"$ne": "inactive"}, "entitlement_active": {"$ne": False},
            "$or": [{"guild_id": {"$exists": False}}, {"guild_id": {"$in": [guild.id, str(guild.id)]}}],
        }
        generation = get_db_failure_generation()
        documents = await asyncio.to_thread(lambda: list(vip_col.find(query, {
            "guild_id": 1, "role_id": 1, "highlight_id": 1, "user_id": 1, "member_slot_upgrade": 1,
        })))
        if not is_db_online() or get_db_failure_generation() != generation:
            return

        bindings = defaultdict(dict)
        for document in documents:
            role_id = snowflake_or_none(document.get("role_id"))
            owner_id = snowflake_or_none(self.document_owner(document))
            if not role_id or not owner_id or role_id == snowflake_or_none(document.get("highlight_id")):
                continue
            role = guild.get_role(role_id)
            if not self.cog._is_personal_vip_role(role) or role.is_default():
                continue
            if owner_id not in bindings[role_id] or str(document["_id"]) == str(owner_id):
                bindings[role_id][owner_id] = document

        for role_id, owners in bindings.items():
            # Ambiguous ownership cannot produce a reliable personal limit.
            if len(owners) != 1:
                continue
            owner_id, document = next(iter(owners.items()))
            owner = guild.get_member(owner_id)
            role = guild.get_role(role_id)
            if owner is None or role is None or owner.bot:
                continue
            base = self.cog.get_vip_limit(owner)
            if not base:
                continue
            extra = vip_extras(document, role_id)
            limit = base + extra
            total = len(role.members)
            if total <= limit:
                if guild.chunked:
                    self.clear(role_id)
                continue
            notify_admin = role_id not in self.reported
            self.reported.add(role_id)
            await self.remind_owner(owner, role, total, limit, guild.chunked)
            if not notify_admin:
                continue
            log.info("vip_member_limit_exceeded guild_id=%s role_id=%s total=%s limit=%s",
                     guild.id, role_id, total, limit)
            minimum = "" if guild.chunked else "Pelo menos "
            await send_admin_audit_dm(
                self.cog.bot, category="vip", action="Cargo VIP acima do limite de membros",
                guild=guild, actor=None, target=owner,
                reason="O cargo pessoal está com mais membros do que o limite do VIP e das vagas compradas.",
                details={"Cargo": f"{escape_markdown(role.name)} (ID {role.id})", "Membros no cargo": f"{minimum}{total}",
                         "Limite": f"{limit} ({base} do VIP + {extra} vagas extras)",
                         "Excedente": f"{minimum}{total - limit}"},
                source="vip_capacity_check",
            )
