from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, periodo: Choice[str] = None):
    await it.response.defer()
    if not await ensure_guild_interaction(it, "o comando /voice_rank"):
        return
    mode = periodo.value if periodo else "global"
    keys = get_brt_keys()

    if mode == "global":
        sort_target = "time"
        query = {}
        display_val = "time"
        title_suf = "Global 🌍"
    else:
        key_map = {"daily": "day", "weekly": "week", "monthly": "month"}
        current_key = keys[key_map[mode]]
        query = {f"stats_{mode}.key": current_key}
        sort_target = f"stats_{mode}.value"
        display_val = sort_target
        title_suf = f"{periodo.name}"

    lb = await asyncio.to_thread(lambda: list(voice_col.find(query).sort(sort_target, -1).limit(50)))
    lines = []
    for u in lb:
        try:
            uid = int(u["_id"])
        except (KeyError, TypeError, ValueError):
            continue
        member = it.guild.get_member(uid)
        if member is None:
            continue
        val = u
        try:
            if "." in display_val:
                for k in display_val.split("."): val = val[k]
            else:
                val = val[display_val]
        except: val = 0
        seconds = int(val)
        if seconds <= 0:
            continue
        h = seconds // 3600
        m = (seconds % 3600) // 60
        i = len(lines) + 1
        lines.append(f"**{i}.** {member.mention} — `{h}h {m}m`")
        if len(lines) >= 10:
            break

    desc = "\n".join(lines) if lines else "🦗 Nenhum membro atual ficou em call neste período."
    embed = discord.Embed(title=f"🎙️ Rank Voz - {title_suf}", description=desc, color=discord.Color.green())
    embed.set_footer(text="Reset automático às 00:00 (Brasília)")
    await it.followup.send(embed=embed)
