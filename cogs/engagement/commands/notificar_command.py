from __future__ import annotations
from ..cog import *


async def execute(self, it, mensagem: str):
    try:
        rid = await self.get_vip_role_id(it.user.id, it.guild.id)
        role = it.guild.get_role(int(rid)) if rid else None

        if not role:
            return await it.response.send_message("🚫 Acesso não autorizado. Contrato VIP ausente.", ephemeral=True)

        await it.channel.send(f"🔔 **Broadcast de {it.user.mention}:**\n\n{mensagem}\n\n|| {role.mention} ||", allowed_mentions=discord.AllowedMentions(roles=[role]))
        await it.response.send_message("✅ Broadcast transmitido.", ephemeral=True)
    except discord.Forbidden:
        await it.response.send_message("❌ Permissões insuficientes para enviar a mensagem no canal atual.", ephemeral=True)
    except Exception as e:
        log.error(f"Erro em notificar vip: {e}")
        await it.response.send_message("❌ Falha de transmissão no sistema.", ephemeral=True)
