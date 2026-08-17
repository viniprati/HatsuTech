import asyncio
import logging
import os
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().with_name(".env"))
load_dotenv(Path.home() / ".env", override=False)


try:
    from config import ALLOWED_GUILD_IDS, CHAT_COUNT_CHANNEL_ID, DISCORD_TOKEN, validate_required_config
except ImportError:
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    ALLOWED_GUILD_IDS = (609159041499004982,)
    CHAT_COUNT_CHANNEL_ID = 1117559464363573358
    validate_required_config = lambda: bool(DISCORD_TOKEN)

AntiSpamSystem = None
try:
    from utils import AntiSpamSystem as ImportedAntiSpamSystem, BOT_OWNER_ID, has_full_access, is_allowed_guild
    AntiSpamSystem = ImportedAntiSpamSystem
except ImportError as e:
    print(f"WARN: AntiSpamSystem unavailable: {e}. Spam scoring filter disabled.")
    from utils import BOT_OWNER_ID, has_full_access

    def is_allowed_guild(guild_id: int | None) -> bool:
        return guild_id == 609159041499004982

try:
    from database import event_col, msg_col, client
    print("OK: Database modules loaded in main.")
except ImportError as e:
    print(f"ERROR: Failed to import database modules: {e}")

    class DummyCol:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    msg_col = event_col = DummyCol()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SecurityBot")

BERSERK_VIP_ID = 999723165225857074
MUGETSU_VIP_ID = 1121511055059861524
MONARCH_VIP_ID = 1351596017631494195
VIP_SCORE_BONUSES = {
    BERSERK_VIP_ID: 5,
    MUGETSU_VIP_ID: 10,
    MONARCH_VIP_ID: 15,
}


def summarize_app_command_error(error: Exception) -> str:
    if isinstance(error, app_commands.CommandInvokeError) and error.original:
        error = error.original

    if isinstance(error, discord.HTTPException):
        details = str(error)
        if error.status == 429 and "1015" in details:
            return "HTTPException 429: Cloudflare 1015 rate limit from discord.com"
        if len(details) > 500:
            details = details[:500] + "... [truncated]"
        return f"HTTPException status={error.status} code={getattr(error, 'code', None)}: {details}"

    details = str(error)
    if len(details) > 500:
        details = details[:500] + "... [truncated]"
    return f"{type(error).__name__}: {details}"


def get_member_score_bonus_percent(member) -> int:
    best_percent = 0
    for role in getattr(member, "roles", []):
        best_percent = max(best_percent, VIP_SCORE_BONUSES.get(role.id, 0))
    return best_percent


def get_integer_bonus_gain(base_amount: int, bonus_percent: int, remainder: float = 0) -> tuple[int, float]:
    base_amount = int(max(base_amount, 0))
    if bonus_percent <= 0 or base_amount <= 0:
        return base_amount, 0
    raw_bonus = float(remainder or 0) + (base_amount * bonus_percent / 100)
    whole_bonus = int(raw_bonus)
    return base_amount + whole_bonus, round(raw_bonus - whole_bonus, 6)


class SecurityBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.voice_states = True
        intents.presences = True

        super().__init__(command_prefix="!", intents=intents, help_command=None)

        self.spam_system = AntiSpamSystem() if AntiSpamSystem else None
        self.event_cooldown = {}
        self.event_cache = {}
        self.last_event_check = 0

    @staticmethod
    def _is_allowed_guild_id(guild_id: int | None) -> bool:
        return is_allowed_guild(guild_id)

    async def _leave_unauthorized_guilds(self):
        for guild in list(self.guilds):
            if not self._is_allowed_guild_id(guild.id):
                try:
                    logger.warning("Leaving unauthorized guild: %s (%s)", guild.name, guild.id)
                    await guild.leave()
                except Exception as e:
                    logger.error("Failed to leave unauthorized guild %s (%s): %s", guild.name, guild.id, e)

    async def _app_command_guild_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild and self._is_allowed_guild_id(interaction.guild.id):
            return True

        msg = "Este bot só funciona nos servidores autorizados."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return False

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            command_name = interaction.command.name if interaction.command else "desconhecido"
            print(f"Command error in {command_name}: {summarize_app_command_error(error)}")
            try:
                await interaction.followup.send("Não consegui concluir esse comando agora.", ephemeral=True)
            except Exception:
                pass
            return

        if isinstance(error, app_commands.MissingPermissions):
            missing = [perm.replace("_", " ").title() for perm in error.missing_permissions]
            await interaction.response.send_message(
                f"Você não tem permissão para usar esse comando. Necessário: {', '.join(missing)}.",
                ephemeral=True,
            )
        elif isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("Você não tem permissão para usar esse comando.", ephemeral=True)
        elif isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"Calma um pouco. Tente de novo em {error.retry_after:.2f}s.", ephemeral=True
            )
        else:
            command_name = interaction.command.name if interaction.command else "desconhecido"
            print(f"Command error in {command_name}: {summarize_app_command_error(error)}")
            try:
                await interaction.response.send_message("Não consegui concluir esse comando agora.", ephemeral=True)
            except Exception:
                pass

    async def _refresh_event_cache(self):
        docs = await asyncio.to_thread(lambda: list(event_col.find({"active": True})))
        active_by_channel = {}
        for doc in docs:
            try:
                channel_id = int(doc.get("channel_id"))
            except (TypeError, ValueError):
                continue
            active_by_channel[channel_id] = doc
        self.event_cache = active_by_channel
        self.last_event_check = time.time()

    async def process_event_message(self, message: discord.Message):
        content = (message.content or "").strip()
        if len(content) <= 6:
            return
        if len(set(content.lower().replace(" ", ""))) < 4:
            return

        now = time.time()
        last_event_msg = self.event_cooldown.get((message.channel.id, message.author.id), 0)
        if now - last_event_msg < 2:
            return

        if now - self.last_event_check > 10:
            try:
                await self._refresh_event_cache()
            except Exception as e:
                print(f"Failed to refresh event cache: {e}")

        data = self.event_cache.get(message.channel.id)
        if not data or not data.get("active", False):
            return

        if self.spam_system and self.spam_system.is_spamming((message.guild.id, message.channel.id, message.author.id)):
            return

        if data.get("end_time") and now > data.get("end_time"):
            await asyncio.to_thread(
                event_col.update_one,
                {"_id": data.get("_id", "config")},
                {"$set": {"active": False, "last_event_scores": data.get("current_scores", {}).copy()}},
            )
            self.event_cache.pop(message.channel.id, None)
            return

        try:
            self.event_cooldown[(message.channel.id, message.author.id)] = now
            uid = str(message.author.id)
            fresh_data = await asyncio.to_thread(event_col.find_one, {"_id": data.get("_id", "config")}) or data
            remainders = fresh_data.get("score_bonus_remainders") or {}
            bonus_percent = get_member_score_bonus_percent(message.author)
            score_gain, remainder = get_integer_bonus_gain(1, bonus_percent, remainders.get(uid, 0))
            current_scores = fresh_data.get("current_scores") or {}
            current_score = int(float(current_scores.get(uid, 0) or 0))
            update = {"$set": {f"current_scores.{uid}": current_score + score_gain}}
            if bonus_percent > 0:
                update["$set"][f"score_bonus_remainders.{uid}"] = remainder
            await asyncio.to_thread(
                event_col.update_one,
                {"_id": data.get("_id", "config")},
                update,
            )
        except Exception as e:
            print(f"Failed to compute event score: {e}")

    async def setup_hook(self):
        self.tree.on_error = self.on_tree_error
        self.tree.interaction_check = self._app_command_guild_check

        print("--- Loading cogs ---")
        if not os.path.exists("./cogs"):
            os.makedirs("./cogs")
            print("Created 'cogs' folder.")

        if os.path.exists("./cogs"):
            entries = sorted(os.listdir("./cogs"))
            for entry in entries:
                entry_path = os.path.join("./cogs", entry)
                module_name = None

                if entry.endswith(".py"):
                    module_name = f"cogs.{entry[:-3]}"
                elif os.path.isdir(entry_path) and os.path.exists(os.path.join(entry_path, "__init__.py")):
                    module_name = f"cogs.{entry}"

                if not module_name:
                    continue

                try:
                    await self.load_extension(module_name)
                    print(f"Loaded cog: {entry}")
                except Exception as e:
                    print(f"Failed to load {entry}: {e}")
        else:
            print("WARN: 'cogs' folder not found.")

    async def on_guild_join(self, guild: discord.Guild):
        if self._is_allowed_guild_id(guild.id):
            return
        logger.warning("Joined unauthorized guild (%s). Leaving...", guild.id)
        try:
            await guild.leave()
        except Exception as e:
            logger.error("Could not leave guild %s: %s", guild.id, e)

    async def on_ready(self):
        logger.info("SecurityBot Online: %s (ID: %s)", self.user, self.user.id)
        print("\n--- BOT ONLINE ---")
        print(f"Owner ID: {BOT_OWNER_ID}")
        print(f"Allowed guilds: {ALLOWED_GUILD_IDS}")
        print("------------------\n")
        await self._leave_unauthorized_guilds()
        await self.change_presence(activity=discord.Game(name="Minecraft .gg/animescafe"))

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.type == discord.InteractionType.application_command:
            if not await self._app_command_guild_check(interaction):
                return False
        return True

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild or not self._is_allowed_guild_id(message.guild.id):
            return

        await self.process_event_message(message)

        await self.process_commands(message)


