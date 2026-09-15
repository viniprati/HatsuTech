import discord
from discord import app_commands
from discord.app_commands import MissingPermissions
from PIL import Image
import io
import time
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from database import is_db_online

try:
    from config import ALLOWED_GUILD_IDS, MAIN_GUILD_ID, TEST_GUILD_ID
except Exception:
    MAIN_GUILD_ID = 609159041499004982
    TEST_GUILD_ID = 1442105700246491189
    ALLOWED_GUILD_IDS = (MAIN_GUILD_ID, TEST_GUILD_ID)


BOT_OWNER_ID = 983870132063453235
FULL_ACCESS_ROLE_ID = 1117577222249795725


BRT = timezone(timedelta(hours=-3))


class AntiSpamSystem:
    """Detector de flood usado apenas para ignorar pontuacao de mensagens."""

    def __init__(self, max_messages: int = 6, window_seconds: int = 8):
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self._messages = defaultdict(deque)

    def is_spamming(self, user_key) -> bool:
        now = time.time()
        events = self._messages[user_key]
        while events and now - events[0] > self.window_seconds:
            events.popleft()
        events.append(now)
        return len(events) > self.max_messages


def has_full_access(user: discord.abc.User | discord.Member) -> bool:
    """Bypass global: Dono do bot OU cargo de acesso total."""
    if user.id == BOT_OWNER_ID:
        return True
    roles = getattr(user, "roles", None)
    if roles:
        return any(getattr(role, "id", None) == FULL_ACCESS_ROLE_ID for role in roles)
    return False


def is_allowed_guild(guild_id: int | None) -> bool:
    if guild_id is None:
        return False
    return int(guild_id) in set(ALLOWED_GUILD_IDS)


def get_data_guild_id(guild_id: int | None) -> int:
    if guild_id is None:
        return MAIN_GUILD_ID
    gid = int(guild_id)
    if gid == TEST_GUILD_ID:
        return MAIN_GUILD_ID
    return gid


def get_brt_keys():
    """Retorna chaves de data (Dia, Semana, Mes) em BRT."""
    now = datetime.now(BRT)
    return {
        "day": now.strftime("%Y-%m-%d"),
        "week": now.strftime("%Y-%W"),
        "month": now.strftime("%Y-%m"),
    }


def process_icon(image_bytes: bytes) -> bytes:
    """Processa imagens para usar em icones de cargos."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if getattr(img, "is_animated", False):
            return image_bytes
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        img.thumbnail((128, 128))
        output = io.BytesIO()
        img.save(output, format="PNG", optimize=True)
        return output.getvalue()
    except Exception:
        return image_bytes


def check_owner_or_perm(allowed_role_id=None, **perms):
    """
    Verifica permissoes na seguinte ordem:
    1. Dono do bot OU cargo de acesso total -> libera tudo.
    2. Cargo especifico permitido (allowed_role_id) -> libera.
    3. Permissoes nativas do Discord (administrator/manage_messages/etc).
    """

    async def predicate(interaction: discord.Interaction):
        if has_full_access(interaction.user):
            return True

        roles = getattr(interaction.user, "roles", [])
        if allowed_role_id and any(role.id == allowed_role_id for role in roles):
            return True

        if interaction.channel is None:
            raise MissingPermissions(list(perms) or ["guild_channel"])

        permissions = interaction.channel.permissions_for(interaction.user)
        missing = [perm for perm, value in perms.items() if getattr(permissions, perm) != value]

        if not missing:
            return True

        raise MissingPermissions(missing)

    return app_commands.check(predicate)


def can_manage_role(actor: discord.Member, target_role: discord.Role) -> bool:
    """Confere se o membro pode gerenciar um cargo pela hierarquia do Discord."""
    if has_full_access(actor):
        return True
    if actor.guild.owner_id == actor.id:
        return True
    return target_role < actor.top_role


def bot_can_manage_role(guild: discord.Guild, target_role: discord.Role) -> bool:
    me = guild.me
    if me is None:
        return False
    return target_role < me.top_role


async def ensure_db_online(interaction: discord.Interaction, action_label: str = "esta operacao") -> bool:
    """Falha amigavelmente quando o MongoDB estiver offline para comandos criticos."""
    if is_db_online():
        return True

    msg = f"Banco de dados indisponivel no momento. Nao foi possivel executar {action_label}. Tente novamente em instantes."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)
    return False


async def ensure_guild_interaction(interaction: discord.Interaction, action_label: str = "este comando") -> bool:
    if interaction.guild is not None:
        return True

    msg = f"Use {action_label} dentro de um servidor."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)
    return False


def build_update_pipeline(field_name: str, value: int = 1):
    """Pipeline MongoDB para somar estatisticas (Chat/Voz)."""
    keys = get_brt_keys()
    return [
        {
            "$set": {
                f"{field_name}": {"$add": [{"$ifNull": [f"${field_name}", 0]}, value]},
                "stats_daily": {
                    "$cond": {
                        "if": {"$eq": ["$stats_daily.key", keys["day"]]},
                        "then": {"key": keys["day"], "value": {"$add": ["$stats_daily.value", value]}},
                        "else": {"key": keys["day"], "value": value},
                    }
                },
                "stats_weekly": {
                    "$cond": {
                        "if": {"$eq": ["$stats_weekly.key", keys["week"]]},
                        "then": {"key": keys["week"], "value": {"$add": ["$stats_weekly.value", value]}},
                        "else": {"key": keys["week"], "value": value},
                    }
                },
                "stats_monthly": {
                    "$cond": {
                        "if": {"$eq": ["$stats_monthly.key", keys["month"]]},
                        "then": {"key": keys["month"], "value": {"$add": ["$stats_monthly.value", value]}},
                        "else": {"key": keys["month"], "value": value},
                    }
                },
            }
        }
    ]
