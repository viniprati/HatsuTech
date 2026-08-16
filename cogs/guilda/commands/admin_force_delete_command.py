from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, alvo: discord.Member):

    guild_data = self.get_user_guild(alvo.id)

    if not guild_data:
        return await it.response.send_message(
            f"❌ O usuário **{alvo.display_name}** não pertence a nenhuma guilda, então não há nada para apagar.",
            ephemeral=True
        )


    nome_guilda = guild_data['name']
    id_guilda = guild_data['_id']
    runtime_data = await self.build_guild_runtime_view(it.guild, guild_data)
    lider_text = runtime_data["_leader_text"]
    qtd_membros = runtime_data["_active_member_count"]
    xp_total = guild_data.get("total_xp", 0)


    embed = discord.Embed(
        title="🚨 EXCLUSÃO ADMINISTRATIVA FORÇADA",
        description="Você está prestes a **APAGAR PERMANENTEMENTE** a guilda abaixo.\nEsta ação não pode ser desfeita e todo o XP será perdido.",
        color=discord.Color.dark_red()
    )

    embed.add_field(name="Nome da Guilda", value=f"**{nome_guilda}**", inline=True)
    embed.add_field(name="ID no Banco", value=f"`{id_guilda}`", inline=True)
    embed.add_field(name="Líder", value=lider_text, inline=False)
    embed.add_field(name="Estatísticas", value=f"👥 Membros ativos: {qtd_membros}\n✨ XP total: {xp_total:,}", inline=False)
    embed.set_footer(text=f"Solicitado por Admin: {it.user.display_name}")


    view = GuildConfirmDelete(guild_id=id_guilda, author_id=it.user.id)

    await it.response.send_message(embed=embed, view=view, ephemeral=True)
