from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction):
    all_guilds = [
        await self.build_guild_runtime_view(it.guild, g)
        for g in guilds_col.find()
    ]
    all_guilds.sort(key=lambda g: g.get("total_xp", 0), reverse=True)

    if not all_guilds:
        return await it.response.send_message("❌ Nenhuma guilda foi criada ainda.", ephemeral=True)

    view = GuildAdminPagination(all_guilds)
    if view.total_pages <= 1:
        view.next_button.disabled = True

    embed = view.create_embed()
    await it.response.send_message(embed=embed, view=view, ephemeral=True)
