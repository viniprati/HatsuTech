from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction, item: Choice[str], quantidade: int = 0):
    if not await ensure_db_online(interaction, "a reposição de estoque"):
        return
    shop = await asyncio.to_thread(eco_shop_col.find_one, {"_id": "main_shop"}) or {"items": {}}
    items = shop.get("items", {})
    if item.value == "all":
        sets = {}
        for sku, data in items.items():
            sets[f"items.{sku}.stock"] = int(data.get("max_stock", data.get("stock", 0)))
        if not sets:
            return await interaction.response.send_message("Não há itens configurados para repor.", ephemeral=True)
        stock_result = await asyncio.to_thread(eco_shop_col.update_one, {"_id": "main_shop"}, {"$set": sets}, upsert=True)
        if not getattr(stock_result, "acknowledged", False):
            return await interaction.response.send_message("Não consegui repor o estoque. Tente novamente.", ephemeral=True)
        limits_result = await asyncio.to_thread(
            eco_limits_col.update_many,
            {},
            {"$set": {"purchased_skus": []}},
        )
        if not getattr(limits_result, "acknowledged", False):
            return await interaction.response.send_message(
                "Estoque reposto, mas não consegui liberar os limites de compra. Avise a administração.",
                ephemeral=True,
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

    stock_result = await asyncio.to_thread(
        eco_shop_col.update_one, {"_id": "main_shop"}, {"$set": {f"items.{item.value}.stock": new_stock}}
    )
    if not getattr(stock_result, "acknowledged", False) or not stock_result.matched_count:
        return await interaction.response.send_message("Não consegui atualizar o estoque. Tente novamente.", ephemeral=True)
    limits_result = await asyncio.to_thread(
        eco_limits_col.update_many,
        {},
        {"$pull": {"purchased_skus": item.value}},
    )
    if not getattr(limits_result, "acknowledged", False):
        return await interaction.response.send_message(
            f"Estoque de `{item.value}` atualizado para `{new_stock}`, mas os limites de compra não foram liberados. Avise a administração.",
            ephemeral=True,
        )
    await interaction.response.send_message(
        f"Novo estoque de `{item.value}`: `{new_stock}`. Limite da rodada liberado para este VIP.",
        ephemeral=True,
    )
