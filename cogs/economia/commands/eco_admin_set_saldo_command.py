from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction, usuario: discord.Member, moeda: Choice[str], valor: int, motivo: str):
    if not await ensure_db_online(interaction, "o comando /eco_admin set_saldo"):
        return

    motivo = " ".join((motivo or "").strip().split())
    if not motivo:
        return await interaction.response.send_message("❌ Informe o motivo da alteração.", ephemeral=True)

    native_admin = self._is_native_economy_admin(interaction)
    events_team_access = self._is_events_team_member(interaction) and not native_admin
    if events_team_access and moeda.value != "essencia":
        return await interaction.response.send_message(
            "❌ A equipe de eventos só pode definir saldo de `essencia`.",
            ephemeral=True,
        )

    new_value = max(0, int(valor))
    await asyncio.to_thread(self._ensure_user_doc, usuario.id, interaction.guild.id)
    before_doc = await asyncio.to_thread(self._get_user_doc, usuario.id, interaction.guild.id)
    before = int(before_doc.get(moeda.value, 0) or 0)
    result = await asyncio.to_thread(
        eco_users_col.update_one,
        {"_id": self._user_doc_id(usuario.id, interaction.guild.id)},
        {"$set": {moeda.value: new_value, "updated_at": datetime.now(timezone.utc)}},
    )
    if not getattr(result, "acknowledged", False):
        return await interaction.response.send_message(
            "❌ Não foi possível confirmar a alteração no banco de dados.",
            ephemeral=True,
        )
    log_doc = {
        "type": "eco_admin_set_saldo",
        "guild_id": self._gid(interaction.guild.id),
        "actor_id": self._uid(interaction.user.id),
        "target_id": self._uid(usuario.id),
        "currency": moeda.value,
        "amount": new_value,
        "before": before,
        "after": new_value,
        "reason": motivo,
        "access_source": "events_team_role" if events_team_access else "native_admin",
        "created_at": datetime.now(timezone.utc),
    }
    await asyncio.to_thread(eco_admin_logs_col.insert_one, log_doc)

    if events_team_access:
        await self._send_economy_event_audit_dm(
            interaction,
            action="/eco_admin set_saldo",
            usuario=usuario,
            moeda=moeda.value,
            valor=new_value,
            motivo=motivo,
            before=before,
            after=new_value,
        )

    await interaction.response.send_message(
        f"Saldo de `{moeda.value}` de {usuario.mention} definido para `{new_value}`. Motivo: `{motivo}`",
        ephemeral=True,
    )
