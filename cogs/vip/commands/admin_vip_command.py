from __future__ import annotations
from ..cog import *
from ..cog import _to_int_or_none

ADMIN_VIP_MAX_RECORDS = 2000
ADMIN_VIP_QUERY_TIMEOUT_SECONDS = 8
ADMIN_VIP_DB_MAX_TIME_MS = 7000


async def execute(self, it):
    await it.response.defer(ephemeral=True)
    if not await ensure_db_online(it, "o comando /admin_vip"):
        return

    guild_id = str(it.guild.id)
    role_ids = [value for role in it.guild.roles for value in (str(role.id), role.id)]
    projection = {
        "_id": 1,
        "user_id": 1,
        "guild_id": 1,
        "role_id": 1,
        "role_source": 1,
        "highlight_id": 1,
    }

    def _limited_find(collection, query, fields):
        cursor = collection.find(query, fields).max_time_ms(ADMIN_VIP_DB_MAX_TIME_MS)
        return list(cursor.limit(ADMIN_VIP_MAX_RECORDS + 1))

    def _fetch_records():
        scoped = _limited_find(vip_col, {"guild_id": guild_id}, projection)
        legacy = _limited_find(
            vip_col,
            {
                "guild_id": {"$exists": False},
                "$or": [
                    {"role_id": {"$in": role_ids}},
                    {"highlight_id": {"$in": role_ids}},
                ],
            },
            projection,
        )
        truncated = len(scoped) > ADMIN_VIP_MAX_RECORDS or len(legacy) > ADMIN_VIP_MAX_RECORDS
        scoped = scoped[:ADMIN_VIP_MAX_RECORDS]
        legacy = legacy[:ADMIN_VIP_MAX_RECORDS]

        merged = {}
        for doc in legacy + scoped:
            user_id = vip_document_user_id(doc) or str(doc.get("_id"))
            selected = merged.get(user_id)
            keeps_original_id = str(doc.get("_id")) == str(user_id)
            selected_keeps_original_id = selected and str(selected.get("_id")) == str(user_id)
            if selected is None or (keeps_original_id and not selected_keeps_original_id):
                merged[user_id] = doc
        records_with_personal_vip = [
            doc for doc in merged.values()
            if doc.get("role_id") not in (None, "")
            or doc.get("role_source") == "command:/vip"
            or doc.get("highlight_id") not in (None, "")
        ]
        return records_with_personal_vip, truncated

    try:
        records, records_truncated = await asyncio.wait_for(
            asyncio.to_thread(_fetch_records),
            timeout=ADMIN_VIP_QUERY_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return await it.followup.send(
            "O /admin_vip excedeu o tempo limite da consulta. Tente novamente em instantes.",
            ephemeral=True,
        )
    except Exception:
        log.exception("Falha ao consultar dados do /admin_vip guild_id=%s", guild_id)
        return await it.followup.send(
            "Falha ao consultar os VIPs. O erro foi registrado no console do bot.",
            ephemeral=True,
        )

    try:
        lines = []
        visible_records = []
        for data in records:
            uid_text = vip_document_user_id(data)
            uid = _to_int_or_none(uid_text)
            member = it.guild.get_member(uid) if uid else None
            member_text = member.mention if member else f"ID {uid_text or data.get('_id')}"

            role_id = data.get("role_id")
            role = it.guild.get_role(_to_int_or_none(role_id)) if role_id else None
            if role:
                role_text = f"VIP {role.mention}"
            else:
                role_text = "VIP sem cargo pessoal"

            highlight_id = data.get("highlight_id")
            highlight = it.guild.get_role(_to_int_or_none(highlight_id)) if highlight_id else None
            if highlight:
                role_text = f"{role_text} | Destaque {highlight.mention}"
            elif highlight_id:
                role_text = f"{role_text} | Destaque ausente `{highlight_id}`"

            flags = []
            eligible = member and self._is_vip_eligible(member)
            if role:
                flags.append("cargo pessoal ativo")
            elif eligible:
                flags.append("pode recriar pelo `/vip`")
            else:
                flags.append("sem cargo VIP ou Booster Premium")
            if highlight:
                flags.append("destaque Monarch ativo")
            if data.get("role_source"):
                flags.append(f"origem: `{data.get('role_source')}`")
            if str(data.get("_id")) != str(uid_text):
                flags.append("chave composta")
            suffix = f" | {'; '.join(flags)}" if flags else ""
            lines.append(f"{member_text} | {role_text}{suffix}")
            visible_records.append(data)

        compound_key_count = sum(
            str(data.get("_id")) != str(vip_document_user_id(data))
            for data in visible_records
        )
        notices = []
        if compound_key_count:
            notices.append(f"{compound_key_count} registro(s) com chave composta")
        if records_truncated:
            notices.append(f"resultado truncado em {ADMIN_VIP_MAX_RECORDS} itens por consulta")
        notice = " | ".join(notices) if notices else None
        view = VipAdminView(lines, f"Admin VIPs ({len(lines)})", it.user.id, notice=notice)
        await it.followup.send(embed=view.get_embed(), view=view, ephemeral=True)
    except Exception:
        log.exception("Falha ao montar ou enviar /admin_vip guild_id=%s", guild_id)
        await it.followup.send(
            "Falha ao montar o painel de VIPs. O erro foi registrado no console do bot.",
            ephemeral=True,
        )
