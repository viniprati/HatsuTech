from __future__ import annotations
from ..cog import *


async def execute(
    self,
    it: discord.Interaction,
    usuario: discord.Member,
    cargo: discord.Role,
    tempo: str,
    somar: bool = False
):
    if not await ensure_db_online(it, "o comando /temprole"):
        return
    duration = parse_duration_literal(tempo)
    if duration is None:
        return await it.response.send_message("Formato invalido! Use: 1d, 2h, 30m, 10s", ephemeral=True)
    if cargo.is_default() or cargo.managed or not bot_can_manage_role(it.guild, cargo):
        return await it.response.send_message("Não posso gerenciar esse cargo. Verifique minhas permissões e a hierarquia.", ephemeral=True)
    if not can_manage_role(it.user, cargo):
        return await it.response.send_message("Esse cargo é superior ou igual ao seu cargo mais alto.", ephemeral=True)

    now = time.time()

    query = {
        "user_id": str(usuario.id),
        "guild_id": str(it.guild.id),
        "role_id": str(cargo.id)
    }

    existing = await asyncio.to_thread(temp_col.find_one, query)
    if somar and existing and existing.get("end_time") > now:
        new_end_time = existing.get("end_time") + duration
        action_msg = "somado/estendido"
    else:
        new_end_time = now + duration
        action_msg = "substituido"

    role_added = cargo not in usuario.roles
    if role_added:
        try:
            await usuario.add_roles(cargo)
        except discord.Forbidden:
            return await it.response.send_message("Sem permissao (cargo superior ao meu).", ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            return await it.response.send_message("Não consegui adicionar o cargo agora. Tente novamente em instantes.", ephemeral=True)

    result = await asyncio.to_thread(
        temp_col.update_one,
        query,
        {
            "$set": {
                "end_time": new_end_time,
                "source": "temprole",
                "source_label": "Temprole manual",
                "source_detail": "command:/temprole",
                "source_actor_id": str(it.user.id),
                "updated_at": now,
            }
        },
        upsert=True,
    )
    if not getattr(result, "acknowledged", False):
        if role_added:
            try:
                await usuario.remove_roles(cargo, reason="Falha ao salvar expiração do temprole")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
                log.warning(
                    "temprole_rollback_failed guild_id=%s user_id=%s role_id=%s error=%s",
                    it.guild.id, usuario.id, cargo.id, exc,
                )
                return await it.response.send_message(
                    "Não consegui salvar a expiração nem desfazer a concessão do cargo. Avise a administração.",
                    ephemeral=True,
                )
        return await it.response.send_message(
            "Não consegui salvar a expiração. A concessão foi desfeita; tente novamente mais tarde.",
            ephemeral=True,
        )

    await it.response.send_message(
        f"Cargo {cargo.mention} {action_msg} para {usuario.mention}.\n"
        f"Expira em: <t:{int(new_end_time)}:F> (<t:{int(new_end_time)}:R>)",
        ephemeral=True
    )
    if cargo.id in VIP_CONFIG:
        await send_admin_audit_dm(
            self.bot,
            category="vip",
            action="Temprole VIP definido",
            guild=it.guild,
            actor=it.user,
            target=usuario,
            details={
                "Comando": "/temprole",
                "Cargo": f"{cargo.mention} (`{cargo.id}`)",
                "Operação": action_msg,
                "Expiração": f"<t:{int(new_end_time)}:F>",
            },
            source="command:/temprole",
        )
