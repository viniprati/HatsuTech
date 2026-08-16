from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction, usuario: discord.Member):
    doc = await asyncio.to_thread(self._get_user_doc, usuario.id, interaction.guild.id)
    await interaction.response.send_message(embed=self._format_balance_embed(usuario, doc), ephemeral=True)
