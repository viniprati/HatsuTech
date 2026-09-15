import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord import ui
import datetime
import logging
import re


from database import guilds_col


from utils import ensure_guild_interaction, get_brt_keys, has_full_access
try:
    from config import CHAT_COUNT_CHANNEL_ID
except ImportError:
    CHAT_COUNT_CHANNEL_ID = 1117559464363573358


XP_PER_MSG = 1
MSG_COOLDOWN = 5
XP_PER_VOICE_TICK = 1
VOICE_TICK_SECONDS = 10
GUILD_XP_FROM_ECONOMY_ONLY = True
GUILD_PERIOD_STATS_TEMPLATE = {"message_xp": 0, "voice_xp": 0}
GUILD_MONTHLY_BOOST_TIERS = [
    (100_000, 25),
    (90_000, 20),
    (75_000, 15),
    (60_000, 10),
    (50_000, 5),
]

log = logging.getLogger(__name__)





def is_admin_or_owner():
    """
    Check personalizado: Permite a execução se o usuário for o dono do bot
    OU se tiver permissão de Administrador no servidor.
    """
    def predicate(interaction: discord.Interaction) -> bool:

        if has_full_access(interaction.user):
            return True

        if interaction.permissions.administrator:
            return True
        return False
    return app_commands.check(predicate)





class GuildInviteView(ui.View):
    def __init__(self, cog, guild_data, target_user, inviter):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_data = guild_data
        self.target_user = target_user
        self.inviter = inviter
        self.value = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content=f"⏰ O convite para **{self.guild_data['name']}** expirou.", view=self)
        except: pass

    @ui.button(label="Aceitar", style=discord.ButtonStyle.green, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.target_user.id:
            return await interaction.response.send_message("Este convite não é para você.", ephemeral=True)

        current_guild = guilds_col.find_one({"_id": self.guild_data["_id"]})
        if not current_guild:
            return await interaction.response.send_message("❌ Esta guilda não existe mais.", ephemeral=True)

        active_members = await self.cog.get_active_member_records(interaction.guild, current_guild)
        if len(active_members) >= 10:
            return await interaction.response.send_message("❌ A guilda lotou nesses 3 minutos!", ephemeral=True)

        if guilds_col.find_one({"members.user_id": interaction.user.id}):
            return await interaction.response.send_message("❌ Você já está em uma guilda.", ephemeral=True)

        new_member = {
            "user_id": interaction.user.id,
            "joined_at": datetime.datetime.now(),
            "xp": 0,
            "msg_count": 0,
            "voice_minutes": 0,
            "voice_seconds": 0,
            "message_xp": 0,
            "voice_xp": 0,
        }

        guilds_col.update_one(
            {"_id": self.guild_data["_id"]},
            {"$push": {"members": new_member}}
        )

        self.value = True
        for child in self.children: child.disabled = True

        await interaction.response.edit_message(content=f"🎉 **{interaction.user.mention}** agora faz parte da guilda **{current_guild['name']}**!", view=self)

    @ui.button(label="Recusar", style=discord.ButtonStyle.red, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.target_user.id:
            return await interaction.response.send_message("Não é para você.", ephemeral=True)

        self.value = False
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"❌ **{interaction.user.name}** recusou o convite.", view=self)

class GuildConfirmDelete(ui.View):
    def __init__(self, guild_id, author_id: int):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente quem abriu esta confirmação pode usar estes botões.", ephemeral=True)
            return False
        return True

    @ui.button(label="Sim, Deletar Guilda", style=discord.ButtonStyle.danger, emoji="💣")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        guilds_col.delete_one({"_id": self.guild_id})
        await interaction.response.edit_message(content="🗑️ **Guilda deletada com sucesso!**", view=None, embed=None)

    @ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="❌ Ação cancelada.", view=None, embed=None)



