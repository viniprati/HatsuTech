from __future__ import annotations
from ..cog import *


async def execute(self, it, usuario: discord.Member, cargo: discord.Role):
    if not await ensure_db_online(it, "o comando /vincular_vip"):
        return
    if cargo.id in VIP_CONFIG:
        return await it.response.send_message("Nao e permitido vincular um cargo base de elegibilidade como VIP pessoal.", ephemeral=True)
    async with self._get_vip_lock(usuario.id, it.guild.id):
        conflicting = await asyncio.to_thread(
            vip_col.find_one,
            {"guild_id": str(it.guild.id), "role_id": {"$in": [str(cargo.id), cargo.id]}},
        )
        conflict_user_id = vip_document_user_id(conflicting) if conflicting else None
        if conflict_user_id and conflict_user_id != str(usuario.id):
            return await it.response.send_message("Este cargo ja esta vinculado a outro usuario nesta guild.", ephemeral=True)
        await self._position_common_vip_role(it.guild, cargo)
        await self._update_vip_role_with_snapshot(
            usuario.id,
            {
                "$set": {
                    "role_id": str(cargo.id),
                    "role_source": "command:/vincular_vip",
                    "status": "active",
                    "entitlement_active": True,
                    "review_required": False,
                    "missing_member": False,
                    "missing_role": False,
                    "last_seen_at": datetime.now(timezone.utc),
                },
                "$unset": {
                    "cleanup_reason": "",
                    "cleanup_source": "",
                    "cleanup_checked_at": "",
                    "disabled_reason": "",
                    "disabled_at": "",
                },
            },
            "command:/vincular_vip",
            actor_id=it.user.id,
            guild_id=it.guild.id,
            upsert=True
        )
    await it.response.send_message(f"✅ Vinculado {cargo.mention} a {usuario.mention}", ephemeral=True)
