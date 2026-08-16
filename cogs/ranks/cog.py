import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
import asyncio
import time
import re
import platform
from datetime import datetime, timezone

from database import msg_col, voice_col, event_col, vip_col

from utils import AntiSpamSystem, check_owner_or_perm, build_update_pipeline, get_brt_keys

try:
    from config import CHAT_COUNT_CHANNEL_ID
except ImportError:
    CHAT_COUNT_CHANNEL_ID = 1117559464363573358

from discord.app_commands import Choice

MONARCH_VIP_ID = 1351596017631494195
MUGETSU_VIP_ID = 1121511055059861524
BERSERK_VIP_ID = 999723165225857074
BOOSTER_PREMIUM_ROLE_ID = 764698895254159391
VIP_SCORE_BONUSES = {
    BERSERK_VIP_ID: 5,
    MUGETSU_VIP_ID: 10,
    MONARCH_VIP_ID: 15,
}


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


def fmt_rank_score(value: float) -> str:
    return f"{int(float(value or 0)):,}".replace(",", ".")

class AdminDashboardView(ui.View):
    def __init__(self, bot, cog):
        super().__init__(timeout=300)
        self.bot = bot
        self.cog = cog
        self.snapshot = None
        self.snapshot_at = None

    def _sum_daily_metric(self, col, day_key: str) -> int:
        pipeline = [
            {"$match": {"stats_daily.key": day_key}},
            {"$group": {"_id": None, "total": {"$sum": "$stats_daily.value"}}}
        ]
        res = list(col.aggregate(pipeline))
        return int(res[0]['total']) if res else 0

    def _sum_global_metric(self, col, field: str) -> int:
        pipeline = [{"$group": {"_id": None, "total": {"$sum": f"${field}"}}}]
        res = list(col.aggregate(pipeline))
        return int(res[0]['total']) if res else 0

    def _fmt_duration(self, seconds: float) -> str:
        seconds = int(max(seconds, 0))
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"

    def _count_server_tag_users(self, guild: discord.Guild) -> int:
        count = 0
        for member in guild.members:
            try:
                pg = member.primary_guild
                if pg and pg.id == guild.id:
                    count += 1
            except Exception:
                continue
        return count

    async def refresh_snapshot(self, guild: discord.Guild):
        keys = get_brt_keys()
        day_key = keys["day"]

        chat_users = set(await asyncio.to_thread(msg_col.distinct, "_id", {"stats_daily.key": day_key}))
        voice_users = set(await asyncio.to_thread(voice_col.distinct, "_id", {"stats_daily.key": day_key}))
        active_today = len(chat_users | voice_users)

        event_data = await asyncio.to_thread(event_col.find_one, {"_id": "config"}) or {}

        msgs_today = await asyncio.to_thread(self._sum_daily_metric, msg_col, day_key)
        msgs_total = await asyncio.to_thread(self._sum_global_metric, msg_col, "count")
        voice_today = await asyncio.to_thread(self._sum_daily_metric, voice_col, day_key)
        voice_total = await asyncio.to_thread(self._sum_global_metric, voice_col, "time")
        top_chat_today = await asyncio.to_thread(msg_col.find_one, {"stats_daily.key": day_key}, sort=[("stats_daily.value", -1)])
        top_chat_global = await asyncio.to_thread(msg_col.find_one, {}, sort=[("count", -1)])
        top_voice_today = await asyncio.to_thread(voice_col.find_one, {"stats_daily.key": day_key}, sort=[("stats_daily.value", -1)])
        top_voice_global = await asyncio.to_thread(voice_col.find_one, {}, sort=[("time", -1)])

        self.snapshot = {
            "day_key": day_key,
            "active_today": active_today,
            "total_members": guild.member_count or 0,
            "server_tag_users": self._count_server_tag_users(guild),
            "msgs_today": msgs_today,
            "msgs_total": msgs_total,
            "voice_today": voice_today,
            "voice_total": voice_total,
            "top_chat_today": top_chat_today,
            "top_chat_global": top_chat_global,
            "top_voice_today": top_voice_today,
            "top_voice_global": top_voice_global,
            "event_active": bool(event_data.get("active", False)),
            "event_end_time": int(event_data["end_time"]) if event_data.get("end_time") else None,
            "event_channel_id": event_data.get("channel_id"),
            "event_participants": len((event_data.get("current_scores") or {}) if event_data.get("active") else (event_data.get("last_event_scores") or {})),
        }
        self.snapshot_at = datetime.now(timezone.utc)

    async def ensure_snapshot(self, guild: discord.Guild, force: bool = False):
        if force or self.snapshot is None or self.snapshot_at is None:
            await self.refresh_snapshot(guild)
            return
        if (datetime.now(timezone.utc) - self.snapshot_at).total_seconds() > 90:
            await self.refresh_snapshot(guild)

    @ui.button(label="📡 Sistema & Saúde", style=discord.ButtonStyle.primary, emoji="🖥️", row=0)
    async def sys_info(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_snapshot(interaction.guild)
        snap = self.snapshot
        g = interaction.guild
        online_count = sum(1 for m in g.members if m.status != discord.Status.offline)

        ping = round(self.bot.latency * 1000)
        uptime_delta = datetime.now() - self.cog.start_time
        uptime_str = str(uptime_delta).split('.')[0]
        total_members = snap["total_members"]
        active_today = snap["active_today"]
        engagement_rate = (active_today / total_members * 100) if total_members else 0
        tag_users = snap["server_tag_users"]
        tag_rate = (tag_users / total_members * 100) if total_members else 0

        e = discord.Embed(title="🖥️ Sistema e Saúde", color=0x2b2d31, timestamp=datetime.now())
        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        e.add_field(name="🤖 Bot Status", value=f"Ping: `{ping}ms`\nUptime: `{uptime_str}`\nPython: `{platform.python_version()}`", inline=True)
        e.add_field(name="👥 Membros", value=f"Total: `{total_members}`\nOnline: `{online_count}`\nNovos (24h): `{len([m for m in g.members if (datetime.now(timezone.utc) - m.joined_at).days < 1])}`", inline=True)
        e.add_field(name="📈 Engajamento Diário", value=f"Ativos Hoje: **{active_today}**\nTaxa: `{engagement_rate:.1f}%` dos membros", inline=True)
        e.add_field(name="🏷️ Tag do Servidor", value=f"Usando: **{tag_users}**\nTaxa: `{tag_rate:.1f}%`", inline=True)
        e.add_field(name="📦 Atualização", value=f"Atualizado: `{self.snapshot_at.strftime('%H:%M:%S')}`", inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label="💬 Estatísticas Chat", style=discord.ButtonStyle.secondary, emoji="📝", row=0)
    async def chat_stats(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_snapshot(interaction.guild)
        snap = self.snapshot
        total_msgs = snap["msgs_total"]
        msgs_today = snap["msgs_today"]
        top_today = snap["top_chat_today"]
        avg_msg = (msgs_today / snap["active_today"]) if snap["active_today"] else 0

        e = discord.Embed(title="📝 Estatísticas de Chat", color=discord.Color.blurple())
        e.add_field(name="📅 Volume Hoje", value=f"**{msgs_today}** mensagens", inline=True)
        e.add_field(name="🌎 Volume Global", value=f"**{total_msgs:,}** mensagens".replace(",", "."), inline=True)
        e.add_field(name="📊 Média por Ativo", value=f"`{avg_msg:.1f}` msgs", inline=True)
        if top_today:
            e.add_field(name="🏆 Destaque do Dia (Chat)", value=f"<@{top_today['_id']}>\nEnvios: `{top_today['stats_daily']['value']}`", inline=False)
        else:
            e.add_field(name="🏆 Destaque do Dia", value="Ninguém falou hoje.", inline=False)
        top_global = snap["top_chat_global"]
        if top_global:
            e.add_field(name="🌟 Top Global", value=f"<@{top_global['_id']}>\nTotal: `{int(top_global.get('count', 0)):,}` msgs".replace(",", "."), inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label="🎙️ Estatísticas Voz", style=discord.ButtonStyle.secondary, emoji="🎧", row=0)
    async def voice_stats(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_snapshot(interaction.guild)
        snap = self.snapshot
        active_calls = len(self.cog.voice_sessions)
        total_secs = snap["voice_total"]
        today_secs = snap["voice_today"]

        e = discord.Embed(title="🎧 Estatísticas de Voz", color=discord.Color.green())
        e.add_field(name="🔴 Ao Vivo", value=f"**{active_calls}** usuários em call", inline=False)
        e.add_field(name="📅 Tempo Hoje", value=f"`{self._fmt_duration(today_secs)}`", inline=True)
        e.add_field(name="🌎 Tempo Total", value=f"`{self._fmt_duration(total_secs)}`", inline=True)

        max_ch = None
        max_c = 0
        for vc in interaction.guild.voice_channels:
            if len(vc.members) > max_c:
                max_c = len(vc.members)
                max_ch = vc
        if max_ch:
            e.add_field(name="🔥 Canal + Ativo", value=f"{max_ch.mention} ({max_c} on)", inline=False)
        top_global = snap["top_voice_global"]
        if top_global:
            e.add_field(name="🌟 Top Global Voz", value=f"<@{top_global['_id']}>\nTempo: `{self._fmt_duration(top_global.get('time', 0))}`", inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label="💎 Gestão VIP", style=discord.ButtonStyle.success, emoji="👑", row=1)
    async def vip_stats(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_snapshot(interaction.guild)
        total_db_vips = await asyncio.to_thread(vip_col.count_documents, {})
        g = interaction.guild
        monarchs = len(g.get_role(MONARCH_VIP_ID).members) if g.get_role(MONARCH_VIP_ID) else 0
        mugetsus = len(g.get_role(MUGETSU_VIP_ID).members) if g.get_role(MUGETSU_VIP_ID) else 0
        berserks = len(g.get_role(BERSERK_VIP_ID).members) if g.get_role(BERSERK_VIP_ID) else 0
        boosters = len(g.get_role(BOOSTER_PREMIUM_ROLE_ID).members) if g.get_role(BOOSTER_PREMIUM_ROLE_ID) else 0

        e = discord.Embed(title="💎 Gestão VIP", color=discord.Color.gold())
        e.add_field(name="📦 Base de Dados VIP", value=f"`{total_db_vips}` registros ativos", inline=False)
        e.add_field(name="👑 Monarchs", value=f"**{monarchs}**", inline=True)
        e.add_field(name="🌑 Mugetsus", value=f"**{mugetsus}**", inline=True)
        e.add_field(name="⚔️ Berserks", value=f"**{berserks}**", inline=True)
        e.add_field(name="🚀 Boosters", value=f"**{boosters}**", inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label="🚨 Eventos", style=discord.ButtonStyle.secondary, emoji="📌", row=1)
    async def event_stats(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_snapshot(interaction.guild)
        snap = self.snapshot

        e = discord.Embed(title="🚨 Eventos & Alertas", color=discord.Color.orange())
        if snap["event_active"]:
            e.add_field(name="Status", value="🟢 Evento em andamento", inline=True)
            if snap["event_end_time"]:
                e.add_field(name="Encerramento", value=f"<t:{snap['event_end_time']}:R>", inline=True)
            else:
                e.add_field(name="Encerramento", value="Sem duração definida", inline=True)
            canal = f"<#{snap['event_channel_id']}>" if snap["event_channel_id"] else "Todos os canais"
            e.add_field(name="Canal", value=canal, inline=False)
            e.add_field(name="Participantes", value=f"`{snap['event_participants']}`", inline=True)
        else:
            e.add_field(name="Status", value="🔴 Nenhum evento ativo", inline=False)

        alerts = []
        total_members = snap["total_members"] or 1
        rate = (snap["active_today"] / total_members) * 100
        if rate < 5:
            alerts.append("Engajamento do dia abaixo de 5%.")
        if len(self.cog.voice_sessions) == 0:
            alerts.append("Sem usuários em call neste momento.")
        if not alerts:
            alerts.append("Nenhum alerta crítico.")
        e.add_field(name="Alertas", value="\n".join(f"- {a}" for a in alerts), inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @ui.button(label="🔄 Atualizar", style=discord.ButtonStyle.gray, row=2)
    async def refresh_panel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.ensure_snapshot(interaction.guild, force=True)
        await interaction.followup.send("✅ Painel atualizado com dados mais recentes.", ephemeral=True)


class RankSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_sessions = {}
        self.start_time = datetime.now()
        self.chat_spam_system = AntiSpamSystem()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        if message.channel.id != CHAT_COUNT_CHANNEL_ID:
            return
        if self.chat_spam_system.is_spamming((message.guild.id, message.author.id)):
            return

        uid = str(message.author.id)
        bonus_percent = get_member_score_bonus_percent(message.author)
        doc = await asyncio.to_thread(msg_col.find_one, {"_id": uid}) or {}
        remainders = doc.get("score_bonus_remainders") or {}
        gain, remainder = get_integer_bonus_gain(1, bonus_percent, remainders.get("chat", 0))
        await asyncio.to_thread(
            msg_col.update_one,
            {"_id": uid},
            build_update_pipeline("count", gain),
            upsert=True
        )
        if bonus_percent > 0:
            await asyncio.to_thread(
                msg_col.update_one,
                {"_id": uid},
                {"$set": {"score_bonus_remainders.chat": remainder}},
            )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        uid = str(member.id)
        if after.channel and not before.channel:
            self.voice_sessions[uid] = time.time()
        elif before.channel and not after.channel and uid in self.voice_sessions:
            dur = int(time.time() - self.voice_sessions.pop(uid))
            if dur > 5:
                bonus_percent = get_member_score_bonus_percent(member)
                doc = await asyncio.to_thread(voice_col.find_one, {"_id": uid}) or {}
                remainders = doc.get("score_bonus_remainders") or {}
                dur, remainder = get_integer_bonus_gain(dur, bonus_percent, remainders.get("voice", 0))
                await asyncio.to_thread(
                    voice_col.update_one,
                    {"_id": uid},
                    build_update_pipeline("time", dur),
                    upsert=True
                )
                if bonus_percent > 0:
                    await asyncio.to_thread(
                        voice_col.update_one,
                        {"_id": uid},
                        {"$set": {"score_bonus_remainders.voice": remainder}},
                    )

    @app_commands.command(name="rank", description="Ranking de Chat (Global, Diário, etc).")
    @app_commands.describe(periodo="Selecione o período do ranking")
    @app_commands.choices(periodo=[
        Choice(name="🏆 Global (Tudo)", value="global"),
        Choice(name="📅 Diário (Hoje)", value="daily"),
        Choice(name="🗓️ Semanal (Esta semana)", value="weekly"),
        Choice(name="🈷️ Mensal (Este mês)", value="monthly")
    ])
    async def rank(self, it: discord.Interaction, periodo: Choice[str] = None):
        from .commands.rank_command import execute

        await execute(self, it, periodo)

    @app_commands.command(name="voice_rank", description="Ranking de Voz.")
    @app_commands.describe(periodo="Selecione o período do ranking")
    @app_commands.choices(periodo=[
        Choice(name="🏆 Global (Tudo)", value="global"),
        Choice(name="📅 Diário (Hoje)", value="daily"),
        Choice(name="🗓️ Semanal (Esta semana)", value="weekly"),
        Choice(name="🈷️ Mensal (Este mês)", value="monthly")
    ])
    async def voice_rank(self, it: discord.Interaction, periodo: Choice[str] = None):
        from .commands.voice_rank_command import execute

        await execute(self, it, periodo)

    @app_commands.command(name="admin_stats", description="Painel Admin Completo (Ranks & Sistema).")
    @check_owner_or_perm(administrator=True)
    async def admin_stats(self, interaction: discord.Interaction):
        from .commands.admin_stats_command import execute

        await execute(self, interaction)

    @app_commands.command(name="evento_iniciar", description="Inicia um evento de contagem.")
    @check_owner_or_perm(administrator=True)
    async def evento_iniciar(self, it, duracao: str = None, canal: discord.TextChannel = None):
        from .commands.evento_iniciar_command import execute

        await execute(self, it, duracao, canal)

    @app_commands.command(name="evento2_iniciar", description="Inicia o evento 2 em um canal.")
    @check_owner_or_perm(administrator=True)
    async def evento2_iniciar(self, it, canal: discord.TextChannel, duracao: str = None):
        from .commands.evento2_iniciar_command import execute

        await execute(self, it, canal, duracao)

    @app_commands.command(name="evento_encerrar", description="Encerra o evento atual.")
    @check_owner_or_perm(administrator=True)
    async def evento_encerrar(self, it):
        from .commands.evento_encerrar_command import execute

        await execute(self, it)

    @app_commands.command(name="evento2_encerrar", description="Encerra o evento 2.")
    @check_owner_or_perm(administrator=True)
    async def evento2_encerrar(self, it):
        from .commands.evento2_encerrar_command import execute

        await execute(self, it)

    @app_commands.command(name="topevento", description="Ranking do evento atual ou anterior.")
    async def topevento(self, it):
        from .commands.topevento_command import execute

        await execute(self, it)

    @app_commands.command(name="topevento2", description="Ranking do evento 2.")
    async def topevento2(self, it):
        from .commands.topevento2_command import execute

        await execute(self, it)

async def setup(bot):
    await bot.add_cog(RankSystem(bot))
