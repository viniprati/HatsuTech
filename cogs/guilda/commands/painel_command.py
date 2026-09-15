from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, usuario: discord.Member = None):
    await it.response.defer()
    if not await ensure_guild_interaction(it, "o comando /guilda painel"):
        return

    target = usuario or it.user
    guild_data = self.get_user_guild(target.id)

    if not guild_data:
        return await it.followup.send("❌ Usuário não possui guilda.", ephemeral=True)

    all_guilds = [
        await self.build_guild_runtime_view(it.guild, g)
        for g in guilds_col.find()
    ]
    all_guilds.sort(key=lambda g: self._ranking_value(g, "monthly", "total"), reverse=True)
    rank = next((i for i, g in enumerate(all_guilds, 1) if g["_id"] == guild_data["_id"]), "N/A")

    runtime_data = await self.build_guild_runtime_view(it.guild, guild_data)
    members_sorted = sorted(runtime_data["_active_records"], key=lambda item: item[0].get("xp", 0), reverse=True)
    monthly_field, monthly_key = self._period_stat_paths()["monthly"]
    monthly_stats = runtime_data.get(monthly_field) or {}
    if monthly_stats.get("key") != monthly_key:
        monthly_stats = {}
    monthly_message_xp = int(monthly_stats.get("message_xp", 0))
    monthly_voice_xp = int(monthly_stats.get("voice_xp", 0))
    monthly_total_xp = monthly_message_xp + monthly_voice_xp

    desc = (
        f"🏆 **Rank Mensal:** #{rank}\n"
        f"✨ **XP Mensal:** {monthly_total_xp:,}\n"
        f"💬 **Mensagens:** {monthly_message_xp:,} XP\n"
        f"🎙️ **Call:** {monthly_voice_xp:,} XP\n"
        f"{self.format_monthly_boost_summary(runtime_data)}\n"
        f"📚 **XP Histórico:** {runtime_data.get('total_xp', 0):,}\n"
        f"👑 **Líder:** {runtime_data['_leader_text']}\n\n"
    ).replace(",", ".")
    desc += "**📊 Membros & Contribuição:**\n"

    for i, (m, member) in enumerate(members_sorted, 1):
        uid = m['user_id']
        xp = m.get('xp', 0)
        voice_seconds = int(m.get("voice_seconds", 0) or 0)
        if voice_seconds <= 0:
            voice_seconds = int(m.get('voice_minutes', 0) or 0) * 60
        msgs = m.get('msg_count', 0)

        total_minutes = voice_seconds // 60
        hours, minutes = divmod(total_minutes, 60)
        time_str = f"{hours}h{minutes}m" if hours > 0 else f"{minutes}m"

        line = f"`#{i:02d}` {member.mention}"
        if uid == guild_data['leader_id']:
            line += " 👑"

        stats = f"└ 🗣️ `{msgs} msgs` | 🎙️ `{time_str}` | ✨ `{xp} XP`"
        desc += f"{line}\n{stats}\n"

    if not members_sorted:
        desc += "Nenhum membro ativo encontrado.\n"

    embed = discord.Embed(
        title=f"{guild_data['emoji']} {guild_data['name']}",
        description=desc,
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"Membros ativos: {len(members_sorted)}/10")

    await it.followup.send(embed=embed)
