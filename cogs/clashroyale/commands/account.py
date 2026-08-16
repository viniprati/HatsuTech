from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord

from .common import SUCCESS_COLOR, cr_embed, fmt_int, fmt_tag, send_api_error


async def vincular(self, interaction: discord.Interaction, tag: str):
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        player = await self.api.get_player(tag)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    normalized_tag = self.api.normalize_tag(player.get("tag") or tag)
    doc = {
        "guild_id": str(interaction.guild_id),
        "player_tag": normalized_tag,
        "player_name": player.get("name"),
        "last_profile": player,
        "linked_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await asyncio.to_thread(
        self.accounts_col.update_one,
        {"_id": str(interaction.user.id)},
        {"$set": doc, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )

    embed = cr_embed(
        "Conta vinculada",
        f"{interaction.user.mention}, vinculei sua conta **{player.get('name')}** {fmt_tag(normalized_tag)}.",
        SUCCESS_COLOR,
    )
    embed.add_field(name="Trofeus", value=fmt_int(player.get("trophies")), inline=True)
    embed.add_field(name="Nivel", value=fmt_int(player.get("expLevel")), inline=True)
    clan = player.get("clan") or {}
    embed.add_field(name="Cla", value=clan.get("name", "Sem cla"), inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)


async def desvincular(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    result = await asyncio.to_thread(self.accounts_col.delete_one, {"_id": str(interaction.user.id)})
    if getattr(result, "deleted_count", 0):
        embed = cr_embed("Conta desvinculada", "Removi seu vinculo com Clash Royale.", SUCCESS_COLOR)
    else:
        embed = cr_embed("Sem vinculo", "Voce ainda nao tinha uma conta vinculada.")
    await interaction.followup.send(embed=embed, ephemeral=True)


async def perfil(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
    await interaction.response.defer(thinking=True)
    try:
        player_tag = await self.resolve_player_tag(interaction, usuario, tag)
        player = await self.api.get_player(player_tag)
        await self.save_profile_cache(player, usuario or interaction.user)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    await interaction.followup.send(embed=self.build_player_embed(player))


async def atualizar(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        player_tag = await self.resolve_player_tag(interaction, interaction.user, None)
        player = await self.api.get_player(player_tag)
        await self.save_profile_cache(player, interaction.user)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    embed = cr_embed(
        "Perfil atualizado",
        f"Atualizei o cache de **{player.get('name')}** {fmt_tag(player.get('tag'))}.",
        SUCCESS_COLOR,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


async def status(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    configured = "Sim" if self.api.configured else "Nao"
    cache_size = len(self.api._cache)
    try:
        started = datetime.now(timezone.utc)
        data = await self.api.get_cards()
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        api_state = f"Online (`{elapsed_ms}ms`)"
        details = f"Cartas carregadas: `{len(data.get('items') or [])}`"
    except Exception as exc:
        api_state = "Com erro"
        details = str(exc)[:500]

    embed = cr_embed("Status Clash Royale")
    embed.add_field(name="Token configurado", value=configured, inline=True)
    embed.add_field(name="API", value=api_state, inline=True)
    embed.add_field(name="Cache local", value=f"`{cache_size}` entradas", inline=True)
    embed.add_field(name="Detalhes", value=details, inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)
