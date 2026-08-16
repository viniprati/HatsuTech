from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    embed = await self._build_leaderboard_embed(interaction.guild, "eter")
    view = EcoLeaderboardView(self, interaction.user.id)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
