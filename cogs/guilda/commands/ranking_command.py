from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, periodo: app_commands.Choice[str] = None, tipo: app_commands.Choice[str] = None):
    period = periodo.value if periodo else "monthly"
    score_type = tipo.value if tipo else "total"

    guilds = [
        await self.build_guild_runtime_view(it.guild, g)
        for g in guilds_col.find()
    ]
    top_guilds = sorted(guilds, key=lambda g: self._ranking_value(g, period, score_type), reverse=True)[:10]

    period_labels = {
        "monthly": "Temporada mensal",
        "weekly": "Semanal",
        "global": "Histórico geral",
    }
    type_labels = {
        "total": "Soma geral",
        "message": "Mensagens",
        "voice": "Call",
    }
    type_emojis = {
        "total": "✨",
        "message": "💬",
        "voice": "🎙️",
    }

    desc = ""
    for i, g in enumerate(top_guilds, 1):
        score = self._ranking_value(g, period, score_type)
        if score <= 0 and period != "global":
            continue
        desc += (
            f"`#{i}` {g['emoji']} **{g['name']}** - "
            f"{type_emojis.get(score_type, '✨')} {score:,} XP | 👥 {g['_active_member_count']} ativos"
        )
        if period == "monthly" and score_type == "total":
            desc += f" | Boost `+{self.monthly_boost_percent(score)}%`"
        if g.get("_leader_member") is None:
            desc += " | 👑 líder ausente"
        desc += "\n"
    if not desc: desc = "Nenhuma guilda criada ainda."
    embed = discord.Embed(
        title=f"🏆 Ranking de Guildas - {period_labels.get(period, 'Geral')} / {type_labels.get(score_type, 'Soma geral')}",
        description=desc,
        color=discord.Color.gold(),
    )
    await it.response.send_message(embed=embed)
