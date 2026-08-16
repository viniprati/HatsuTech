from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction):
    user_id = interaction.user.id


    existing_user = updates_col.find_one({"user_id": user_id})

    if existing_user:

        updates_col.delete_one({"user_id": user_id})
        await interaction.response.send_message(
            "🔕 **Notificações desativadas.** Você não receberá mais mensagens sobre atualizações na sua DM.",
            ephemeral=True
        )
    else:

        updates_col.insert_one({
            "user_id": user_id,
            "joined_at": datetime.datetime.now()
        })
        await interaction.response.send_message(
            "🔔 **Notificações ativadas!** Sempre que houver uma novidade importante, eu te avisarei na DM.",
            ephemeral=True
        )
