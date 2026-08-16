from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction, alvo: Choice[str], escopo: Choice[str], confirmar: str, usuario: discord.Member = None):
    if alvo.value == "usuario" and not usuario:
        return await interaction.response.send_message("Voce precisa indicar o usuario para reset individual.", ephemeral=True)

    needed_token = "RESETAR TUDO" if alvo.value == "todos" and escopo.value == "tudo" else "CONFIRMAR"
    if confirmar.strip().upper() != needed_token:
        return await interaction.response.send_message(f"Token invalido. Use exatamente: `{needed_token}`", ephemeral=True)

    payload = {
        "target_mode": alvo.value,
        "scope": escopo.value,
        "target_user_id": usuario.id if usuario else None,
        "requested_by": interaction.user.id,
    }

    embed = discord.Embed(title="Confirmacao de Reset", color=discord.Color.red())
    embed.description = (
        f"Executor: {interaction.user.mention}\n"
        f"Alvo: `{alvo.value}`\n"
        f"Escopo: `{escopo.value}`\n"
        f"Usuario alvo: `{usuario.id if usuario else '-'}`\n\n"
        "Clique em **Confirmar Reset** para executar."
    )
    view = AdminResetConfirmView(self, interaction.user.id, payload)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
