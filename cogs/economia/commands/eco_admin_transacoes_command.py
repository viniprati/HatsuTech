from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction, usuario: discord.Member = None):
    await interaction.response.defer(ephemeral=True)
    query = {"guild_id": self._gid(interaction.guild.id), "status": "completed"}
    if usuario:
        query["buyer_id"] = self._uid(usuario.id)

    transactions = await asyncio.to_thread(
        lambda: list(eco_vip_transactions_col.find(query).sort("created_at", -1).limit(20))
    )
    if not transactions:
        suffix = f" para {usuario.mention}" if usuario else ""
        return await interaction.followup.send(f"Nenhuma compra de VIP registrada{suffix}.", ephemeral=True)

    lines = []
    total = 0
    for data in transactions:
        buyer_id = data.get("buyer_id", "?")
        sku = data.get("sku")
        item_name = data.get("item_name", data.get("sku", "VIP"))
        price = int(data.get("price_amount", 0))
        total += price
        created_at = data.get("created_at")
        timestamp = f"<t:{int(created_at.timestamp())}:f>" if created_at else "data indisponivel"
        item_label = format_vip_name(sku, item_name) if sku else item_name
        lines.append(f"{timestamp} | <@{buyer_id}> | **{item_label}** | {format_currency_amount('essencia', price)}")

    embed = discord.Embed(
        title="Transacoes VIP - Kaguya",
        description=truncate_discord_text("\n".join(lines), DISCORD_EMBED_DESCRIPTION_LIMIT, "\n[conteudo truncado]"),
        color=discord.Color.gold(),
    )
    embed.set_footer(text=f"Ultimas {len(transactions)} compras | Total exibido: {total} Essência")
    await interaction.followup.send(embed=embed, ephemeral=True)
