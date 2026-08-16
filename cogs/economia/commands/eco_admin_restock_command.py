from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction, item: Choice[str], quantidade: int = 0):
    shop = await asyncio.to_thread(eco_shop_col.find_one, {"_id": "main_shop"}) or {"items": {}}
    items = shop.get("items", {})
    if item.value == "all":
        sets = {}
        for sku, data in items.items():
            sets[f"items.{sku}.stock"] = int(data.get("max_stock", data.get("stock", 0)))
        await asyncio.to_thread(eco_shop_col.update_one, {"_id": "main_shop"}, {"$set": sets}, upsert=True)
        await asyncio.to_thread(
            eco_limits_col.update_many,
            {"guild_id": self._gid(interaction.guild.id)},
            {"$set": {"purchased_skus": []}},
        )
        return await interaction.response.send_message(
            "Estoque de todos os itens foi reposto para maximo e os limites da rodada foram liberados.",
            ephemeral=True,
        )

    data = items.get(item.value)
    if not data:
        return await interaction.response.send_message("Item nao encontrado.", ephemeral=True)

    if quantidade <= 0:
        new_stock = int(data.get("max_stock", data.get("stock", 0)))
    else:
        new_stock = int(data.get("stock", 0) + quantidade)
        new_stock = min(new_stock, int(data.get("max_stock", new_stock)))

    await asyncio.to_thread(eco_shop_col.update_one, {"_id": "main_shop"}, {"$set": {f"items.{item.value}.stock": new_stock}})
    await asyncio.to_thread(
        eco_limits_col.update_many,
        {"guild_id": self._gid(interaction.guild.id)},
        {"$pull": {"purchased_skus": item.value}},
    )
    await interaction.response.send_message(
        f"Novo estoque de `{item.value}`: `{new_stock}`. Limite da rodada liberado para este VIP.",
        ephemeral=True,
    )
