import discord
from discord import app_commands
from discord.ext import commands
import datetime
import asyncio


from database import updates_col


from utils import check_owner_or_perm

class Atualizacoes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="notificacao", description="Ative ou desative o recebimento de novidades do bot na sua DM.")
    async def notificacao(self, interaction: discord.Interaction):
        from .commands.notificacao_command import execute

        await execute(self, interaction)


    @app_commands.command(name="anunciar", description="Envia uma atualização via DM para todos os inscritos (Admin/Owner).")
    @app_commands.describe(titulo="Título do anúncio", mensagem="Corpo da mensagem", imagem="Imagem opcional para o embed")
    @check_owner_or_perm(administrator=True)
    async def anunciar(self, interaction: discord.Interaction, titulo: str, mensagem: str, imagem: discord.Attachment = None):
        from .commands.anunciar_command import execute

        await execute(self, interaction, titulo, mensagem, imagem)

async def setup(bot):
    await bot.add_cog(Atualizacoes(bot))
