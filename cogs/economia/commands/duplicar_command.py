from __future__ import annotations
from ..cog import *


def _parse_boost_duration(raw_duration: str) -> tuple[int | None, str | None]:
    duration = str(raw_duration or "").strip().lower().replace(" ", "")
    if duration in {"0", "off", "desativar"}:
        return 0, None

    match = re.fullmatch(r"(\d+)([hd])", duration)
    if not match:
        return None, "Use uma duracao como `2h` ou `1d`. Use `0` para desativar."

    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        return None, "A duracao precisa ser maior que zero. Use `0` para desativar."

    seconds = amount * 3600 if unit == "h" else amount * 86400
    if seconds > 7 * 86400:
        return None, "A duracao maxima e `7d`."

    return seconds, None


async def execute(self, interaction: discord.Interaction, duracao: str, motivo: str | None = None):
    if not interaction.guild:
        return await interaction.response.send_message("Use este comando dentro de um servidor.", ephemeral=True)
    if not await ensure_db_online(interaction, "alterar o ganho 2x da economia"):
        return

    duration_seconds, error = _parse_boost_duration(duracao)
    if error:
        return await interaction.response.send_message(error, ephemeral=True)

    guild_key = self._gid(interaction.guild.id)

    if duration_seconds == 0:
        removed = self.economy_boosts.pop(guild_key, None)
        await asyncio.to_thread(eco_settings_col.delete_one, {"_id": self._economy_boost_doc_id(guild_key)})
        if not removed:
            return await interaction.response.send_message("Nao existe ganho 2x ativo para desligar.", ephemeral=True)
        return await interaction.response.send_message("Ganho 2x da economia desativado.", ephemeral=True)

    now = self._now_ts()
    expires_at = now + duration_seconds
    boost = {
        "multiplier": 2,
        "started_at": now,
        "expires_at": expires_at,
        "started_by": interaction.user.id,
        "reason": (motivo or "").strip()[:180],
    }
    await asyncio.to_thread(
        eco_settings_col.update_one,
        {"_id": self._economy_boost_doc_id(guild_key)},
        {
            "$set": {
                **boost,
                "guild_id": guild_key,
                "updated_at": datetime.now(timezone.utc),
            },
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
        },
        upsert=True,
    )
    self.economy_boosts[guild_key] = boost

    reason_line = f"\nMotivo: {motivo.strip()[:180]}" if motivo and motivo.strip() else ""
    await interaction.response.send_message(
        (
            "Ganho 2x da economia ativado.\n"
            f"Duracao: `{str(duracao).strip()}`\n"
            f"Termina: <t:{int(expires_at)}:R>{reason_line}\n\n"
            f"Durante esse periodo, ganhos por mensagem e call valem {format_currency_amount('eter', 2)}."
        ),
        ephemeral=True,
    )
