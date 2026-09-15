import discord
from discord import app_commands
from discord.ext import commands
import datetime
import asyncio
import logging


from database import updates_col, welcome_dm_logs_col


from utils import (
    DISCORD_EMBED_DESCRIPTION_LIMIT,
    DISCORD_EMBED_TITLE_LIMIT,
    check_owner_or_perm,
    ensure_db_online,
    is_allowed_guild,
    truncate_discord_text,
)

try:
    from config import MAIN_GUILD_ID
except ImportError:
    MAIN_GUILD_ID = 609159041499004982

log = logging.getLogger(__name__)
APOIADOR_ROLE_ID = 1512225314502086746
APOIADOR_CHANNEL_ID = 1482468114313773271
REPOSITORY_URL = "https://github.com/viniprati/HatsuTech"
TERMS_URL = "https://viniprati.github.io/Hatsutech-Termos-de-Uso/"
PRIVACY_URL = "https://viniprati.github.io/Hatsutech-Politica-de-Privacidade/"
GITHUB_EMOJI = "<:Github:1539330267347423252>"
DOCUMENTS_EMOJI = "<a:6_staff:1512192546732900543>"
SUPPORTER_EMOJI = "<:3121discordearlysupporter:1539331728634806272>"
WELCOME_EMOJI = "<:welcome:1539332759112392835>"


def build_member_welcome_embed(member: discord.Member, bot_user: discord.ClientUser | None = None) -> discord.Embed:
    guild = member.guild
    supporter_url = f"https://discord.com/channels/{MAIN_GUILD_ID}/{APOIADOR_CHANNEL_ID}"
    embed = discord.Embed(
        title=f"{WELCOME_EMOJI} Bem-vindo ao {guild.name}",
        description=(
            f"Oi, {member.mention}! Eu sou a **HatsuTech**, bot oficial do servidor.\n\n"
            "Esta mensagem reúne alguns links importantes para você conhecer melhor o servidor, "
            "os documentos oficiais e o funcionamento do projeto."
        ),
        color=discord.Color.from_rgb(255, 211, 77),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(
        name=f"{SUPPORTER_EMOJI} Cargo Apoiador",
        value=(
            "Se você usa a tag do servidor no perfil, pode resgatar o cargo **Apoiador** "
            "e receber benefícios exclusivos dentro da comunidade.\n"
            f"[Resgatar cargo Apoiador]({supporter_url})"
        ),
        inline=False,
    )
    embed.add_field(
        name=f"{DOCUMENTS_EMOJI} Documentos oficiais",
        value=(
            f"[Termos de Uso]({TERMS_URL})\n"
            f"[Política de Privacidade]({PRIVACY_URL})"
        ),
        inline=True,
    )
    embed.add_field(
        name=f"{GITHUB_EMOJI} Código do bot",
        value=(
            "O repositório da HatsuTech está público para leitura, revisão e acompanhamento da comunidade.\n"
            f"[Acessar repositório]({REPOSITORY_URL})"
        ),
        inline=False,
    )
    embed.add_field(
        name="Licença",
        value=(
            "O projeto é **source-available**, não open-source. O código pode ser lido e revisado, "
            "mas uso, cópia, hospedagem, modificação, redistribuição ou reutilização exigem autorização prévia."
        ),
        inline=False,
    )
    if bot_user:
        embed.set_thumbnail(url=bot_user.display_avatar.url)
    embed.set_footer(text="Hatsutech • Animes Café")
    return embed


class Atualizacoes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _record_welcome_dm(self, member: discord.Member, status: str, error: str | None = None):
        doc = {
            "type": "member_welcome_dm",
            "guild_id": str(member.guild.id),
            "user_id": str(member.id),
            "status": status,
            "error": error[:300] if error else None,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        try:
            await asyncio.to_thread(
                welcome_dm_logs_col.update_one,
                {"type": doc["type"], "guild_id": doc["guild_id"], "user_id": doc["user_id"]},
                {
                    "$set": doc,
                    "$inc": {"attempts": 1},
                },
                upsert=True,
            )
        except Exception as exc:
            log.warning("welcome_dm_log_failed guild_id=%s user_id=%s error=%s", member.guild.id, member.id, exc)

    async def _welcome_dm_already_recorded(self, member: discord.Member) -> bool:
        try:
            existing = await asyncio.to_thread(
                welcome_dm_logs_col.find_one,
                {
                    "type": "member_welcome_dm",
                    "guild_id": str(member.guild.id),
                    "user_id": str(member.id),
                    "status": {"$in": ["sent", "dm_closed"]},
                },
            )
            return existing is not None
        except Exception as exc:
            log.warning("welcome_dm_lookup_failed guild_id=%s user_id=%s error=%s", member.guild.id, member.id, exc)
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot or not is_allowed_guild(member.guild.id):
            return

        if await self._welcome_dm_already_recorded(member):
            log.info("welcome_dm_skipped_existing guild_id=%s user_id=%s", member.guild.id, member.id)
            return

        embed = build_member_welcome_embed(member, self.bot.user)
        try:
            await member.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            await self._record_welcome_dm(member, "sent")
            log.info("welcome_dm_sent guild_id=%s user_id=%s", member.guild.id, member.id)
        except discord.Forbidden:
            await self._record_welcome_dm(member, "dm_closed")
            log.info("welcome_dm_blocked guild_id=%s user_id=%s", member.guild.id, member.id)
        except discord.HTTPException as exc:
            await self._record_welcome_dm(member, "http_error", str(exc))
            log.warning("welcome_dm_http_error guild_id=%s user_id=%s status=%s", member.guild.id, member.id, exc.status)
        except Exception as exc:
            await self._record_welcome_dm(member, "unexpected_error", str(exc))
            log.exception("welcome_dm_unexpected_error guild_id=%s user_id=%s", member.guild.id, member.id)


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
