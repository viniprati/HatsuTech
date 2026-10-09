from __future__ import annotations
from ..cog import *


class AdminVipTransactionsView(discord.ui.View):
    def __init__(self, lines: list[str], author_id: int, total: int, member: discord.Member | None):
        super().__init__(timeout=180)
        self.lines = lines
        self.author_id = author_id
        self.total = total
        self.member = member
        self.page = 0
        self.per_page = 5
        self.total_pages = (len(lines) - 1) // self.per_page + 1
        self.update_buttons()

    def update_buttons(self):
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page >= self.total_pages - 1

    def build_embed(self):
        start = self.page * self.per_page
        current = self.lines[start:start + self.per_page]
        description = f"Compras concluídas: **{len(self.lines)}**"
        if self.member:
            description += f" • Comprador: {self.member.mention}"
        description += "\n\n" + "\n\n".join(current)
        embed = discord.Embed(
            title="🧾 Compras de VIP • Kaguya",
            description=truncate_discord_text(description, DISCORD_EMBED_DESCRIPTION_LIMIT, "\n[conteúdo truncado]"),
            color=discord.Color.gold(),
        )
        embed.set_footer(
            text=f"Página {self.page + 1}/{self.total_pages} • Últimas {len(self.lines)} compras • Total exibido: {self.total} Essência"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("Somente quem abriu a consulta pode navegar neste painel.", ephemeral=True)
        return False

    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Próxima ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


async def execute(self, interaction: discord.Interaction, usuario: discord.Member = None):
    await interaction.response.defer(ephemeral=True)
    query = {"guild_id": self._gid(interaction.guild.id), "status": "completed"}
    if usuario:
        query["buyer_id"] = self._uid(usuario.id)

    transactions = await asyncio.to_thread(
        lambda: list(eco_vip_transactions_col.find(query).sort("created_at", -1).limit(20))
    )
    if not transactions:
        suffix = f" para {usuario.mention}" if usuario else ""
        return await interaction.followup.send(f"Nenhuma compra de VIP registrada{suffix}.", ephemeral=True)

    lines = []
    total = 0
    for index, data in enumerate(transactions, 1):
        buyer_id = data.get("buyer_id", "?")
        sku = data.get("sku")
        item_name = data.get("item_name", data.get("sku", "VIP"))
        price = int(data.get("price_amount", 0))
        total += price
        created_at = data.get("created_at")
        timestamp = f"<t:{int(created_at.timestamp())}:f>" if created_at else "data indisponivel"
        item_label = format_vip_name(sku, item_name) if sku else item_name
        lines.append(
            f"**{index}. {item_label}** • {format_currency_amount('essencia', price)}\n"
            f"Comprador: <@{buyer_id}> • Data: {timestamp}"
        )

    view = AdminVipTransactionsView(lines, interaction.user.id, total, usuario)
    await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)
