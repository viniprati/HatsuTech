from __future__ import annotations

from ..cog import *
from .anunciar_command import broadcast_embed


def build_store_announcement_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌐 Nova Loja Global de VIPs",
        description=(
            "A versão `1.0.3` do HatsuTech chegou com uma nova forma de comprar VIPs!\n\n"
            "A **Loja Global de VIPs** possui um estoque único e exclusivo da comunidade Animes Café."
        ),
        color=discord.Color.from_rgb(212, 172, 55),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(
        name="🛒 Novo comando",
        value="Use `/eco loja_global` para consultar o estoque e comprar seu VIP.",
        inline=False,
    )
    embed.add_field(
        name="📦 Estoque inicial",
        value=(
            "<:certo:1555211164114223115> <:Vip_Berserk:1351063519684202549> **Berserk:** `5/5`\n"
            "<:certo:1555211164114223115> <:Vip_Mugetsu:1351063776434196480> **Mugetsu:** `5/5`\n"
            "<:certo:1555211164114223115> <:Vip_Monarch:1351063576345055383> **Monarch:** `5/5`"
        ),
        inline=False,
    )
    embed.add_field(
        name="💰 Valores",
        value=(
            "<:Vip_Berserk:1351063519684202549> **Berserk — 30 dias:** "
            "<:planta:1512208216295997500> `2.000` Essências\n"
            "<:Vip_Mugetsu:1351063776434196480> **Mugetsu — 30 dias:** "
            "<:planta:1512208216295997500> `3.000` Essências\n"
            "<:Vip_Monarch:1351063576345055383> **Monarch — 30 dias:** "
            "<:planta:1512208216295997500> `5.000` Essências"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎒 Compra e inventário",
        value=(
            "O VIP comprado não é ativado automaticamente. Ele fica guardado no seu inventário, onde você pode "
            "**ativá-lo** ou **doá-lo** usando `/eco inventario`."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔄 O que mudou na loja antiga?",
        value=(
            "A compra de VIPs saiu de `/eco loja`. A loja antiga continua dedicada a "
            "**Lootboxes, Chances e Inventário**."
        ),
        inline=False,
    )
    embed.add_field(
        name="ℹ️ Importante",
        value=(
            "Cada compra reduz o estoque disponível para a comunidade. Não existe reposição automática ou "
            "calendário fixo: o **restock acontece conforme decisão da Administração**."
        ),
        inline=False,
    )
    embed.set_footer(text="HatsuTech • Atualização 1.0.3 • Use /notificacao para cancelar")
    return embed


async def execute(self, interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    embed = build_store_announcement_embed()
    await broadcast_embed(
        self,
        interaction,
        embed,
        broadcast_type="global_vip_store_1_0_3",
        command_name="/anuncio_loja",
    )
