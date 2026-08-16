from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction):
    doc = await asyncio.to_thread(self._get_user_doc, interaction.user.id, interaction.guild.id)
    await interaction.response.send_message(embed=self._format_balance_embed(interaction.user, doc), ephemeral=True)
