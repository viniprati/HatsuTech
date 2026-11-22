from __future__ import annotations

import asyncio
import discord

from database import TransactionUnavailable
from utils import ensure_guild_interaction
from .. import finance


async def execute(self, it: discord.Interaction):
    if not await ensure_guild_interaction(it, "o comando /guilda_cofre"):
        return
    await it.response.defer(ephemeral=True)
    try:
        document = await asyncio.to_thread(finance.read_current_guild, it.guild.id, it.user.id)
    except (finance.GuildFinanceError, TransactionUnavailable) as error:
        return await it.followup.send(str(error), ephemeral=True)

    name = discord.utils.escape_markdown(document.get("name", "Guilda"))
    balance = int(document.get("treasury_eter", 0))
    contribution = sum(int(member.get("treasury_contributed", 0)) for member in document.get("members", [])
                       if str(member.get("user_id")) == str(it.user.id))
    embed = discord.Embed(
        title="🏦 Cofre da sua guilda", color=discord.Color.gold(),
        description=f"**{name}**\n\nSaldo disponível: **{balance:,} Éteres**".replace(",", "."),
    )
    embed.add_field(name="Sua contribuição", value=f"{contribution:,} Éteres".replace(",", "."), inline=False)
    essence = f"{document.get('slot_essence_balance', 0):,}".replace(",", ".")
    embed.add_field(name="Reserva de vagas", value=(f"**{essence} Essências** disponíveis.\n"
                    "Use `/guilda doar_essencias` para contribuir. O líder compra em `/guilda vagas`."), inline=False)
    embed.add_field(
        name="Como funciona",
        value=("O bônus de guilda acumula neste cofre e o saldo permanece entre as temporadas.\n"
               "O líder usa `/guilda distribuir` para dividir igualmente entre integrantes presentes "
               "com pelo menos sete dias na guilda. Sobras permanecem no cofre."),
        inline=False,
    )
    embed.add_field(name="Movimentações", value="Use `/historico_guilda` para consultar o histórico em privado.", inline=False)
    embed.set_footer(text="Visível só para você • Consulta restrita aos integrantes da própria guilda")
    await it.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
