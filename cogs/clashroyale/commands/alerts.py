from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord

from .common import SUCCESS_COLOR, cr_embed


IMPORTANT_CHESTS = {"Legendary Chest", "Mega Lightning Chest", "Royal Wild Chest", "Epic Chest", "Magical Chest", "Giant Chest"}


async def bau(self, interaction: discord.Interaction, ativo: bool = True):
    await interaction.response.defer(thinking=True, ephemeral=True)
    await asyncio.to_thread(
        self.accounts_col.update_one,
        {"_id": str(interaction.user.id)},
        {
            "$set": {
                "guild_id": str(interaction.guild_id),
                "alerts.chests": bool(ativo),
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    state = "ativado" if ativo else "desativado"
    embed = cr_embed("Alerta de bau", f"Alerta de bau importante **{state}** para voce.", SUCCESS_COLOR)
    await interaction.followup.send(embed=embed, ephemeral=True)


async def guerra(self, interaction: discord.Interaction, canal: discord.TextChannel | None = None, ativo: bool = True):
    await interaction.response.defer(thinking=True, ephemeral=True)
    channel = canal or interaction.channel
    await asyncio.to_thread(
        self.settings_col.update_one,
        {"_id": str(interaction.guild_id)},
        {
            "$set": {
                "guild_id": str(interaction.guild_id),
                "alerts.war": bool(ativo),
                "alert_channel_id": str(channel.id) if ativo else None,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    state = "ativado" if ativo else "desativado"
    embed = cr_embed("Alerta de guerra", f"Alerta de guerra **{state}** em {channel.mention}.", SUCCESS_COLOR)
    await interaction.followup.send(embed=embed, ephemeral=True)
