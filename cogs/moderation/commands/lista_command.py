from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction):
    await it.response.defer(thinking=True)

    groups = await self.build_lista_groups(it.guild)
    total_members = sum(len(entries) for _label, entries in groups)
    if total_members == 0:
        return await it.followup.send(
            "Nenhum membro encontrado nos cargos de Moderador/Moderador Sênior.",
            ephemeral=True,
        )

    def make_embed(page: int = 1) -> discord.Embed:
        title = "Staff para SB!U" if page == 1 else f"Staff para SB!U - parte {page}"
        embed = discord.Embed(
            title=title,
            description=(
                f"**{total_members} membros encontrados.**\n"
                "Copie uma linha por vez; cada comando já está separado por pessoa."
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Lista gerada a partir dos cargos de moderação.")
        return embed

    def append_field(embeds: list[discord.Embed], name: str, value: str, inline: bool = False):
        if len(embeds[-1].fields) >= 25:
            embeds.append(make_embed(len(embeds) + 1))
        embeds[-1].add_field(name=name, value=value, inline=inline)

    embeds = [make_embed()]
    member_index = 1
    for label, entries in groups:
        if not entries:
            continue
        append_field(embeds, f"{label} - {len(entries)} membros", "────────────", inline=False)
        for display_name, command in entries:
            append_field(
                embeds,
                self.format_lista_member_name(member_index, display_name),
                f"`{command}`",
                inline=False,
            )
            member_index += 1

    for embed_to_send in embeds:
        await it.followup.send(embed=embed_to_send, ephemeral=False, allowed_mentions=discord.AllowedMentions.none())
