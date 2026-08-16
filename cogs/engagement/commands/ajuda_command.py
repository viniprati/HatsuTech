from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Central de Ajuda",
        description="Interface de suporte ativada.\n\n"
                    "Navegue pelas **Categorias** usando o menu suspenso abaixo.\n"
                    "Sintaxe de execução via prefixo Slash (`/`).",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=self.bot.user.display_avatar.url)
    embed.set_footer(text="Módulo de Assistência")

    view = HelpView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
