import discord

from database import TransactionUnavailable
from .slot_upgrades import SlotPurchaseError, slot_price


class SlotCheckoutView(discord.ui.View):
    def __init__(self, interaction, kind, base_capacity, count, purchase):
        super().__init__(timeout=90)
        self.user_id = interaction.user.id
        self.guild_id = interaction.guild_id
        self.kind = kind
        self.base_capacity = base_capacity
        self.count = count
        self.purchase = purchase
        self.operation_id = interaction.id
        self.processing = False

    def description(self):
        price = f"{slot_price(self.kind, self.count):,}".replace(",", ".")
        limit = self.base_capacity + self.count
        return (f"Limite atual: **{limit} pessoas**. Com a vaga: **{limit + 1}**.\n"
                f"Preço: **{price} Essências**.\n\n"
                "Vagas extras são perdidas sem reembolso se a guilda ou o cargo for excluído.")

    async def interaction_check(self, interaction):
        if interaction.user.id == self.user_id and interaction.guild_id == self.guild_id and not self.processing:
            return True
        await interaction.response.send_message("Esta confirmação não está disponível.", ephemeral=True)
        return False

    @discord.ui.button(label="Comprar uma vaga", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        self.processing = True
        await interaction.response.defer()
        try:
            price, count = await self.purchase(interaction, self.operation_id)
        except (SlotPurchaseError, TransactionUnavailable) as error:
            text = str(error)
        else:
            paid = f"{price:,}".replace(",", ".")
            text = f"✅ Compra confirmada por **{paid} Essências**. Novo limite: **{self.base_capacity + count} pessoas**."
        self.stop()
        await interaction.edit_original_response(content=text, view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        self.processing = True
        self.stop()
        await interaction.response.edit_message(content="Compra cancelada.", view=None)
