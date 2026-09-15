import discord
from discord import app_commands
from discord.ext import commands
from discord.http import Route
import re
from datetime import datetime




from utils import bot_can_manage_role, can_manage_role, check_owner_or_perm, ensure_guild_interaction, process_icon


try:
    from config import LOG_CARGOS_ID
except ImportError:
    LOG_CARGOS_ID = 1444675225743528087

LISTA_MODERATION_ROLES = (
    (1117570040204628028, "Moderador Sênior"),
    (1117569899691253832, "Moderador"),
)

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _parse_hex_color(self, raw_value: str | None) -> int | None:
        if raw_value is None:
            return None
        value = raw_value.strip().replace("#", "")
        if not value:
            return None
        if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
            raise ValueError("Use formato HEX de 6 dígitos, como #FFAA00.")
        return int(value, 16)

    def _build_role_color_kwargs(self, guild: discord.Guild, primary: str | None, secondary: str | None = None) -> dict:
        p = self._parse_hex_color(primary)
        s = self._parse_hex_color(secondary)

        if p is None and s is not None:
            raise ValueError("Informe a cor primária para usar gradiente.")

        if s is not None and "ENHANCED_ROLE_COLORS" not in guild.features:
            raise ValueError("Este servidor não possui suporte a gradiente de cargos.")

        kwargs = {}
        if p is not None:
            kwargs["color"] = discord.Color(p)
        if s is not None:
            kwargs["secondary_color"] = discord.Color(s)
        return kwargs



    async def enviar_log(self, g, t, f, c=discord.Color.blue()):
        ch = g.get_channel(LOG_CARGOS_ID)
        if ch:
            e = discord.Embed(title=t, color=c, timestamp=datetime.now())
            for n,v in f: e.add_field(name=n, value=v, inline=False)
            await ch.send(embed=e)


    async def add_members_bulk(self, g, r, s):
        if not s: return 0
        c = 0

        ids = set(re.findall(r"\d+", s))
        for i in ids:
            m = g.get_member(int(i))
            if m:
                try: await m.add_roles(r); c+=1
                except: pass
        return c

    async def build_lista_groups(self, guild: discord.Guild) -> list[tuple[str, list[tuple[str, str]]]]:
        try:
            return await self._build_lista_groups_from_api(guild)
        except discord.HTTPException:
            return self._build_lista_groups_from_cache(guild)

    async def _build_lista_groups_from_api(self, guild: discord.Guild) -> list[tuple[str, list[tuple[str, str]]]]:
        target_role_ids = {role_id for role_id, _label in LISTA_MODERATION_ROLES}
        members_by_role = {role_id: {} for role_id in target_role_ids}
        after = 0
        while True:
            route = Route("GET", "/guilds/{guild_id}/members", guild_id=guild.id)
            members = await self.bot.http.request(route, params={"limit": 1000, "after": after})
            if not members:
                break

            for member_data in members:
                user = member_data.get("user") or {}
                user_id = int(user.get("id", 0) or 0)
                if not user_id:
                    continue

                member_role_ids = {int(role_id) for role_id in member_data.get("roles", [])}
                display_name = None
                matched_role_ids = member_role_ids.intersection(members_by_role)
                if matched_role_ids:
                    display_name = member_data.get("nick") or user.get("global_name") or user.get("username") or str(user_id)
                for role_id in matched_role_ids:
                    members_by_role[role_id][user_id] = display_name

            if len(members) < 1000:
                break
            after = int((members[-1].get("user") or {}).get("id", after) or after)

        return self._format_lista_groups(members_by_role)

    def _build_lista_groups_from_cache(self, guild: discord.Guild) -> list[tuple[str, list[tuple[str, str]]]]:
        members_by_role = {role_id: {} for role_id, _label in LISTA_MODERATION_ROLES}
        for role_id, _label in LISTA_MODERATION_ROLES:
            role = guild.get_role(role_id)
            if not role:
                continue
            for member in role.members:
                members_by_role[role_id][member.id] = member.display_name

        return self._format_lista_groups(members_by_role)

    def _format_lista_groups(self, members_by_role: dict[int, dict[int, str]]) -> list[tuple[str, list[tuple[str, str]]]]:
        groups = []
        seen_user_ids = set()
        for role_id, label in LISTA_MODERATION_ROLES:
            members = []
            for user_id, display_name in sorted(
                members_by_role.get(role_id, {}).items(),
                key=lambda item: (str(item[1]).lower(), item[0]),
            ):
                if user_id in seen_user_ids:
                    continue
                seen_user_ids.add(user_id)
                members.append((str(display_name), f"sb!u <@{user_id}>"))
            groups.append((label, members))
        return groups

    def format_lista_member_name(self, index: int, display_name: str) -> str:
        clean_name = " ".join(str(display_name).split()) or "Sem nome"
        max_name_length = 90
        if len(clean_name) > max_name_length:
            clean_name = clean_name[: max_name_length - 1].rstrip() + "..."
        return f"{index:02d}. {clean_name}"


    @app_commands.command(name="limpar", description="Limpa mensagens do chat.")
    @check_owner_or_perm(manage_messages=True)
    async def limpar(self, it, quantidade: int):
        from .commands.limpar_command import execute

        await execute(self, it, quantidade)


    @app_commands.command(name="lock", description="Tranca o canal para o cargo @everyone.")
    @check_owner_or_perm(manage_channels=True)
    async def lock(self, it):
        from .commands.lock_command import execute

        await execute(self, it)


    @app_commands.command(name="unlock", description="Destranca o canal para o cargo @everyone.")
    @check_owner_or_perm(manage_channels=True)
    async def unlock(self, it):
        from .commands.unlock_command import execute

        await execute(self, it)


    @app_commands.command(name="addcargo", description="Adiciona um cargo a um usuário.")
    @check_owner_or_perm(manage_roles=True)
    async def addcargo(self, it: discord.Interaction, usuario: discord.Member, cargo: discord.Role):
        from .commands.addcargo_command import execute

        await execute(self, it, usuario, cargo)


    @app_commands.command(name="cargopng", description="Cria um cargo com ícone (PNG) e adiciona membros.")
    @app_commands.describe(
        cor_hex="Cor primária em HEX (ex: #FFAA00)",
        cor_secundaria="Cor secundária em HEX para gradiente (opcional)",
    )
    @check_owner_or_perm(manage_roles=True)
    async def cargopng(self, it, nome: str, imagem: discord.Attachment, cor_hex: str=None, cor_secundaria: str=None, membros: str=None):
        from .commands.cargopng_command import execute

        await execute(self, it, nome, imagem, cor_hex, cor_secundaria, membros)


    @app_commands.command(name="seticon", description="Altera o ícone de um cargo existente.")
    @check_owner_or_perm(manage_roles=True)
    async def seticon(self, it, cargo: discord.Role, imagem: discord.Attachment):
        from .commands.seticon_command import execute

        await execute(self, it, cargo, imagem)


    @app_commands.command(name="migrar_roles", description="Migrar dados JSON antigos para o DB (Admin).")
    @check_owner_or_perm(administrator=True)
    async def migrar_roles(self, it):
        from .commands.migrar_roles_command import execute

        await execute(self, it)


    @app_commands.command(name="lista", description="Gera lista sb!u dos moderadores e moderadores senior.")
    @check_owner_or_perm(administrator=True)
    async def lista(self, it: discord.Interaction):
        from .commands.lista_command import execute

        await execute(self, it)

async def setup(bot):
    await bot.add_cog(Moderation(bot))
