import asyncio

from database import TransactionUnavailable
from ..finance import GuildFinanceError, donate_slot_essence


async def execute(interaction, amount):
    await interaction.response.defer(ephemeral=True)
    try:
        await asyncio.to_thread(donate_slot_essence, interaction.guild_id, interaction.user.id,
                                amount, interaction.id)
    except (GuildFinanceError, TransactionUnavailable) as error:
        return await interaction.followup.send(str(error), ephemeral=True)
    formatted = f"{amount:,}".replace(",", ".")
    await interaction.followup.send(
        f"Você doou **{formatted} Essências** para a compra de vagas da sua guilda. Consulte `/guilda_cofre`.",
        ephemeral=True,
    )
