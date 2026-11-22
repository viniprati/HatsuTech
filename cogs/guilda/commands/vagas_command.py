import asyncio

from database import TransactionUnavailable
from cogs.economia.slot_checkout_view import SlotCheckoutView
from cogs.economia.slot_upgrades import GUILD_BASE_CAPACITY, buy_slot, slot_price
from ..finance import GuildFinanceError, read_current_guild


async def execute(interaction):
    await interaction.response.defer(ephemeral=True)
    guild_id, actor_id = interaction.guild_id, interaction.user.id
    try:
        document = await asyncio.to_thread(read_current_guild, guild_id, actor_id)
    except (GuildFinanceError, TransactionUnavailable) as error:
        return await interaction.followup.send(str(error), ephemeral=True)
    if str(document.get("leader_id")) != str(actor_id):
        return await interaction.followup.send("Só o líder pode comprar vagas para a guilda.", ephemeral=True)

    count = document.get("extra_member_slots", 0)
    price = slot_price("guild", count)
    from_reserve = min(document.get("slot_essence_balance", 0), price)
    personal = price - from_reserve

    async def purchase(_, operation_id):
        return await asyncio.to_thread(buy_slot, "guild", guild_id, actor_id, document["_id"], count, operation_id,
                                       max_personal=personal)

    view = SlotCheckoutView(interaction, "guild", GUILD_BASE_CAPACITY, count, purchase)
    split = (f"\n\nReserva da guilda: **{from_reserve:,} Essências**.\n"
             f"Da sua carteira: **até {personal:,} Essências**.").replace(",", ".")
    await interaction.followup.send(view.description() + split, view=view, ephemeral=True)
