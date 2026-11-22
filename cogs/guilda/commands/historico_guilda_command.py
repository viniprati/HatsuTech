from __future__ import annotations

import asyncio
import logging
import discord

from database import TransactionUnavailable
from utils import ensure_guild_interaction, truncate_discord_text
from .. import finance

log = logging.getLogger(__name__)
PAGE_SIZE = 5


class GuildHistoryView(discord.ui.View):
    def __init__(self, owner_id, server_id, guild_id):
        super().__init__(timeout=180)
        self.owner_id, self.server_id, self.guild_id = owner_id, server_id, guild_id
        self.page = 0

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner_id and interaction.guild_id == self.server_id:
            return True
        await interaction.response.send_message("Abra seu próprio `/historico_guilda`.", ephemeral=True)
        return False

    def render(self, document, entries):
        pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = max(0, min(self.page, pages - 1))
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page == pages - 1
        name = discord.utils.escape_markdown(document.get("name", "Guilda"))
        embed = discord.Embed(
            title="Histórico da sua guilda", color=discord.Color.dark_teal(),
            description=(f"**{name}**\nCofre: **{int(document.get('treasury_eter', 0)):,} Éteres**\n"
                         "Depósitos de bônus agrupados por membro, dia e origem."),
        )
        for entry in entries[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]:
            timestamp = finance.utc_date(entry.get("updated_at"))
            when = f"<t:{int(timestamp.timestamp())}:f>" if timestamp else "Data indisponível"
            actor = f"<@{int(entry['actor_id'])}>" if entry.get("actor_id") else "Membro"
            kind = entry.get("type")
            if kind == "deposit":
                source = "chat" if entry.get("source") == "message" else "voz"
                title, text = "Entrada no cofre", f"{actor} • {source}: **+{entry.get('amount', 0):,} Éteres**"
            elif kind == "distribution":
                recipients = ", ".join(f"<@{int(uid)}>" for uid in entry.get("recipients", []))
                title = "Distribuição igualitária"
                text = (f"Líder: {actor}\nTotal: **{entry.get('amount', 0):,} Éteres** • "
                        f"**{entry.get('share', 0):,}** por membro\n"
                        f"Receberam: {recipients}\nSobra: **{entry.get('remainder', 0):,} Éteres**")
            elif kind == "creation":
                title, text = "Criação da guilda", f"{actor} pagou **{entry.get('fee', 0):,} Essências**."
            elif kind == "slot_donation":
                title = "Doação para vagas"
                text = f"{actor} doou **{entry['amount']:,} Essências**.".replace(",", ".")
            elif kind == "slot_purchase":
                title = "Compra de vaga extra"
                text = (f"{actor} comprou uma vaga por **{entry['amount']:,} Essências**.\n"
                        f"Da reserva: **{entry['from_reserve']:,}** • Da carteira do líder: **{entry['from_personal']:,}**").replace(",", ".")
            else:
                title, text = "Movimento", "Registro administrativo."
            embed.add_field(name=title, value=truncate_discord_text(f"{when}\n{text}", 1024), inline=False)
        if not entries:
            embed.add_field(name="Sem movimentos", value="O histórico começa com as operações registradas após esta atualização.")
        embed.set_footer(text=f"Página {self.page + 1}/{pages} • Até {finance.HISTORY_LIMIT} movimentos recentes • Só integrantes podem consultar")
        return embed

    async def change_page(self, interaction, delta):
        await interaction.response.defer(ephemeral=True)
        try:
            # Revalidate membership on every click, including after leaving,
            # being expelled or joining another guild while this view is open.
            document, entries = await asyncio.to_thread(
                finance.read_history, self.server_id, self.owner_id, self.guild_id,
            )
        except (finance.GuildFinanceError, TransactionUnavailable) as error:
            return await interaction.edit_original_response(content=str(error), embed=None, view=None)
        self.page += delta
        await interaction.edit_original_response(
            content=None, embed=self.render(document, entries), view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        await self.change_page(interaction, -1)

    @discord.ui.button(label="Próximo", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        await self.change_page(interaction, 1)

    async def on_error(self, interaction, error, item):
        log.error("guild_history_view_failed error_type=%s", type(error).__name__)
        if interaction.response.is_done():
            await interaction.followup.send("Não consegui consultar o histórico agora.", ephemeral=True)
        else:
            await interaction.response.send_message("Não consegui consultar o histórico agora.", ephemeral=True)


async def execute(self, it: discord.Interaction):
    if not await ensure_guild_interaction(it, "o comando /historico_guilda"):
        return
    await it.response.defer(ephemeral=True)
    try:
        document = await asyncio.to_thread(finance.read_current_guild, it.guild.id, it.user.id)
        document, entries = await asyncio.to_thread(finance.read_history, it.guild.id, it.user.id, document["_id"])
    except (finance.GuildFinanceError, TransactionUnavailable) as error:
        return await it.followup.send(str(error), ephemeral=True)
    view = GuildHistoryView(it.user.id, it.guild.id, document["_id"])
    await it.followup.send(
        embed=view.render(document, entries), view=view, ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )
