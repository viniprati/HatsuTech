from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction, quantidade: int = 1):
    await interaction.response.defer(ephemeral=True)
    await self._open_box(interaction, "loot_premium", quantidade)
