from __future__ import annotations

from collections import Counter

import discord

from .common import cr_embed, fmt_int, get_items, send_api_error, truncate

WIN_CONDITIONS = {
    "Hog Rider", "Royal Giant", "Goblin Barrel", "Graveyard", "Balloon", "Miner", "X-Bow",
    "Mortar", "Goblin Drill", "Giant", "Golem", "Lava Hound", "Ram Rider", "Battle Ram",
    "Wall Breakers", "Royal Hogs", "Elixir Golem", "Electro Giant", "Goblin Giant",
}
SPELLS = {
    "Arrows", "Fireball", "Rocket", "Lightning", "Zap", "The Log", "Poison", "Tornado",
    "Earthquake", "Royal Delivery", "Giant Snowball", "Barbarian Barrel", "Freeze", "Rage",
    "Void", "Goblin Curse",
}
AIR_ANSWERS = {
    "Musketeer", "Archers", "Firecracker", "Wizard", "Electro Wizard", "Magic Archer",
    "Baby Dragon", "Inferno Dragon", "Mega Minion", "Minions", "Minion Horde", "Bats",
    "Phoenix", "Hunter", "Executioner", "Tesla", "Inferno Tower", "Cannon Cart",
}
BUILDINGS = {
    "Cannon", "Tesla", "Inferno Tower", "Bomb Tower", "Goblin Cage", "Tombstone",
    "Furnace", "Mortar", "X-Bow", "Elixir Collector", "Goblin Hut", "Barbarian Hut",
}


async def info(self, interaction: discord.Interaction, nome: str):
    await interaction.response.defer(thinking=True)
    try:
        cards = get_items(await self.api.get_cards())
    except Exception as exc:
        return await send_api_error(interaction, exc)

    card = self.find_card(cards, nome)
    if not card:
        embed = cr_embed("Carta nao encontrada", f"Nao encontrei uma carta parecida com `{nome}`.")
        return await interaction.followup.send(embed=embed)

    embed = cr_embed(card.get("name", "Carta"))
    embed.add_field(name="ID", value=f"`{card.get('id')}`", inline=True)
    embed.add_field(name="Elixir", value=f"`{card.get('elixirCost', '-')}`", inline=True)
    embed.add_field(name="Raridade", value=str(card.get("rarity", "-")).title(), inline=True)
    embed.add_field(name="Nivel maximo", value=f"`{card.get('maxLevel', '-')}`", inline=True)
    icon = (card.get("iconUrls") or {}).get("medium")
    if icon:
        embed.set_thumbnail(url=icon)
    await interaction.followup.send(embed=embed)


async def lista(self, interaction: discord.Interaction, raridade: str | None = None):
    await interaction.response.defer(thinking=True)
    try:
        cards = get_items(await self.api.get_cards())
    except Exception as exc:
        return await send_api_error(interaction, exc)

    if raridade:
        cards = [c for c in cards if str(c.get("rarity", "")).lower() == raridade.lower()]
    by_rarity = Counter(c.get("rarity", "desconhecida") for c in cards)
    names = ", ".join(sorted(c.get("name", "Carta") for c in cards))
    embed = cr_embed("Lista de cartas")
    embed.add_field(name="Total", value=f"`{len(cards)}`", inline=True)
    embed.add_field(name="Raridades", value="\n".join(f"{k.title()}: `{v}`" for k, v in by_rarity.most_common()) or "-", inline=True)
    embed.add_field(name="Cartas", value=truncate(names, 3900), inline=False)
    await interaction.followup.send(embed=embed)


async def deck_analisar(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
    await interaction.response.defer(thinking=True)
    try:
        player_tag = await self.resolve_player_tag(interaction, usuario, tag)
        player = await self.api.get_player(player_tag)
        await self.save_profile_cache(player, usuario or interaction.user)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    deck = player.get("currentDeck") or []
    names = {c.get("name") for c in deck}
    avg = sum(float(c.get("elixirCost") or 0) for c in deck) / len(deck) if deck else 0
    win = sorted(names & WIN_CONDITIONS)
    spells = sorted(names & SPELLS)
    air = sorted(names & AIR_ANSWERS)
    buildings = sorted(names & BUILDINGS)
    warnings = []
    if not win:
        warnings.append("Sem condicao de vitoria clara.")
    if len(spells) < 2:
        warnings.append("Poucos feiticos.")
    if not air:
        warnings.append("Poucas respostas aereas evidentes.")
    if avg > 4.2:
        warnings.append("Custo medio alto.")

    embed = cr_embed(f"Analise de deck - {player.get('name')}")
    embed.add_field(name="Custo medio", value=f"`{avg:.2f}`", inline=True)
    embed.add_field(name="Condicao de vitoria", value=", ".join(win) or "-", inline=True)
    embed.add_field(name="Feiticos", value=", ".join(spells) or "-", inline=True)
    embed.add_field(name="Anti-aereo", value=", ".join(air) or "-", inline=False)
    embed.add_field(name="Construcoes", value=", ".join(buildings) or "-", inline=False)
    embed.add_field(name="Leitura rapida", value="\n".join(f"- {w}" for w in warnings) if warnings else "Deck bem equilibrado pelos criterios simples.", inline=False)
    await interaction.followup.send(embed=embed)


async def meta_servidor(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    docs = await self.get_linked_accounts(interaction.guild_id)
    card_counter = Counter()
    decks = 0
    for doc in docs:
        deck = (doc.get("last_profile") or {}).get("currentDeck") or []
        if not deck:
            continue
        decks += 1
        for card in deck:
            card_counter[card.get("name", "Carta")] += 1

    embed = cr_embed("Meta do servidor")
    embed.description = f"Base: `{decks}` decks em cache."
    embed.add_field(
        name="Cartas mais usadas",
        value="\n".join(f"`#{idx}` **{name}** - `{count}` decks" for idx, (name, count) in enumerate(card_counter.most_common(15), 1)) or "Sem dados suficientes.",
        inline=False,
    )
    await interaction.followup.send(embed=embed)
