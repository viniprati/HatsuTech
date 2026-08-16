from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction):
    doc = await asyncio.to_thread(self._get_user_doc, interaction.user.id, interaction.guild.id)
    limits = await asyncio.to_thread(
        eco_limits_col.find_one, {"_id": self._limits_doc_id(interaction.user.id, interaction.guild.id)}
    ) or {}
    purchased = limits.get("purchased_skus", [])
    vip_counts = self._vip_inventory_counts(doc)
    vip_lines = [
        f"{format_vip_name(sku)}: `{vip_counts[sku]}`"
        for sku, item in VIP_INVENTORY_ITEMS.items()
        if vip_counts[sku] > 0
    ]

    embed = discord.Embed(title=f"Inventario de {interaction.user.display_name}", color=discord.Color.dark_teal())
    embed.add_field(name=format_currency_label("eter"), value=f"`{int(doc.get('eter', 0))}`", inline=True)
    embed.add_field(name=format_currency_label("essencia"), value=f"`{int(doc.get('essencia', 0))}`", inline=True)
    embed.add_field(name=format_currency_label("cristal_essencia"), value=f"`{int(doc.get('cristal_essencia', 0))}`", inline=True)
    embed.add_field(name=format_lootbox_name("Lootbox Comum"), value=f"`{int(doc.get('common_box', 0))}`", inline=True)
    embed.add_field(name=format_lootbox_name("Lootbox Premium"), value=f"`{int(doc.get('premium_box', 0))}`", inline=True)
    embed.add_field(
        name="VIPs guardados",
        value="\n".join(vip_lines) if vip_lines else "Nenhum VIP guardado.",
        inline=False,
    )
    vip_bonus = get_member_vip_bonus(interaction.user)
    guild_bonus = self._get_member_guild_bonus(interaction.user)
    boost_lines = []
    if vip_bonus.get("percent"):
        boost_lines.append(f"VIP: {format_vip_bonus_label(vip_bonus)}")
    if guild_bonus.get("percent"):
        boost_lines.append(f"Guilda: {format_guild_bonus_label(guild_bonus)}")
    if boost_lines:
        total_percent = int(vip_bonus.get("percent", 0) or 0) + int(guild_bonus.get("percent", 0) or 0)
        boost_lines.append(f"Total em ganhos de chat/call: `+{total_percent}%`")
        embed.add_field(
            name="Boosts de Eter",
            value="\n".join(boost_lines),
            inline=False,
        )
    embed.add_field(
        name="Ativar ou doar",
        value=(
            "VIP comprado ou ganho fica guardado ate voce ativa-lo. "
            "Ao ativar, o prazo comeca imediatamente.\n"
            "A doacao transfere um VIP inativo para outro membro e e irreversivel; "
            "a staff nao se responsabiliza por doacoes por engano."
        ),
        inline=False,
    )
    embed.add_field(name="Compras unicas", value=", ".join(purchased) if purchased else "Nenhuma", inline=False)
    await interaction.response.send_message(
        embed=embed,
        view=EcoInventoryView(self, interaction.user.id, interaction.guild.id),
        ephemeral=True,
    )
