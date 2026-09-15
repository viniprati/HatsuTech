from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction):
    if not await ensure_guild_interaction(interaction, "o comando /eco saldo"):
        return
    doc = await asyncio.to_thread(self._get_user_doc, interaction.user.id, interaction.guild.id)
    await interaction.response.send_message(embed=self._format_balance_embed(interaction.user, doc), ephemeral=True)
