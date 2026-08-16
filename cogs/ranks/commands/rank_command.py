from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, periodo: Choice[str] = None):
    await it.response.defer()
    mode = periodo.value if periodo else "global"
    keys = get_brt_keys()

    if mode == "global":
        sort_target = "count"
        query = {}
        display_val = "count"
        title_suf = "Global 🌍"
    else:
        key_map = {"daily": "day", "weekly": "week", "monthly": "month"}
        current_key = keys[key_map[mode]]
        query = {f"stats_{mode}.key": current_key}
        sort_target = f"stats_{mode}.value"
        display_val = sort_target
        title_suf = f"{periodo.name}"

    lb = await asyncio.to_thread(lambda: list(msg_col.find(query).sort(sort_target, -1).limit(50)))
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
        if float(val) <= 0:
            continue
        i = len(lines) + 1
        lines.append(f"**{i}.** {member.mention} — `{fmt_rank_score(val)} pts`")
        if len(lines) >= 10:
            break

    desc = "\n".join(lines) if lines else "🦗 Nenhum membro atual pontuou neste período ainda."
    embed = discord.Embed(title=f"🏆 Rank Chat - {title_suf}", description=desc, color=discord.Color.purple())
    embed.set_footer(text="Reset automático às 00:00 (Brasília)")
    await it.followup.send(embed=embed)
