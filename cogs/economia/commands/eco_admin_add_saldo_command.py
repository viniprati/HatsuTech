from __future__ import annotations
from ..cog import *


async def execute(self, interaction: discord.Interaction, usuario: discord.Member, moeda: Choice[str], valor: int, motivo: str):
    if not await ensure_db_online(interaction, "o comando /eco_admin add_saldo"):
        return

    motivo = " ".join((motivo or "").strip().split())
    if not motivo:
        return await interaction.response.send_message("❌ Informe o motivo da alteração.", ephemeral=True)

    native_admin = self._is_native_economy_admin(interaction)
    events_team_access = self._is_events_team_member(interaction) and not native_admin
    if events_team_access and moeda.value != "essencia":
        return await interaction.response.send_message(
            "❌ A equipe de eventos só pode adicionar saldo de `essencia`.",
            ephemeral=True,
        )

    add = int(valor)
    if add <= 0:
        return await interaction.response.send_message(
            "❌ O valor para adicionar precisa ser maior que zero.",
            ephemeral=True,
        )

    before_doc = await asyncio.to_thread(self._get_user_doc, usuario.id, interaction.guild.id)
    before = int(before_doc.get(moeda.value, 0) or 0)
    credited = await asyncio.to_thread(self._credit_user, usuario.id, interaction.guild.id, {moeda.value: add})
    if not credited:
        return await interaction.response.send_message(
            "❌ Não foi possível confirmar a alteração no banco de dados.",
            ephemeral=True,
        )
    after_doc = await asyncio.to_thread(self._get_user_doc, usuario.id, interaction.guild.id)
    after = int(after_doc.get(moeda.value, before + add) or 0)

    log_doc = {
        "type": "eco_admin_add_saldo",
        "guild_id": self._gid(interaction.guild.id),
        "actor_id": self._uid(interaction.user.id),
        "target_id": self._uid(usuario.id),
        "currency": moeda.value,
        "amount": add,
        "before": before,
        "after": after,
        "reason": motivo,
        "access_source": "events_team_role" if events_team_access else "native_admin",
        "created_at": datetime.now(timezone.utc),
    }
    await asyncio.to_thread(eco_admin_logs_col.insert_one, log_doc)

    if events_team_access:
        await self._send_economy_event_audit_dm(
            interaction,
            action="/eco_admin add_saldo",
            usuario=usuario,
            moeda=moeda.value,
            valor=add,
            motivo=motivo,
            before=before,
            after=after,
        )

    await interaction.response.send_message(
        f"Adicionado `{add}` de `{moeda.value}` para {usuario.mention}. Motivo: `{motivo}`",
        ephemeral=True,
    )
