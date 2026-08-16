from __future__ import annotations
from ..cog import *


async def execute(self, it, usuario: discord.User = None):
    try:
        u = usuario or it.user
        member = it.guild.get_member(u.id)
        e = discord.Embed(color=discord.Color.blurple())
        e.set_author(name=f"Perfil de {u.name}", icon_url=u.display_avatar.url)
        e.set_thumbnail(url=u.display_avatar.url)
        e.add_field(name="🆔 Identificação", value=f"`{u.id}`", inline=True)
        e.add_field(name="📅 Criação", value=f"<t:{int(u.created_at.timestamp())}:d>", inline=True)

        if member:
            e.add_field(name="📥 Ingresso", value=f"<t:{int(member.joined_at.timestamp())}:d>" if member.joined_at else "N/A", inline=True)
            badges_str = await self.get_badges(member)
            e.add_field(name="🏅 Conquistas", value=badges_str, inline=False)

            roles = sorted(member.roles, key=lambda r: r.position, reverse=True)
            roles_mentions = [r.mention for r in roles if r.name != "@everyone"]
            roles_str = ", ".join(roles_mentions) if roles_mentions else "Nenhum"

            if len(roles_str) > 1000:
                roles_str = roles_str[:1000] + "..."
            e.add_field(name=f"🎭 Cargos ({len(roles_mentions)})", value=roles_str, inline=False)
        else:
            e.description = "⚠️ Este usuário não está neste servidor."

        await it.response.send_message(embed=e)
    except Exception as e:
        log.error(f"Erro ao compilar userinfo: {e}")
        await it.response.send_message("❌ Não consegui carregar as informações do usuário.", ephemeral=True)
