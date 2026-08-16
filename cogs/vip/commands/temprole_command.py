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

    await asyncio.to_thread(
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

    if cargo not in usuario.roles:
        try:
            await usuario.add_roles(cargo)
        except discord.Forbidden:
            return await it.response.send_message("Sem permissao (cargo superior ao meu).", ephemeral=True)

    await it.response.send_message(
        f"Cargo {cargo.mention} {action_msg} para {usuario.mention}.\n"
        f"Expira em: <t:{int(new_end_time)}:F> (<t:{int(new_end_time)}:R>)",
        ephemeral=True
    )
