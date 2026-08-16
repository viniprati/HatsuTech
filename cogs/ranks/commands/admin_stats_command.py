from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    view = AdminDashboardView(self.bot, self)
    await view.refresh_snapshot(interaction.guild)
    total_members = view.snapshot["total_members"] or 1
    engagement_rate = (view.snapshot["active_today"] / total_members) * 100
    tag_users = view.snapshot["server_tag_users"]
    tag_rate = (tag_users / total_members) * 100
    embed = discord.Embed(
        title="🛡️ Painel Administrativo",
        description=(
            "Resumo atual do servidor.\n\n"
            f"**Ativos hoje:** {view.snapshot['active_today']} | "
            f"**Engajamento:** {engagement_rate:.1f}%\n"
            f"**Tag do servidor em uso:** {tag_users} ({tag_rate:.1f}%)"
        ),
        color=0x2b2d31
    )
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
    embed.set_footer(text=f"Atualizado às {view.snapshot_at.strftime('%H:%M:%S')}")
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
