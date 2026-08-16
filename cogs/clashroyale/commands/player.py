from __future__ import annotations

from collections import Counter

import discord

from .common import SUCCESS_COLOR, cr_embed, fmt_int, safe_ratio, send_api_error, truncate


async def batalhas(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
    await interaction.response.defer(thinking=True)
    try:
        player_tag = await self.resolve_player_tag(interaction, usuario, tag)
        battles = await self.api.get_player_battlelog(player_tag)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    embed = cr_embed("Ultimas batalhas")
    if not battles:
        embed.description = "Nenhuma batalha recente encontrada."
        return await interaction.followup.send(embed=embed)

    wins = losses = draws = 0
    lines = []
    for battle in battles[:10]:
        team = (battle.get("team") or [{}])[0]
        opponent = (battle.get("opponent") or [{}])[0]
        crowns = int(team.get("crowns", 0) or 0)
        opp_crowns = int(opponent.get("crowns", 0) or 0)
        if crowns > opp_crowns:
            wins += 1
            result = "Vitoria"
        elif crowns < opp_crowns:
            losses += 1
            result = "Derrota"
        else:
            draws += 1
            result = "Empate"
        mode = battle.get("gameMode", {}).get("name") or battle.get("type", "Batalha")
        opp_name = opponent.get("name", "Oponente")
        lines.append(f"**{result}** `{crowns}-{opp_crowns}` vs **{opp_name}** - {mode}")

    embed.description = "\n".join(lines)
    total = wins + losses + draws
    embed.add_field(name="Resumo", value=f"`{wins}` V / `{losses}` D / `{draws}` E\nWinrate: `{safe_ratio(wins, total):.1f}%`")
    await interaction.followup.send(embed=embed)


async def bau(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
    await interaction.response.defer(thinking=True)
    try:
        player_tag = await self.resolve_player_tag(interaction, usuario, tag)
        data = await self.api.get_player_chests(player_tag)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    chests = data.get("items") or []
    embed = cr_embed("Proximos baus")
    if not chests:
        embed.description = "Nao encontrei baus futuros para esse jogador."
    else:
        embed.description = "\n".join(f"`+{c.get('index', '?')}` **{c.get('name', 'Bau')}**" for c in chests[:15])
    await interaction.followup.send(embed=embed)


async def deck(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
    await interaction.response.defer(thinking=True)
    try:
        player_tag = await self.resolve_player_tag(interaction, usuario, tag)
        player = await self.api.get_player(player_tag)
        await self.save_profile_cache(player, usuario or interaction.user)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    await interaction.followup.send(embed=self.build_deck_embed(player))


async def cartas(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
    await interaction.response.defer(thinking=True)
    try:
        player_tag = await self.resolve_player_tag(interaction, usuario, tag)
        player = await self.api.get_player(player_tag)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    cards = player.get("cards") or []
    by_rarity = Counter(c.get("rarity", "Desconhecida") for c in cards)
    top = sorted(cards, key=lambda c: (int(c.get("level", 0) or 0), int(c.get("maxLevel", 0) or 0)), reverse=True)[:12]
    embed = cr_embed(f"Cartas de {player.get('name', 'jogador')}")
    embed.add_field(name="Total", value=f"`{len(cards)}` cartas", inline=True)
    embed.add_field(name="Raridades", value="\n".join(f"{k}: `{v}`" for k, v in by_rarity.most_common()) or "-", inline=True)
    embed.add_field(
        name="Maiores niveis",
        value=truncate("\n".join(f"**{c.get('name')}** - nv. `{c.get('level', '-')}`" for c in top)),
        inline=False,
    )
    await interaction.followup.send(embed=embed)


async def comparar(self, interaction: discord.Interaction, jogador1: str, jogador2: str):
    await interaction.response.defer(thinking=True)
    try:
        p1 = await self.api.get_player(jogador1)
        p2 = await self.api.get_player(jogador2)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    def line(label: str, key: str):
        return f"**{label}:** `{fmt_int(p1.get(key))}` x `{fmt_int(p2.get(key))}`"

    embed = cr_embed("Comparacao de jogadores", f"**{p1.get('name')}** x **{p2.get('name')}**")
    embed.add_field(name="Tags", value=f"`{p1.get('tag')}` x `{p2.get('tag')}`", inline=False)
    embed.add_field(
        name="Numeros",
        value="\n".join(
            [
                line("Trofeus", "trophies"),
                line("Max trofeus", "bestTrophies"),
                line("Vitorias", "wins"),
                line("Derrotas", "losses"),
                line("Nivel", "expLevel"),
            ]
        ),
        inline=False,
    )
    await interaction.followup.send(embed=embed)


async def historico(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
    await interaction.response.defer(thinking=True)
    try:
        player_tag = await self.resolve_player_tag(interaction, usuario, tag)
        battles = await self.api.get_player_battlelog(player_tag)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    wins = losses = draws = 0
    modes = Counter()
    cards = Counter()
    for battle in battles:
        team = (battle.get("team") or [{}])[0]
        opponent = (battle.get("opponent") or [{}])[0]
        crowns = int(team.get("crowns", 0) or 0)
        opp_crowns = int(opponent.get("crowns", 0) or 0)
        if crowns > opp_crowns:
            wins += 1
        elif crowns < opp_crowns:
            losses += 1
        else:
            draws += 1
        modes[battle.get("gameMode", {}).get("name") or battle.get("type", "Batalha")] += 1
        for card in team.get("cards") or []:
            cards[card.get("name", "Carta")] += 1

    total = wins + losses + draws
    embed = cr_embed("Historico recente")
    embed.add_field(name="Resultado", value=f"`{wins}` V / `{losses}` D / `{draws}` E\nWinrate: `{safe_ratio(wins, total):.1f}%`", inline=True)
    embed.add_field(name="Modos", value="\n".join(f"{k}: `{v}`" for k, v in modes.most_common(5)) or "-", inline=True)
    embed.add_field(name="Cartas mais usadas", value="\n".join(f"{k}: `{v}`" for k, v in cards.most_common(8)) or "-", inline=False)
    await interaction.followup.send(embed=embed)
