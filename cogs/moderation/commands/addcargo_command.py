from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, usuario: discord.Member, cargo: discord.Role):
    await it.response.defer(ephemeral=True)


    if cargo.is_default() or cargo.managed:
         return await it.followup.send("🚫 **Erro:** Esse cargo não pode ser atribuído manualmente.", ephemeral=True)
    if not bot_can_manage_role(it.guild, cargo):
         return await it.followup.send("🚫 **Erro:** Esse cargo é superior ou igual ao meu cargo mais alto.", ephemeral=True)
    if not can_manage_role(it.user, cargo):
         return await it.followup.send("🚫 **Erro:** Esse cargo é superior ou igual ao seu cargo mais alto.", ephemeral=True)

    try:
        if cargo in usuario.roles:
            await it.followup.send(f"⚠️ {usuario.mention} já possui o cargo {cargo.mention}.", ephemeral=True)
        else:
            await usuario.add_roles(cargo, reason=f"Adicionado por {it.user} via /addcargo")
            await it.followup.send(f"✅ Cargo {cargo.mention} adicionado a {usuario.mention}.", ephemeral=True)


            await self.enviar_log(
                it.guild,
                "🛠️ Cargo Adicionado Manualmente",
                [("Admin", it.user.mention), ("Usuário", usuario.mention), ("Cargo", cargo.mention)],
                discord.Color.green()
            )
    except discord.Forbidden:
        await it.followup.send("❌ **Erro:** Não tenho permissão para gerenciar este cargo.", ephemeral=True)
    except Exception as e:
        await it.followup.send(f"❌ **Erro:** {e}", ephemeral=True)