class GuildIconSelect(ui.Select):
    def __init__(self, guild_id):
        self.guild_id = guild_id
        options = [
            discord.SelectOption(label="Combate", emoji="⚔️", description="Guilda focada em luta"),
            discord.SelectOption(label="Defesa", emoji="🛡️", description="Guilda protetora"),
            discord.SelectOption(label="Realeza", emoji="👑", description="Guilda de elite"),
            discord.SelectOption(label="Magia", emoji="🔮", description="Guilda mística"),
            discord.SelectOption(label="Sombrio", emoji="💀", description="Guilda das trevas"),
            discord.SelectOption(label="Natureza", emoji="🌿", description="Guilda da floresta"),
            discord.SelectOption(label="Fogo", emoji="🔥", description="Elemento Fogo"),
            discord.SelectOption(label="Gelo", emoji="❄️", description="Elemento Gelo"),
            discord.SelectOption(label="Trovão", emoji="⚡", description="Elemento Trovão"),
            discord.SelectOption(label="Sorte", emoji="🍀", description="Jogos e Sorte")
        ]
        super().__init__(placeholder="Selecione um ícone padrão...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        chosen_emoji = self.values[0]
        guilds_col.update_one({"_id": self.guild_id}, {"$set": {"emoji": chosen_emoji}})
        await interaction.response.edit_message(content=f"✅ O ícone da guilda foi atualizado para {chosen_emoji}!", view=None, embed=None)

class GuildIconCustomModal(ui.Modal, title="Ícone Personalizado"):
    emoji_input = ui.TextInput(label="Cole o Emoji aqui", placeholder="<:emoji:123...> ou 🛡️", required=True, max_length=50)

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        novo_emoji = self.emoji_input.value.strip()

        is_custom = re.match(r'<a?:.+:(\d+)>', novo_emoji)

        if is_custom:
            emoji_id = int(is_custom.group(1))
            emoji_obj = interaction.guild.get_emoji(emoji_id)
            if not emoji_obj:
                return await interaction.response.send_message("❌ Esse emoji deve pertencer a este servidor (o bot precisa vê-lo).", ephemeral=True)

        guilds_col.update_one({"_id": self.guild_id}, {"$set": {"emoji": novo_emoji}})
        await interaction.response.send_message(f"✅ Ícone personalizado atualizado para {novo_emoji}!", ephemeral=True)

class GuildIconView(ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.add_item(GuildIconSelect(guild_id))

    @ui.button(label="Usar Emoji Personalizado", style=discord.ButtonStyle.secondary, emoji="✏️")
    async def custom_emoji(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(GuildIconCustomModal(self.guild_id))



class GuildAdminPagination(ui.View):
    def __init__(self, guild_list):
        super().__init__(timeout=180)
        self.guild_list = guild_list
        self.current_page = 0
        self.items_per_page = 10
        self.total_pages = (len(guild_list) - 1) // self.items_per_page + 1

    def create_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        current_data = self.guild_list[start:end]

        embed = discord.Embed(
            title="🛡️ Painel Administrativo de Guildas",
            description=f"Total de Guildas: **{len(self.guild_list)}**\n\n",
            color=discord.Color.dark_purple()
        )

        text = ""
        for i, guild in enumerate(current_data, start + 1):
            emoji = guild.get('emoji', '❓')
            name = guild.get('name', 'Sem Nome')
            member_count = guild.get("_active_member_count", 0)
            xp = guild.get("total_xp", 0)
            leader_text = guild.get("_leader_text", "Líder ausente")

            text += f"`#{i:02d}` {emoji} **{name}**\n"
            text += f"└ 👑 Líder: {leader_text}\n"
            text += f"└ 👥 Membros ativos: `{member_count}` | ✨ XP total: `{xp:,}`\n"
            text += f"└ 🆔 ID: `{guild['_id']}`\n\n"

        embed.description += text
        embed.set_footer(text=f"Página {self.current_page + 1}/{self.total_pages}")
        return embed

    async def update_buttons(self, interaction):
        self.prev_button.disabled = (self.current_page == 0)
        self.next_button.disabled = (self.current_page == self.total_pages - 1)
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @ui.button(label="◀️ Anterior", style=discord.ButtonStyle.primary, disabled=True)
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page -= 1
        await self.update_buttons(interaction)

    @ui.button(label="Próximo ▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page += 1
        await self.update_buttons(interaction)





class GuildSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cd = commands.CooldownMapping.from_cooldown(1, MSG_COOLDOWN, commands.BucketType.user)
        if not GUILD_XP_FROM_ECONOMY_ONLY:
            self.voice_xp_loop.start()

    def cog_unload(self):
        if self.voice_xp_loop.is_running():
            self.voice_xp_loop.cancel()


    def get_user_guild(self, user_id):
        return guilds_col.find_one({"members.user_id": user_id})

    async def get_guild_member_safe(self, guild: discord.Guild, user_id):
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return None

        member = guild.get_member(user_id)
        if member:
            return member

        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def get_active_member_records(self, guild: discord.Guild, guild_data: dict) -> list[tuple[dict, discord.Member]]:
        active = []
        for record in guild_data.get("members", []):
            member = await self.get_guild_member_safe(guild, record.get("user_id"))
            if member is not None:
                active.append((record, member))
        return active

    def _period_stat_paths(self) -> dict:
        keys = get_brt_keys()
        return {
            "weekly": ("stats_weekly", keys["week"]),
            "monthly": ("stats_monthly", keys["month"]),
        }

    def _reset_period_stats_if_needed(self, guild_doc: dict | None) -> dict:
        if not guild_doc:
            return {}
        sets = {}
        for field, key in self._period_stat_paths().values():
            stats = guild_doc.get(field) or {}
            if stats.get("key") != key:
                sets[field] = {"key": key, **GUILD_PERIOD_STATS_TEMPLATE}
        return sets

    def _build_guild_xp_update(self, guild_doc: dict | None, source: str, xp_amount: int, member_inc: dict) -> dict:
        inc = {
            "members.$.xp": xp_amount,
            "total_xp": xp_amount,
            **member_inc,
        }
        if source == "message":
            inc["total_message_xp"] = xp_amount
        elif source == "voice":
            inc["total_voice_xp"] = xp_amount

        for field, _key in self._period_stat_paths().values():
            inc[f"{field}.{source}_xp"] = xp_amount

        return {"$inc": inc}

    def monthly_xp(self, guild_data: dict | None) -> int:
        if not guild_data:
            return 0
        field, key = self._period_stat_paths()["monthly"]
        stats = (guild_data.get(field) or {})
        if stats.get("key") != key:
            return 0
        return int(stats.get("message_xp", 0)) + int(stats.get("voice_xp", 0))

    def monthly_boost_percent(self, monthly_xp: int) -> int:
        for threshold, percent in GUILD_MONTHLY_BOOST_TIERS:
            if monthly_xp >= threshold:
                return percent
        return 0

    def next_monthly_boost_tier(self, monthly_xp: int) -> tuple[int, int] | None:
        for threshold, percent in reversed(GUILD_MONTHLY_BOOST_TIERS):
            if monthly_xp < threshold:
                return threshold, percent
        return None

    def format_monthly_boost_summary(self, guild_data: dict | None) -> str:
        monthly_xp = self.monthly_xp(guild_data)
        percent = self.monthly_boost_percent(monthly_xp)
        next_tier = self.next_monthly_boost_tier(monthly_xp)
        lines = [
            f"Boost de Eter pessoal: `+{percent}%`",
        ]
        if next_tier:
            threshold, next_percent = next_tier
            missing = max(0, threshold - monthly_xp)
            lines.append(
                f"Proxima meta: `{threshold:,}` XP (`+{next_percent}%`) - faltam `{missing:,}`".replace(",", ".")
            )
        else:
            lines.append("Meta maxima mensal alcancada.")
        return "\n".join(lines)

    def get_member_guild_boost_info(self, member: discord.Member | None) -> dict:
        if member is None:
            return {"percent": 0, "guild": None, "monthly_xp": 0, "next_tier": None}
        guild_data = self.get_user_guild(member.id)
        if not guild_data:
            return {"percent": 0, "guild": None, "monthly_xp": 0, "next_tier": None}
        guild_data = self._ensure_current_period_stats(guild_data)
        monthly_xp = self.monthly_xp(guild_data)
        return {
            "percent": self.monthly_boost_percent(monthly_xp),
            "guild": guild_data,
            "monthly_xp": monthly_xp,
            "next_tier": self.next_monthly_boost_tier(monthly_xp),
        }

    def credit_activity_xp(self, member: discord.Member, source: str, xp_amount: int = 1) -> dict:
        if member.bot or source not in {"message", "voice"} or xp_amount <= 0:
            return {"credited": False, "percent": 0, "guild": None, "monthly_xp": 0}

        guild_data = guilds_col.find_one({"members.user_id": member.id})
        if not guild_data:
            return {"credited": False, "percent": 0, "guild": None, "monthly_xp": 0}

        guild_data = self._ensure_current_period_stats(guild_data)
        previous_percent = self.monthly_boost_percent(self.monthly_xp(guild_data))
        member_inc = {
            "members.$.message_xp": xp_amount,
            "members.$.msg_count": 1,
        } if source == "message" else {
            "members.$.voice_xp": xp_amount,
            "members.$.voice_seconds": VOICE_TICK_SECONDS,
        }

        result = guilds_col.update_one(
            {"_id": guild_data["_id"], "members.user_id": member.id},
            self._build_guild_xp_update(guild_data, source, xp_amount, member_inc),
        )
        if not getattr(result, "acknowledged", False):
            log.warning(
                "guild_xp_credit_failed guild_id=%s member_id=%s source=%s amount=%s",
                guild_data.get("_id"),
                member.id,
                source,
                xp_amount,
            )
            return {"credited": False, "percent": 0, "guild": guild_data, "monthly_xp": self.monthly_xp(guild_data)}

        updated = guilds_col.find_one({"_id": guild_data["_id"]}) or guild_data
        monthly_xp = self.monthly_xp(updated)
        current_percent = self.monthly_boost_percent(monthly_xp)
        if current_percent != previous_percent:
            log.info(
                "guild_monthly_boost_tier_changed guild_id=%s guild_name=%s monthly_xp=%s previous_percent=%s current_percent=%s",
                updated.get("_id"),
                updated.get("name"),
                monthly_xp,
                previous_percent,
                current_percent,
            )
        return {
            "credited": True,
            "percent": current_percent,
            "guild": updated,
            "monthly_xp": monthly_xp,
            "next_tier": self.next_monthly_boost_tier(monthly_xp),
        }

    def _ensure_current_period_stats(self, guild_data: dict) -> dict:
        sets = self._reset_period_stats_if_needed(guild_data)
        if sets:
            guilds_col.update_one({"_id": guild_data["_id"]}, {"$set": sets})
            guild_data = {**guild_data, **sets}
        return guild_data

    def _ranking_value(self, guild_data: dict, periodo: str, tipo: str) -> int:
        if periodo == "global":
            if tipo == "message":
                return int(guild_data.get("total_message_xp", 0))
            if tipo == "voice":
                return int(guild_data.get("total_voice_xp", 0))
            return int(guild_data.get("total_xp", 0))

        field, key = self._period_stat_paths()[periodo]
        stats = guild_data.get(field) or {}
        if stats.get("key") != key:
            return 0
        if tipo == "message":
            return int(stats.get("message_xp", 0))
        if tipo == "voice":
            return int(stats.get("voice_xp", 0))
        return int(stats.get("message_xp", 0)) + int(stats.get("voice_xp", 0))

    async def build_guild_runtime_view(self, guild: discord.Guild, guild_data: dict) -> dict:
        active_records = await self.get_active_member_records(guild, guild_data)
        leader = await self.get_guild_member_safe(guild, guild_data.get("leader_id"))

        data = dict(guild_data)
        data["_active_records"] = active_records
        data["_active_member_count"] = len(active_records)
        data["_leader_member"] = leader
        data["_leader_text"] = leader.mention if leader else "Líder ausente"
        return data



    guilda = app_commands.Group(name="guilda", description="Sistema de Guildas")

    @guilda.command(name="criar", description="Cria uma nova guilda (Você será o líder).")
    async def criar(self, it: discord.Interaction, nome: str, emoji: str):
        from .commands.criar_command import execute

        await execute(self, it, nome, emoji)

    @guilda.command(name="painel", description="Mostra as informações, membros e stats da guilda.")
    async def painel(self, it: discord.Interaction, usuario: discord.Member = None):
        from .commands.painel_command import execute

        await execute(self, it, usuario)

    @guilda.command(name="convidar", description="Convida alguém para sua guilda (Líder apenas).")
    async def convidar(self, it: discord.Interaction, usuario: discord.Member):
        from .commands.convidar_command import execute

        await execute(self, it, usuario)

    @guilda.command(name="sair", description="Sai da guilda atual.")
    async def sair(self, it: discord.Interaction):
        from .commands.sair_command import execute

        await execute(self, it)

    @guilda.command(name="deletar", description="Exclui sua guilda permanentemente (Líder apenas).")
    async def deletar(self, it: discord.Interaction):
        from .commands.deletar_command import execute

        await execute(self, it)


    @guilda.command(name="editar_nome", description="Edita apenas o nome da guilda (Líder apenas).")
    async def editar_nome(self, it: discord.Interaction, novo_nome: str):
        from .commands.editar_nome_command import execute

        await execute(self, it, novo_nome)


    @guilda.command(name="editar_emoji", description="Abre o menu para alterar o ícone da guilda (Líder apenas).")
    async def editar_emoji(self, it: discord.Interaction):
        from .commands.editar_emoji_command import execute

        await execute(self, it)

    @guilda.command(name="ranking", description="Top 10 Guildas por período e tipo de pontuação.")
    @app_commands.describe(periodo="Período do ranking", tipo="Tipo de pontuação")
    @app_commands.choices(
        periodo=[
            app_commands.Choice(name="🈷️ Mensal", value="monthly"),
            app_commands.Choice(name="🗓️ Semanal", value="weekly"),
            app_commands.Choice(name="🏆 Geral", value="global"),
        ],
        tipo=[
            app_commands.Choice(name="✨ Soma geral", value="total"),
            app_commands.Choice(name="💬 Mensagens", value="message"),
            app_commands.Choice(name="🎙️ Call", value="voice"),
        ],
    )
    async def ranking(
        self,
        it: discord.Interaction,
        periodo: app_commands.Choice[str] = None,
        tipo: app_commands.Choice[str] = None,
    ):
        from .commands.ranking_command import execute

        await execute(self, it, periodo, tipo)

    @guilda.command(name="kick", description="Remove um membro (Líder apenas).")
    async def kick(self, it: discord.Interaction, membro: discord.Member):
        from .commands.kick_command import execute

        await execute(self, it, membro)



    @app_commands.command(name="admin_emoji", description="[ADMIN] Força a troca do emoji de uma guilda.")
    @app_commands.describe(alvo="Um membro que esteja na guilda", emoji="O novo emoji (Cole aqui)")
    @is_admin_or_owner()
    async def admin_emoji(self, it: discord.Interaction, alvo: discord.Member, emoji: str):
        from .commands.admin_emoji_command import execute

        await execute(self, it, alvo, emoji)

    @admin_emoji.error
    async def admin_emoji_error(self, it: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, (app_commands.CheckFailure, app_commands.MissingPermissions)):
            await it.response.send_message("🚫 Você precisa ser **Administrador** ou o **Dono do Bot**.", ephemeral=True)

    @app_commands.command(name="admin_guildas", description="[ADMIN] Painel com lista de todas as guildas.")
    @is_admin_or_owner()
    async def admin_guildas(self, it: discord.Interaction):
        from .commands.admin_guildas_command import execute

        await execute(self, it)

    @admin_guildas.error
    async def admin_guildas_error(self, it: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, (app_commands.CheckFailure, app_commands.MissingPermissions)):
            await it.response.send_message("🚫 Você precisa ser **Administrador** ou o **Dono do Bot**.", ephemeral=True)



    @app_commands.command(name="admin_force_delete", description="[ADMIN] Força a exclusão de uma guilda (Baseado em um membro dela).")
    @app_commands.describe(alvo="Qualquer membro que pertença à guilda que você quer apagar")
    @is_admin_or_owner()
    async def admin_force_delete(self, it: discord.Interaction, alvo: discord.Member):

        from .commands.admin_force_delete_command import execute

        await execute(self, it, alvo)

    @admin_force_delete.error
    async def admin_force_delete_error(self, it: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, (app_commands.CheckFailure, app_commands.MissingPermissions)):
            await it.response.send_message("🚫 **Acesso Negado:** Apenas Administradores ou o Dono do Bot podem forçar a exclusão de guildas.", ephemeral=True)



    @commands.Cog.listener()
    async def on_message(self, message):
        if GUILD_XP_FROM_ECONOMY_ONLY:
            return
        if message.author.bot or not message.guild: return
        if message.channel.id != CHAT_COUNT_CHANNEL_ID: return

        if len(message.content) <= 7: return
        clean_text = message.content.lower().replace(" ", "")
        if len(set(clean_text)) <= 3: return

        bucket = self._cd.get_bucket(message)
        retry_after = bucket.update_rate_limit()
        if retry_after: return

        guild_data = guilds_col.find_one({"members.user_id": message.author.id})
        if not guild_data:
            return
        guild_data = self._ensure_current_period_stats(guild_data)

        guilds_col.update_one(
            {"_id": guild_data["_id"], "members.user_id": message.author.id},
            self._build_guild_xp_update(
                guild_data,
                "message",
                XP_PER_MSG,
                {
                    "members.$.msg_count": 1,
                    "members.$.message_xp": XP_PER_MSG,
                },
            ),
        )

    @tasks.loop(seconds=VOICE_TICK_SECONDS)
    async def voice_xp_loop(self):
        if GUILD_XP_FROM_ECONOMY_ONLY:
            return
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                if len(vc.members) == 0: continue

                for member in vc.members:
                    if member.bot: continue

                    guild_data = guilds_col.find_one({"members.user_id": member.id})
                    if not guild_data:
                        continue
                    guild_data = self._ensure_current_period_stats(guild_data)

                    guilds_col.update_one(
                        {"_id": guild_data["_id"], "members.user_id": member.id},
                        self._build_guild_xp_update(
                            guild_data,
                            "voice",
                            XP_PER_VOICE_TICK,
                            {
                                "members.$.voice_seconds": VOICE_TICK_SECONDS,
                                "members.$.voice_xp": XP_PER_VOICE_TICK,
                            },
                        ),
                    )

    @voice_xp_loop.before_loop
    async def before_voice_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(GuildSystem(bot))
