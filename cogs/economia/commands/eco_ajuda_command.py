from __future__ import annotations
from ..cog import *


MONEY_SECTION_EMOJI = "<:aguaviva:1512208133177741433>"
EARN_SECTION_EMOJI = "<:golfinho:1512208280359932045>"
SHOP_SECTION_EMOJI = "<:palmolive:1512208558622638281>"


def _fmt_entry_label(entry: dict, guild: discord.Guild) -> str:
    if entry["kind"] == "currency":
        return format_currency_amount(entry["currency"], int(entry["amount"]))

    role = guild.get_role(int(entry["role_id"]))
    role_name = role.name if role else str(entry["role_id"])
    return f"VIP {role_name} por {entry.get('days', 30)} dias"


def _default_odds_lines(setting: dict, guild: discord.Guild) -> list[str]:
    entries = setting.get("entries", [])
    total_weight = sum(int(entry.get("weight", 0)) for entry in entries) or 1
    return [
        f"- `{(int(entry.get('weight', 0)) / total_weight) * 100:.0f}%` - {_fmt_entry_label(entry, guild)}"
        for entry in entries
        if int(entry.get("weight", 0)) > 0
    ]


async def _odds_lines(self, box_id: str, default_setting: dict, guild: discord.Guild) -> list[str]:
    lines = await asyncio.to_thread(self._build_odds_lines, box_id, guild)
    if lines:
        return lines
    return _default_odds_lines(default_setting, guild)


ECO_HELP_META = {
    "inicio": {
        "label": "Início",
        "description": "Voltar para a visão geral.",
        "emoji": "🏠",
    },
    "resumo": {
        "label": "Resumo",
        "description": "Moedas e funcionamento básico.",
        "emoji": MONEY_SECTION_EMOJI,
    },
    "ganhos": {
        "label": "Como ganhar",
        "description": "Moedas por mensagem e call.",
        "emoji": EARN_SECTION_EMOJI,
    },
    "lootboxes": {
        "label": "Lootboxes",
        "description": "Preços e chances das caixas.",
        "emoji": LOOTBOX_EMOJI,
    },
    "loja": {
        "label": "Loja e inventário",
        "description": "VIPs temporários e itens guardados.",
        "emoji": SHOP_SECTION_EMOJI,
    },
    "bonus": {
        "label": "Bônus VIP",
        "description": "Ganhos extras para VIPs ativos.",
        "emoji": "✨",
    },
    "comandos": {
        "label": "Comandos úteis",
        "description": "Atalhos principais do /eco.",
        "emoji": "⌨️",
    },
}


def _build_eco_help_overview() -> discord.Embed:
    embed = discord.Embed(
        title="Sistema de Economia - `/eco`",
        description=(
            "*O sistema de economia recompensa quem participa do servidor por chat e por call. "
            "Com essas moedas, você pode comprar lootboxes, juntar Essência e conseguir VIPs temporários.*\n\n"
            "Escolha uma categoria no menu abaixo para navegar pelo guia."
        ),
        color=discord.Color.gold(),
    )
    for key, data in ECO_HELP_META.items():
        if key == "inicio":
            continue
        embed.add_field(
            name=f"{data['emoji']} {data['label']}",
            value=data["description"],
            inline=True,
        )
    embed.set_footer(text="Os ganhos do inventário foram mantidos da versão de testes")
    return embed


