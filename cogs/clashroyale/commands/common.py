from __future__ import annotations

from datetime import datetime, timezone

import discord

from ..client import ClashRoyaleApiError


CR_COLOR = 0x2B7FFF
SUCCESS_COLOR = 0x2ECC71
WARN_COLOR = 0xF1C40F
ERROR_COLOR = 0xE74C3C


def cr_embed(title: str, description: str | None = None, color: int = CR_COLOR) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text="Clash Royale • Hatsutech")
    return embed


def fmt_int(value, default: str = "0") -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return default


def fmt_tag(tag: str | None) -> str:
    return f"`{tag or '-'}`"


def truncate(value: str | None, limit: int = 1024) -> str:
    text = str(value or "-")
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def card_line(card: dict) -> str:
    level = card.get("level")
    max_level = card.get("maxLevel")
    elixir = card.get("elixirCost")
    suffix = []
    if level is not None:
        suffix.append(f"nv. {level}")
    if max_level is not None:
        suffix.append(f"max {max_level}")
    if elixir is not None:
        suffix.append(f"{elixir} elixir")
    return f"**{card.get('name', 'Carta')}**" + (f" ({', '.join(suffix)})" if suffix else "")


def safe_ratio(part: int | float, total: int | float) -> float:
    return (float(part) / float(total) * 100) if total else 0


async def send_api_error(interaction: discord.Interaction, error: Exception):
    if isinstance(error, ValueError):
        message = str(error)
    elif isinstance(error, ClashRoyaleApiError):
        if error.status == 403:
            message = (
                "A API recusou a requisicao. Confere se o IP da host esta autorizado na key.\n\n"
                f"Detalhe: `{truncate(error.message, 600)}`"
            )
        elif error.status == 404:
            message = "Nao encontrei esse registro no Clash Royale. Confere se a tag esta correta."
        elif error.status == 0:
            message = error.message
        else:
            message = f"Erro na API do Clash Royale: `{error.reason}`."
    else:
        message = "Erro inesperado ao consultar o Clash Royale."

    embed = cr_embed("Falha ao consultar Clash Royale", message, ERROR_COLOR)
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


def get_items(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("items") or [])
    return []