def create_bot():
    bot = SecurityBot()

    @bot.check
    def prefix_guild_check(ctx: commands.Context):
        return bool(ctx.guild and is_allowed_guild(ctx.guild.id))

    @bot.command(name="sync")
    async def sync(ctx):
        if not ctx.guild or not is_allowed_guild(ctx.guild.id):
            return

        if has_full_access(ctx.author) or ctx.author.guild_permissions.administrator:
            msg = await ctx.send("Sincronizando comandos slash...")
            try:
                bot.tree.clear_commands(guild=ctx.guild)
                bot.tree.copy_global_to(guild=ctx.guild)
                synced = await bot.tree.sync(guild=ctx.guild)
                await msg.edit(content=f"Pronto. {len(synced)} comandos slash ativos neste servidor.")
            except Exception as e:
                await msg.edit(content=f"Não consegui sincronizar os comandos: `{e}`")
        else:
            await ctx.send("Só o dono do bot ou alguém com acesso total pode fazer isso.")

    return bot


async def run_bot_with_backoff():
    wait_seconds = 60
    max_wait = 1800

    while True:
        bot = create_bot()
        try:
            await bot.start(DISCORD_TOKEN)
            return
        except discord.HTTPException as e:
            err_text = str(e)
            is_cf_1015 = e.status == 429 and "1015" in err_text

            if is_cf_1015:
                logger.error("Cloudflare 1015 during login. Waiting %ss before retry.", wait_seconds)
            else:
                logger.exception("HTTP failure on bot login/start (%s). Retry in %ss.", e.status, wait_seconds)

            await asyncio.sleep(wait_seconds)
            wait_seconds = min(wait_seconds * 2, max_wait)
        except Exception:
            logger.exception("Unexpected bootstrap failure. Retry in %ss.", wait_seconds)
            await asyncio.sleep(wait_seconds)
            wait_seconds = min(wait_seconds * 2, max_wait)
        finally:
            try:
                await bot.close()
            except Exception:
                pass


if __name__ == "__main__":
    if validate_required_config():
        asyncio.run(run_bot_with_backoff())
    else:
        print("CRITICAL: Token not found in .env or config.py")