async def _build_eco_help_embeds(self, guild: discord.Guild) -> dict[str, discord.Embed]:
    common = LOOTBOX_STORE_ITEMS["loot_common"]
    premium = LOOTBOX_STORE_ITEMS["loot_premium"]
    common_odds = await _odds_lines(self, "loot_common", LOOT_COMMON_DEFAULT, guild)
    premium_odds = await _odds_lines(self, "loot_premium", LOOT_PREMIUM_DEFAULT, guild)

    intro = discord.Embed(
        title=f"⏜⌢ ᐥ{MONEY_SECTION_EMOJI}  Moedas",
        description=(
            f"て﹒**Eter**﹒ {CURRENCY_EMOJIS['eter']}\n"
            "> É a moeda inicial da economia. Você ganha Eter conversando no canal de economia/progresso ou ficando ativo em call.\n\n"
            f"て﹒**Essência**﹒ {CURRENCY_EMOJIS['essencia']}\n"
            "> É usada para comprar VIPs temporários na loja.\n\n"
            f"て﹒**Cristal de Essência**﹒{CURRENCY_EMOJIS['cristal_essencia']}\n"
            "> É uma moeda mais rara, usada principalmente para comprar Lootbox Premium."
        ),
        color=discord.Color.from_rgb(83, 211, 201),
    )

    earn = discord.Embed(
        title=f"݂⠀ ۫ ꒰   ݁  Formas de adquirir Eter : .  ۫  ༷  {EARN_SECTION_EMOJI} 𓈒",
        description=(
            "- ***Por mensagem***\n\n"
            f"> 𓈒 Você ganha {format_currency_amount('eter', 1)} ao enviar uma mensagem no chat.\n"
            "> 𓈒 A mensagem precisa ter pelo menos **3** caracteres úteis.\n"
            "> 𓈒 Existe um __cooldown__: você só ganha Eter por mensagem a cada **5 segundos**.\n"
            f"> 𓈒 Atualmente, o ganho por mensagem funciona apenas no canal: <#{CHAT_COUNT_CHANNEL_ID}>\n\n"
            "- ***Por call***\n\n"
            f"> A cada **10 segundos válidos** em call, você recebe: {format_currency_amount('eter', 1)}\n"
            "> Para ser considerada válida, a call precisa ter:\n"
            "> 𓈒 pelo menos **2 pessoas ativas** no canal;\n"
            "> 𓈒 você não estar mutado;\n"
            "> 𓈒 você não estar surdo;\n"
            "> 𓈒 você não estar no canal AFK.\n\n"
            "*Exemplos: 10s = `1 Eter` • 1min = `6 Eter` • 10min = `60 Eter` • 1h = `360 Eter`*"
        ),
        color=discord.Color.green(),
    )

    boxes = discord.Embed(
        title=f"⏜⌢ ᐥ{LOOTBOX_EMOJI}  Lootboxes",
        description=(
            "*Com Eter, você pode comprar Lootbox Comum. Ela serve para conseguir Essência e Cristais de Essência.*\n\n"
            f"A **{format_lootbox_name(common['name'])}** custa {format_currency_amount(common['cost_currency'], common['cost_amount'])}.\n\n"
            f"A **{format_lootbox_name(premium['name'])}** custa {format_currency_amount(premium['cost_currency'], premium['cost_amount'])}."
        ),
        color=discord.Color.blurple(),
    )
    common_odds_text = "\n".join(f"> {line}" for line in common_odds)
    premium_odds_text = "\n".join(f"> {line}" for line in premium_odds)
    boxes.add_field(name=f"Chances da {format_lootbox_name('Lootbox Comum')}", value=common_odds_text, inline=False)
    boxes.add_field(name=f"Chances da {format_lootbox_name('Lootbox Premium')}", value=premium_odds_text, inline=False)

    shop_lines = []
    for sku, item in SHOP_ITEMS_DEFAULT.items():
        shop_lines.append(f"> - **{format_vip_name(sku)}**: {format_currency_amount('essencia', item['price_essencia'])}")
    shop = discord.Embed(
        title=f"⏜⌢ ᐥ{SHOP_SECTION_EMOJI}  Loja de VIPs",
        description=(
            "*Você pode usar Essência para comprar VIPs temporários.*\n\n"
            "**Tabela de valores:**\n"
            + "\n".join(shop_lines)
            + "\n\n"
            "*Os VIPs comprados ou ganhos ficam guardados no inventário. Eles não ativam automaticamente.*\n\n"
            "> Use `/eco inventario` para ativar ou doar um VIP. Ao ativar, o tempo começa imediatamente. "
            "__Doações são irreversíveis.__"
        ),
        color=discord.Color.dark_teal(),
    )

    bonus = discord.Embed(
        title="✨ Bônus de Economia",
        description=(
            "VIPs ativos aumentam seus ganhos da economia. Se você tiver mais de um VIP, vale apenas o maior bônus.\n\n"
            f"**{format_vip_name('vip_berserk_30d')}**\n"
            f"- `+5%` em pontuações de chat, voz e eventos.\n"
            f"- `+5%` no {format_currency_label('eter')} ganho por mensagem/call.\n"
            "- `+5%` nas moedas recebidas ao abrir lootboxes.\n\n"
            f"**{format_vip_name('vip_mugetsu_30d')}**\n"
            f"- `+10%` em pontuações de chat, voz e eventos.\n"
            f"- `+10%` no {format_currency_label('eter')} ganho por mensagem/call.\n"
            "- `+10%` nas moedas recebidas ao abrir lootboxes.\n\n"
            f"**{format_vip_name('vip_monarch_30d')}**\n"
            f"- `+15%` em pontuações de chat, voz e eventos.\n"
            f"- `+15%` no {format_currency_label('eter')} ganho por mensagem/call.\n"
            "- `+15%` nas moedas recebidas ao abrir lootboxes.\n\n"
            "**Boost de Guilda**\n"
            "- A temporada mensal de guildas desbloqueia bônus no Eter pessoal dos membros.\n"
            "- Metas: `50k = +5%`, `60k = +10%`, `75k = +15%`, `90k = +20%`, `100k = +25%`.\n"
            "- Esse bônus soma com o VIP apenas nos ganhos de mensagem/call."
        ),
        color=discord.Color.dark_embed(),
    )
    bonus.set_footer(text="Bônus fracionados de moedas acumulam até virar uma moeda inteira extra")

    commands = discord.Embed(
        title="Comandos úteis",
        description=(
            "> `/eco saldo` - mostra seu saldo e progresso.\n"
            "> `/eco inventario` - mostra moedas, caixas e VIPs guardados.\n"
            "> `/eco loja` - abre a loja de lootboxes e VIPs.\n"
            "> `/eco abrir_comum` - abre Lootbox Comum do inventário.\n"
            "> `/eco abrir_premium` - abre Lootbox Premium do inventário.\n"
            "> `/eco ajuda` - mostra este guia.\n"
            "> `/duplicar duracao:2h` - admin: ativa ganho 2x de Éter por tempo limitado. Use `h` ou `d`."
        ),
        color=discord.Color.purple(),
    )
    commands.set_footer(text="Obs: os ganhos do inventário foram mantidos da versão de testes")

    return {
        "resumo": intro,
        "ganhos": earn,
        "lootboxes": boxes,
        "loja": shop,
        "bonus": bonus,
        "comandos": commands,
    }


class EcoHelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=data["label"],
                description=data["description"],
                emoji=data["emoji"],
                value=key,
            )
            for key, data in ECO_HELP_META.items()
        ]
        super().__init__(
            placeholder="Escolha uma categoria da economia...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view: EcoHelpView = self.view
        category = self.values[0]
        embed = _build_eco_help_overview() if category == "inicio" else view.embeds[category]
        await interaction.response.edit_message(embed=embed, view=view)


class EcoHelpView(discord.ui.View):
    def __init__(self, author_id: int, embeds: dict[str, discord.Embed]):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.embeds = embeds
        self.add_item(EcoHelpSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente quem abriu o painel pode usar este menu.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


async def execute(self, interaction: discord.Interaction):
    if interaction.guild is None:
        return await interaction.response.send_message("Use este comando dentro de um servidor.", ephemeral=True)

    embeds = await _build_eco_help_embeds(self, interaction.guild)
    await interaction.response.send_message(
        embed=_build_eco_help_overview(),
        view=EcoHelpView(interaction.user.id, embeds),
        ephemeral=True,
    )
