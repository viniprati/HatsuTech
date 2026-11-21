from __future__ import annotations

import asyncio
import discord

from database import TransactionUnavailable
from utils import ensure_guild_interaction, truncate_discord_text
from .. import finance


async def resolve_present_ids(guild, records):
    """Only confirmed departures are excluded; lookup failures stop payment."""
    present = set()
    for uid in {int(record["user_id"]) for record in records}:
        member = guild.get_member(uid)
        if member is None:
            try:
                member = await guild.fetch_member(uid)
            except discord.NotFound:
                continue
            except (discord.Forbidden, discord.HTTPException) as error:
                raise finance.GuildFinanceError(
                    "Não consegui confirmar todos os membros no servidor. Tente novamente mais tarde."
                ) from error
        if not member.bot:
            present.add(uid)
    return present


async def execute(self, it: discord.Interaction):
    if not await ensure_guild_interaction(it, "o comando /guilda distribuir"):
        return
    await it.response.defer(ephemeral=True)
    try:
        document = await asyncio.to_thread(finance.read_current_guild, it.guild.id, it.user.id)
        if int(document["leader_id"]) != it.user.id:
            raise finance.GuildFinanceError("Somente o líder pode distribuir o cofre.")
        records = document.get("members", [])
        present = await resolve_present_ids(it.guild, records)
        result = await asyncio.to_thread(
            finance.distribute, it.guild.id, document["_id"], it.user.id,
            records, present, f"distribute:{it.id}",
        )
    except (finance.GuildFinanceError, TransactionUnavailable) as error:
        return await it.followup.send(str(error), ephemeral=True)
    recipients = truncate_discord_text(", ".join(f"<@{uid}>" for uid in result["recipients"]), 3600)
    embed = discord.Embed(
        title="Cofre distribuído", color=discord.Color.green(),
        description=(f"**{result['amount']:,} Éteres** distribuídos igualmente.\n"
                     f"**{len(result['recipients'])} membros** receberam **{result['share']:,} Éteres** cada.\n"
                     f"Saldo restante no cofre: **{result['remainder']:,} Éteres**.\n\n{recipients}"),
    )
    embed.set_footer(text="Participam membros presentes com pelo menos sete dias na guilda, incluindo o líder elegível.")
    await it.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
