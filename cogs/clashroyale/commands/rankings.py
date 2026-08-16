from __future__ import annotations

from collections import Counter

import discord

from .common import cr_embed, fmt_int, fmt_tag, get_items, send_api_error


async def jogadores(self, interaction: discord.Interaction, localizacao: str = "global", limite: int = 10):
    await interaction.response.defer(thinking=True)
    try:
        location_id = await self.resolve_location_id(localizacao)
        data = await self.api.get_location_ranking(location_id, "players", limit=limite)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    items = get_items(data)
    embed = cr_embed("Ranking de jogadores", f"Localizacao: `{localizacao}`")
    embed.description = "\n".join(
        f"`#{p.get('rank', '-')}` **{p.get('name', 'Jogador')}** {fmt_tag(p.get('tag'))} - {fmt_int(p.get('trophies'))} trofeus"
        for p in items[:limite]
    ) or "Ranking sem dados nessa localizacao."
    await interaction.followup.send(embed=embed)


async def clans(self, interaction: discord.Interaction, localizacao: str = "global", limite: int = 10):
    await interaction.response.defer(thinking=True)
    try:
        location_id = await self.resolve_location_id(localizacao)
        data = await self.api.get_location_ranking(location_id, "clans", limit=limite)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    items = get_items(data)
    embed = cr_embed("Ranking de clas", f"Localizacao: `{localizacao}`")
    embed.description = "\n".join(
        f"`#{c.get('rank', '-')}` **{c.get('name', 'Cla')}** {fmt_tag(c.get('tag'))} - {fmt_int(c.get('clanScore'))} pontos"
        for c in items[:limite]
    ) or "Ranking sem dados nessa localizacao."
    await interaction.followup.send(embed=embed)


async def servidor(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    docs = await self.get_linked_accounts(interaction.guild_id)
    players = [doc.get("last_profile") for doc in docs if doc.get("last_profile")]
    players = sorted(players, key=lambda p: int(p.get("trophies", 0) or 0), reverse=True)

    embed = cr_embed("Ranking Clash do servidor")
    embed.description = "\n".join(
        f"`#{idx}` **{p.get('name')}** {fmt_tag(p.get('tag'))} - {fmt_int(p.get('trophies'))} trofeus"
        for idx, p in enumerate(players[:15], 1)
    ) or "Ainda nao ha perfis vinculados com cache. Use `/royale admin sync`."
    await interaction.followup.send(embed=embed)


async def top_trofeus(self, interaction: discord.Interaction):
    return await servidor(self, interaction)


async def top_vitorias(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    docs = await self.get_linked_accounts(interaction.guild_id)
    players = [doc.get("last_profile") for doc in docs if doc.get("last_profile")]
    players = sorted(players, key=lambda p: int(p.get("wins", 0) or 0), reverse=True)
    embed = cr_embed("Top vitorias do servidor")
    embed.description = "\n".join(
        f"`#{idx}` **{p.get('name')}** - {fmt_int(p.get('wins'))} vitorias"
        for idx, p in enumerate(players[:15], 1)
    ) or "Ainda nao ha perfis vinculados com cache."
    await interaction.followup.send(embed=embed)


async def top_clans(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    docs = await self.get_linked_accounts(interaction.guild_id)
    clans_counter = Counter()
    clan_tags = {}
    for doc in docs:
        clan = (doc.get("last_profile") or {}).get("clan") or {}
        name = clan.get("name")
        if name:
            clans_counter[name] += 1
            clan_tags[name] = clan.get("tag")
    embed = cr_embed("Clas mais presentes no servidor")
    embed.description = "\n".join(
        f"`#{idx}` **{name}** {fmt_tag(clan_tags.get(name))} - `{count}` vinculados"
        for idx, (name, count) in enumerate(clans_counter.most_common(15), 1)
    ) or "Nenhum cla encontrado nos vinculos."
    await interaction.followup.send(embed=embed)
