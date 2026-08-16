from __future__ import annotations
from ..cog import *


async def execute(self, it, cargo: discord.Role, imagem: discord.Attachment):
    await it.response.defer(ephemeral=True)
    if cargo.is_default() or cargo.managed:
        return await it.followup.send("❌ Este cargo não pode ter ícone alterado.", ephemeral=True)
    if not bot_can_manage_role(it.guild, cargo):
        return await it.followup.send("❌ Esse cargo é superior ou igual ao meu cargo mais alto.", ephemeral=True)
    if not can_manage_role(it.user, cargo):
        return await it.followup.send("❌ Esse cargo é superior ou igual ao seu cargo mais alto.", ephemeral=True)
    if imagem.content_type and not imagem.content_type.startswith("image/"):
        return await it.followup.send("❌ O anexo precisa ser uma imagem.", ephemeral=True)
    try:
        img_data = await imagem.read()
        processed_icon = process_icon(img_data)

        await cargo.edit(display_icon=processed_icon)
        await it.followup.send(f"✅ Ícone do cargo {cargo.mention} atualizado com sucesso!", ephemeral=True)
    except Exception as e:
        await it.followup.send(f"❌ Erro ao atualizar ícone: {e}", ephemeral=True)
