from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction):
    if not await ensure_db_online(interaction, "o comando /notificacao"):
        return

    user_id = interaction.user.id


    existing_user = await asyncio.to_thread(updates_col.find_one, {"user_id": user_id})

    if existing_user:

        await asyncio.to_thread(updates_col.delete_one, {"user_id": user_id})
        await interaction.response.send_message(
            "🔕 **Notificações desativadas.** Você não receberá mais mensagens sobre atualizações na sua DM.",
            ephemeral=True
        )
    else:

        await asyncio.to_thread(
            updates_col.update_one,
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "joined_at": datetime.datetime.now(datetime.timezone.utc),
                }
            },
            upsert=True,
        )
        await interaction.response.send_message(
            "🔔 **Notificações ativadas!** Sempre que houver uma novidade importante, eu te avisarei na DM.",
            ephemeral=True
        )
