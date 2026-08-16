from __future__ import annotations

import discord

from .common import cr_embed, fmt_int, fmt_tag, get_items, safe_ratio, send_api_error, truncate


async def info(self, interaction: discord.Interaction, tag_ou_nome: str):
    await interaction.response.defer(thinking=True)
    try:
        if tag_ou_nome.strip().startswith("#"):
            clan = await self.api.get_clan(tag_ou_nome)
        else:
            results = get_items(await self.api.search_clans(tag_ou_nome, limit=1))
            if not results:
                embed = cr_embed("Cla nao encontrado", "Nao encontrei cla com esse nome.")
                return await interaction.followup.send(embed=embed)
            clan = await self.api.get_clan(results[0]["tag"])
    except Exception as exc:
        return await send_api_error(interaction, exc)

    embed = self.build_clan_embed(clan)
    await interaction.followup.send(embed=embed)


async def membros(self, interaction: discord.Interaction, tag: str, limite: int = 25):
    await interaction.response.defer(thinking=True)
    try:
        data = await self.api.get_clan_members(tag, limit=limite)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    members = get_items(data)[: max(1, min(limite, 50))]
    embed = cr_embed("Membros do cla")
    embed.description = "\n".join(
        f"`{m.get('clanRank', '-')}` **{m.get('name', 'Jogador')}** {fmt_tag(m.get('tag'))} - {fmt_int(m.get('trophies'))} trofeus"
        for m in members
    ) or "Nenhum membro encontrado."
    await interaction.followup.send(embed=embed)


async def buscar(self, interaction: discord.Interaction, nome: str):
    await interaction.response.defer(thinking=True)
    try:
        clans = get_items(await self.api.search_clans(nome, limit=10))
    except Exception as exc:
        return await send_api_error(interaction, exc)

    embed = cr_embed("Busca de clas", f"Resultado para `{nome}`")
    embed.description = "\n".join(
        f"**{c.get('name')}** {fmt_tag(c.get('tag'))} - {fmt_int(c.get('members'))} membros, {fmt_int(c.get('clanScore'))} pontos"
        for c in clans
    ) or "Nenhum cla encontrado."
    await interaction.followup.send(embed=embed)


async def guerra(self, interaction: discord.Interaction, tag: str | None = None):
    await interaction.response.defer(thinking=True)
    try:
        clan_tag = tag or await self.get_main_clan_tag(interaction.guild_id)
        if not clan_tag:
            raise ValueError("Informe a tag do cla ou configure um cla principal.")
        race = await self.api.get_clan_current_river_race(clan_tag)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    clan = race.get("clan") or {}
    standings = race.get("clans") or []
    embed = cr_embed("Guerra / River Race", f"Cla: **{clan.get('name', 'Principal')}** {fmt_tag(clan.get('tag') or clan_tag)}")
    embed.add_field(name="Estado", value=str(race.get("state") or "-"), inline=True)
    embed.add_field(name="Semana", value=fmt_int(race.get("sectionIndex")), inline=True)
    if standings:
        lines = []
        for item in sorted(standings, key=lambda c: int(c.get("rank", 999) or 999))[:5]:
            lines.append(f"`#{item.get('rank', '-')}` **{item.get('name', 'Cla')}** - {fmt_int(item.get('fame'))} fama")
        embed.add_field(name="Classificacao", value="\n".join(lines), inline=False)
    await interaction.followup.send(embed=embed)


async def guerra_log(self, interaction: discord.Interaction, tag: str | None = None):
    await interaction.response.defer(thinking=True)
    try:
        clan_tag = tag or await self.get_main_clan_tag(interaction.guild_id)
        if not clan_tag:
            raise ValueError("Informe a tag do cla ou configure um cla principal.")
        data = await self.api.get_clan_river_race_log(clan_tag)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    items = get_items(data)[:5]
    embed = cr_embed("Historico de River Race")
    lines = []
    for item in items:
        season = item.get("seasonId", "-")
        section = item.get("sectionIndex", "-")
        clan = item.get("standings", [{}])[0].get("clan", {}) if item.get("standings") else {}
        lines.append(f"Temporada `{season}` semana `{section}` - {fmt_int(clan.get('fame'))} fama")
    embed.description = "\n".join(lines) or "Sem historico disponivel."
    await interaction.followup.send(embed=embed)


async def comparar(self, interaction: discord.Interaction, clan1: str, clan2: str):
    await interaction.response.defer(thinking=True)
    try:
        c1 = await self.api.get_clan(clan1)
        c2 = await self.api.get_clan(clan2)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    embed = cr_embed("Comparacao de clas", f"**{c1.get('name')}** x **{c2.get('name')}**")
    embed.add_field(name="Tags", value=f"{fmt_tag(c1.get('tag'))} x {fmt_tag(c2.get('tag'))}", inline=False)
    embed.add_field(
        name="Numeros",
        value=truncate(
            "\n".join(
                [
                    f"**Pontos:** `{fmt_int(c1.get('clanScore'))}` x `{fmt_int(c2.get('clanScore'))}`",
                    f"**Membros:** `{fmt_int(c1.get('members'))}` x `{fmt_int(c2.get('members'))}`",
                    f"**Trofeus exigidos:** `{fmt_int(c1.get('requiredTrophies'))}` x `{fmt_int(c2.get('requiredTrophies'))}`",
                    f"**Doacoes semanais:** `{fmt_int(c1.get('donationsPerWeek'))}` x `{fmt_int(c2.get('donationsPerWeek'))}`",
                    f"**War trophies:** `{fmt_int(c1.get('clanWarTrophies'))}` x `{fmt_int(c2.get('clanWarTrophies'))}`",
                ]
            )
        ),
        inline=False,
    )
    await interaction.followup.send(embed=embed)
