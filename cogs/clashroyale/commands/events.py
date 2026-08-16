from __future__ import annotations

import discord

from .common import cr_embed, fmt_int, fmt_tag, get_items, send_api_error, truncate


async def atuais(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    try:
        events = await self.api.get_events()
    except Exception as exc:
        return await send_api_error(interaction, exc)

    embed = cr_embed("Eventos atuais")
    lines = []
    for event in events[:10]:
        title = event.get("title") or event.get("name") or "Evento"
        mode = (event.get("gameMode") or {}).get("name")
        lines.append(f"**{title}**" + (f" - {mode}" if mode else ""))
    embed.description = "\n".join(lines) or "Nenhum evento atual retornado pela API."
    await interaction.followup.send(embed=embed)


async def desafios(self, interaction: discord.Interaction):
    await atuais(self, interaction)


async def torneio_buscar(self, interaction: discord.Interaction, nome: str):
    await interaction.response.defer(thinking=True)
    try:
        tournaments = get_items(await self.api.search_tournaments(nome, limit=10))
    except Exception as exc:
        return await send_api_error(interaction, exc)

    embed = cr_embed("Busca de torneios", f"Resultado para `{nome}`")
    embed.description = "\n".join(
        f"**{t.get('name', 'Torneio')}** {fmt_tag(t.get('tag'))} - `{fmt_int(t.get('maxCapacity'))}` vagas"
        for t in tournaments
    ) or "Nenhum torneio encontrado."
    await interaction.followup.send(embed=embed)


async def torneio(self, interaction: discord.Interaction, tag: str):
    await interaction.response.defer(thinking=True)
    try:
        tournament = await self.api.get_tournament(tag)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    embed = cr_embed(tournament.get("name", "Torneio"), tournament.get("description"))
    embed.add_field(name="Tag", value=fmt_tag(tournament.get("tag")), inline=True)
    embed.add_field(name="Status", value=str(tournament.get("status") or "-"), inline=True)
    embed.add_field(name="Jogadores", value=f"`{fmt_int(tournament.get('members'))}` / `{fmt_int(tournament.get('maxCapacity'))}`", inline=True)
    await interaction.followup.send(embed=embed)


async def torneios_globais(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    try:
        tournaments = get_items(await self.api.get_global_tournaments())
    except Exception as exc:
        return await send_api_error(interaction, exc)

    embed = cr_embed("Torneios globais")
    lines = []
    for tournament in tournaments[:10]:
        title = tournament.get("title") or tournament.get("name") or "Torneio"
        lines.append(f"**{title}** - {truncate(tournament.get('description'), 120)}")
    embed.description = "\n".join(lines) or "Nenhum torneio global ativo retornado pela API."
    await interaction.followup.send(embed=embed)
