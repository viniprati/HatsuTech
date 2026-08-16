from __future__ import annotations
from ..cog import *


VERIFIED_BOT_FLAG_VALUE = 65536


def _public_flags_value(flags) -> int:
    return int(getattr(flags, "value", 0) or 0)


def _has_verified_bot_flag(flags) -> bool:
    exposed_value = getattr(flags, "verified_bot", None)
    if exposed_value is not None:
        return bool(exposed_value)
    return bool(_public_flags_value(flags) & VERIFIED_BOT_FLAG_VALUE)


def _format_public_flags(flags) -> str:
    try:
        found_flags = flags.all()
    except AttributeError:
        found_flags = []

    if not found_flags:
        return "Nenhuma flag pública encontrada."

    lines = []
    for flag in found_flags:
        name = getattr(flag, "name", str(flag).split(".")[-1])
        value = getattr(flag, "value", "?")
        lines.append(f"`{name}` (`{value}`)")
    return "\n".join(lines)


async def execute(self, it: discord.Interaction, id: str):
    raw_id = " ".join((id or "").strip().split())
    if not raw_id.isdigit():
        return await it.response.send_message("❌ Informe um ID válido contendo apenas números.", ephemeral=True)

    user_id = int(raw_id)
    try:
        user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
    except discord.NotFound:
        return await it.response.send_message("❌ Não encontrei nenhum usuário com esse ID.", ephemeral=True)
    except discord.HTTPException as e:
        log.warning("verificarbot_fetch_failed user_id=%s error=%s", user_id, e)
        return await it.response.send_message(
            "❌ Não consegui consultar esse usuário agora. Tente novamente em instantes.",
            ephemeral=True,
        )

    public_flags = user.public_flags
    flags_value = _public_flags_value(public_flags)
    is_verified_bot = bool(user.bot and _has_verified_bot_flag(public_flags))

    if user.bot and is_verified_bot:
        title = "✅ Bot verificado"
        description = "Este bot possui a flag oficial `VERIFIED_BOT` do Discord."
        color = discord.Color.green()
    elif user.bot:
        title = "❌ Bot não verificado"
        description = "Este bot não possui a flag `VERIFIED_BOT`."
        color = discord.Color.red()
    else:
        title = "⚠️ Este usuário não é um bot"
        description = "O ID consultado pertence a uma conta normal de usuário."
        color = discord.Color.gold()

    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    embed.set_author(name=str(user), icon_url=user.display_avatar.url)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Nome", value=user.global_name or user.name, inline=True)
    embed.add_field(name="Username", value=f"`{user.name}`", inline=True)
    embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
    embed.add_field(name="É bot?", value="Sim" if user.bot else "Não", inline=True)
    embed.add_field(name="Verificado pelo Discord?", value="Sim" if is_verified_bot else "Não", inline=True)
    embed.add_field(name="Valor bruto das flags", value=f"`{flags_value}`", inline=True)
    embed.add_field(name="Flags públicas encontradas", value=_format_public_flags(public_flags), inline=False)
    embed.set_footer(text="Consulta feita pelas public_flags da API do Discord")

    await it.response.send_message(embed=embed)
