from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord

from .common import SUCCESS_COLOR, WARN_COLOR, cr_embed, fmt_int, send_api_error


async def config(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    settings = await self.get_settings(interaction.guild_id)
    embed = cr_embed("Configuracao Clash Royale")
    embed.add_field(name="Cla principal", value=f"`{settings.get('main_clan_tag') or 'nao configurado'}`", inline=True)
    embed.add_field(name="Canal de alertas", value=f"<#{settings['alert_channel_id']}>" if settings.get("alert_channel_id") else "Nao configurado", inline=True)
    embed.add_field(name="Cache API", value=f"`{len(self.api._cache)}` entradas", inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)


async def clan_principal(self, interaction: discord.Interaction, tag: str):
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        clan = await self.api.get_clan(tag)
    except Exception as exc:
        return await send_api_error(interaction, exc)

    await asyncio.to_thread(
        self.settings_col.update_one,
        {"_id": str(interaction.guild_id)},
        {
            "$set": {
                "guild_id": str(interaction.guild_id),
                "main_clan_tag": clan.get("tag"),
                "main_clan_name": clan.get("name"),
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    embed = cr_embed("Cla principal configurado", f"Agora o cla principal e **{clan.get('name')}** `{clan.get('tag')}`.", SUCCESS_COLOR)
    await interaction.followup.send(embed=embed, ephemeral=True)


async def sync(self, interaction: discord.Interaction, limite: int = 50):
    await interaction.response.defer(thinking=True, ephemeral=True)
    docs = await self.get_linked_accounts(interaction.guild_id)
    docs = docs[: max(1, min(limite, 200))]
    ok = failed = 0
    for doc in docs:
        try:
            player = await self.api.get_player(doc.get("player_tag"))
            await self.save_profile_cache_by_id(player, doc["_id"], interaction.guild_id)
            ok += 1
            await asyncio.sleep(0.2)
        except Exception:
            failed += 1

    embed = cr_embed("Sync concluido", f"Atualizados: `{ok}`\nFalhas: `{failed}`", SUCCESS_COLOR if failed == 0 else WARN_COLOR)
    await interaction.followup.send(embed=embed, ephemeral=True)


async def vinculos(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    docs = await self.get_linked_accounts(interaction.guild_id)
    embed = cr_embed("Vinculos Clash Royale")
    embed.add_field(name="Total", value=f"`{len(docs)}` contas vinculadas", inline=True)
    recent = docs[:10]
    embed.add_field(
        name="Recentes",
        value="\n".join(f"**{d.get('player_name', 'Jogador')}** `{d.get('player_tag')}`" for d in recent) or "-",
        inline=False,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


async def cache_limpar(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    size = self.api.clear_cache()
    embed = cr_embed("Cache limpo", f"Removi `{fmt_int(size)}` entradas do cache local.", SUCCESS_COLOR)
    await interaction.followup.send(embed=embed, ephemeral=True)


async def logs(self, interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    docs = await asyncio.to_thread(lambda: list(self.logs_col.find({"guild_id": str(interaction.guild_id)}).sort("created_at", -1).limit(10)))
    embed = cr_embed("Logs Clash Royale")
    embed.description = "\n".join(
        f"`{d.get('created_at')}` **{d.get('event')}** - {d.get('detail', '-')}"
        for d in docs
    ) or "Nenhum log registrado."
    await interaction.followup.send(embed=embed, ephemeral=True)
