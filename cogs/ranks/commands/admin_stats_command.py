from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    view = AdminDashboardView(self.bot, self, interaction.user.id)
    await view.refresh_snapshot(interaction.guild)
    await interaction.followup.send(embed=view.build_overview_embed(interaction.guild), view=view, ephemeral=True)
