from __future__ import annotations

from collections import Counter

import discord

from .common import cr_embed, fmt_int, fmt_tag


async def semanal(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    docs = await self.get_linked_accounts(interaction.guild_id)
    players = [doc.get("last_profile") for doc in docs if doc.get("last_profile")]
    players_by_trophies = sorted(players, key=lambda p: int(p.get("trophies", 0) or 0), reverse=True)
    players_by_wins = sorted(players, key=lambda p: int(p.get("wins", 0) or 0), reverse=True)
    clan_counter = Counter()
    for player in players:
        clan = player.get("clan") or {}
        if clan.get("name"):
            clan_counter[clan["name"]] += 1

    embed = cr_embed("Resumo semanal Clash Royale")
    embed.description = f"Base atual: `{len(players)}` perfis vinculados com cache."
    embed.add_field(
        name="Top trofeus",
        value="\n".join(f"`#{idx}` **{p.get('name')}** - {fmt_int(p.get('trophies'))}" for idx, p in enumerate(players_by_trophies[:5], 1)) or "-",
        inline=True,
    )
    embed.add_field(
        name="Top vitorias",
        value="\n".join(f"`#{idx}` **{p.get('name')}** - {fmt_int(p.get('wins'))}" for idx, p in enumerate(players_by_wins[:5], 1)) or "-",
        inline=True,
    )
    embed.add_field(
        name="Clas populares",
        value="\n".join(f"`#{idx}` **{name}** - `{count}`" for idx, (name, count) in enumerate(clan_counter.most_common(5), 1)) or "-",
        inline=False,
    )
    await interaction.followup.send(embed=embed)
