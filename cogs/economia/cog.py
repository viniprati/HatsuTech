import logging
import random
import re
import time
import copy
import asyncio
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands, tasks
from pymongo import ReturnDocument

from database import (
    eco_admin_logs_col,
    eco_limits_col,
    eco_logs_col,
    eco_settings_col,
    eco_shop_col,
    eco_users_col,
    eco_vip_transactions_col,
    is_db_online,
    temp_col,
)
from utils import BOT_OWNER_ID, check_owner_or_perm, ensure_db_online, get_data_guild_id

try:
    from config import CHAT_COUNT_CHANNEL_ID, ECONOMY_LOG_CHANNEL_ID
except ImportError:
    CHAT_COUNT_CHANNEL_ID = 1117559464363573358
    ECONOMY_LOG_CHANNEL_ID = 0

SERVER_OWNER_FIXED_ID = 459064218088374293
ECONOMY_EARN_CHANNEL_IDS = {CHAT_COUNT_CHANNEL_ID}
EVENTS_TEAM_ROLE_ID = 1275958325665599571
ECONOMY_ADMIN_AUDIT_DM_USER_IDS = (BOT_OWNER_ID, SERVER_OWNER_FIXED_ID)

log = logging.getLogger(__name__)

BERSERK_VIP_ID = 999723165225857074
MUGETSU_VIP_ID = 1121511055059861524
MONARCH_VIP_ID = 1351596017631494195
VIP_STORE_MAX_STOCK = 1
VIP_STORE_POLICY_VERSION = "vip_inventory_stock_1_v1"
VIP_TRANSACTION_BACKFILL_VERSION = "vip_transactions_from_shop_buy_v1"

SHOP_ITEMS_DEFAULT = {
    "vip_berserk_30d": {
        "name": "VIP Berserk 30 dias",
        "role_id": BERSERK_VIP_ID,
        "price_essencia": 2000,
        "stock": VIP_STORE_MAX_STOCK,
        "max_stock": VIP_STORE_MAX_STOCK,
        "enabled": True,
    },
    "vip_mugetsu_30d": {
        "name": "VIP Mugetsu 30 dias",
        "role_id": MUGETSU_VIP_ID,
        "price_essencia": 3000,
        "stock": VIP_STORE_MAX_STOCK,
        "max_stock": VIP_STORE_MAX_STOCK,
        "enabled": True,
    },
    "vip_monarch_30d": {
        "name": "VIP Monarch 30 dias",
        "role_id": MONARCH_VIP_ID,
        "price_essencia": 5000,
        "stock": VIP_STORE_MAX_STOCK,
        "max_stock": VIP_STORE_MAX_STOCK,
        "enabled": True,
    },
}

VIP_INVENTORY_ITEMS = {
    sku: {
        "name": item["name"],
        "role_id": int(item["role_id"]),
        "days": 30,
        "field": f"vip_inventory.{sku}",
    }
    for sku, item in SHOP_ITEMS_DEFAULT.items()
}
VIP_SKU_BY_ROLE_ID = {item["role_id"]: sku for sku, item in VIP_INVENTORY_ITEMS.items()}
VIP_EMOJIS = {
    "vip_berserk_30d": "<:Vip_Berserk:1351063519684202549>",
    "vip_mugetsu_30d": "<:Vip_Mugetsu:1351063776434196480>",
    "vip_monarch_30d": "<:Vip_Monarch:1351063576345055383>",
}
VIP_ECONOMY_BONUSES = {
    BERSERK_VIP_ID: ("vip_berserk_30d", 5),
    MUGETSU_VIP_ID: ("vip_mugetsu_30d", 10),
    MONARCH_VIP_ID: ("vip_monarch_30d", 15),
}
VIP_SKU_BY_NAME = {
    "VIP Berserk 30 dias": "vip_berserk_30d",
    "VIP Mugetsu 30 dias": "vip_mugetsu_30d",
    "VIP Monarch 30 dias": "vip_monarch_30d",
}
LOOTBOX_EMOJI = "<:controle:1512208193760268419>"

LOOTBOX_STORE_ITEMS = {
    "loot_common": {
        "name": "Lootbox Comum",
        "inventory_key": "common_box",
        "cost_currency": "eter",
        "cost_amount": 500,
    },
    "loot_premium": {
        "name": "Lootbox Premium",
        "inventory_key": "premium_box",
        "cost_currency": "cristal_essencia",
        "cost_amount": 5,
    },
}

LOOT_COMMON_DEFAULT = {
    "_id": "loot_common",
    "name": "Lootbox Comum",
    "cost_currency": "eter",
    "cost_amount": 500,
    "entries": [
        {"kind": "currency", "currency": "essencia", "amount": 10, "weight": 50},
        {"kind": "currency", "currency": "essencia", "amount": 50, "weight": 30},
        {"kind": "currency", "currency": "cristal_essencia", "amount": 1, "weight": 10},
        {"kind": "currency", "currency": "cristal_essencia", "amount": 3, "weight": 5},
        {"kind": "currency", "currency": "essencia", "amount": 200, "weight": 3},
        {"kind": "currency", "currency": "essencia", "amount": 300, "weight": 1},
        {"kind": "currency", "currency": "cristal_essencia", "amount": 10, "weight": 1},
    ],
}

OLD_LOOT_COMMON_ENTRIES = [
    {"kind": "currency", "currency": "essencia", "amount": 10, "weight": 48},
    {"kind": "currency", "currency": "essencia", "amount": 50, "weight": 30},
    {"kind": "currency", "currency": "cristal_essencia", "amount": 1, "weight": 10},
    {"kind": "currency", "currency": "cristal_essencia", "amount": 3, "weight": 5},
    {"kind": "currency", "currency": "essencia", "amount": 200, "weight": 4},
    {"kind": "currency", "currency": "essencia", "amount": 300, "weight": 2},
    {"kind": "currency", "currency": "cristal_essencia", "amount": 10, "weight": 1},
]

LOOT_PREMIUM_DEFAULT = {
    "_id": "loot_premium",
    "name": "Lootbox Premium",
    "cost_currency": "cristal_essencia",
    "cost_amount": 5,
    "entries": [
        {"kind": "currency", "currency": "essencia", "amount": 150, "weight": 30},
        {"kind": "currency", "currency": "essencia", "amount": 200, "weight": 20},
        {"kind": "currency", "currency": "essencia", "amount": 300, "weight": 15},
        {"kind": "currency", "currency": "cristal_essencia", "amount": 3, "weight": 15},
        {"kind": "currency", "currency": "cristal_essencia", "amount": 5, "weight": 10},
        {"kind": "vip_temp", "role_id": BERSERK_VIP_ID, "days": 30, "weight": 5},
        {"kind": "vip_temp", "role_id": MUGETSU_VIP_ID, "days": 30, "weight": 3},
        {"kind": "vip_temp", "role_id": MONARCH_VIP_ID, "days": 30, "weight": 2},
    ],
}

VALID_ECONOMY_CURRENCIES = {"eter", "essencia", "cristal_essencia"}
VALID_REWARD_KINDS = {"currency", "vip_temp"}
VIP_ROLE_IDS = {BERSERK_VIP_ID, MUGETSU_VIP_ID, MONARCH_VIP_ID}
MIN_CHAT_USEFUL_CHARS = 3
ECONOMY_ACTION_COOLDOWN_SECONDS = 3
LOOTBOX_MAX_PURCHASE_QTY = 100
ECONOMY_BOOST_SETTINGS_PREFIX = "economy_boost:"

CURRENCY_EMOJIS = {
    "eter": "<:gota:1512208257396248666>",
    "essencia": "<:planta:1512208216295997500>",
    "cristal_essencia": "<:borboleta:1512208174306824332>",
}
CURRENCY_NAMES = {
    "eter": "Eter",
    "essencia": "Essência",
    "cristal_essencia": "Cristal de Essência",
}


def format_currency_name(currency: str) -> str:
    return CURRENCY_NAMES.get(currency, currency)


def format_currency_label(currency: str) -> str:
    emoji = CURRENCY_EMOJIS.get(currency)
    name = format_currency_name(currency)
    return f"{emoji} {name}" if emoji else name


def format_currency_amount(currency: str, amount: int) -> str:
    return f"{CURRENCY_EMOJIS.get(currency, '')} `{int(amount)}` {format_currency_name(currency)}".strip()


def format_currency_balance_lines(doc: dict) -> str:
    return "\n".join(
        f"{format_currency_label(currency)}: `{int(doc.get(currency, 0))}`"
        for currency in ("eter", "essencia", "cristal_essencia")
    )


def format_vip_name(sku: str, name: str | None = None) -> str:
    item_name = name or VIP_INVENTORY_ITEMS.get(sku, {}).get("name") or SHOP_ITEMS_DEFAULT.get(sku, {}).get("name") or sku
    emoji = VIP_EMOJIS.get(sku)
    return f"{emoji} {item_name}" if emoji else item_name


def format_vip_name_from_item(item: dict, fallback_sku: str | None = None) -> str:
    sku = fallback_sku or VIP_SKU_BY_NAME.get(str(item.get("name", "")))
    return format_vip_name(sku, item.get("name")) if sku else str(item.get("name", fallback_sku or "VIP"))


def format_lootbox_name(name: str) -> str:
    return f"{LOOTBOX_EMOJI} {name}"


def get_member_vip_bonus(member) -> dict:
    best = {"sku": None, "percent": 0}
    if not member:
        return best
    for role in getattr(member, "roles", []):
        bonus = VIP_ECONOMY_BONUSES.get(role.id)
        if bonus and bonus[1] > best["percent"]:
            best = {"sku": bonus[0], "percent": bonus[1]}
    return best


def format_vip_bonus_label(bonus: dict) -> str:
    if not bonus.get("percent"):
        return "Sem bônus VIP"
    return f"{format_vip_name(bonus.get('sku'))} `+{bonus['percent']}%`"


def format_guild_bonus_label(bonus: dict) -> str:
    if not bonus.get("percent"):
        return "Sem bônus de guilda"
    guild_data = bonus.get("guild") or {}
    guild_name = guild_data.get("name", "Guilda")
    guild_emoji = guild_data.get("emoji", "🏰")
    monthly_xp = int(bonus.get("monthly_xp", 0) or 0)
    return f"{guild_emoji} {guild_name} `+{bonus['percent']}%` • `{monthly_xp:,}` XP mensal".replace(",", ".")


class AdminResetConfirmView(discord.ui.View):
    def __init__(self, cog, author_id: int, reset_payload: dict):
        super().__init__(timeout=60)
        self.cog = cog
        self.author_id = author_id
        self.reset_payload = reset_payload

    async def _deny_foreign(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente quem executou o comando pode confirmar.", ephemeral=True)
            return True
        return False

    @discord.ui.button(label="Confirmar Reset", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._deny_foreign(interaction):
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        result = await self.cog.execute_admin_reset(interaction, self.reset_payload)
        await interaction.followup.send(result, ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._deny_foreign(interaction):
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Reset cancelado.", view=self, embed=None)
        self.stop()


class EcoStoreCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Lootboxes", value="lootboxes", description="Compre caixas com moedas", emoji=LOOTBOX_EMOJI),
            discord.SelectOption(label="VIPs", value="vips", description="Compre VIPs temporários", emoji=VIP_EMOJIS["vip_berserk_30d"]),
            discord.SelectOption(label="Chances", value="chances", description="Veja odds das lootboxes", emoji=LOOTBOX_EMOJI),
            discord.SelectOption(label="Inventario", value="inventory", description="Veja moedas e caixas", emoji=LOOTBOX_EMOJI),
        ]
        super().__init__(placeholder="Selecione uma categoria", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        view: EcoStoreView = self.view
        view.current_category = self.values[0]
        view.last_feedback = None
        view.sync_controls()
        await interaction.response.edit_message(embed=await view.build_embed(interaction.guild), view=view)


class LootboxQuantityModal(discord.ui.Modal):
    def __init__(self, store_view, box_id: str, source_interaction: discord.Interaction):
        item = LOOTBOX_STORE_ITEMS.get(box_id, {})
        box_name = item.get("name", "Lootbox")
        super().__init__(title=f"Comprar {box_name}")
        self.store_view = store_view
        self.box_id = box_id
        self.source_interaction = source_interaction
        self.quantity = discord.ui.TextInput(
            label="Quantidade",
            placeholder="Ex: 1, 5, 10",
            required=True,
            max_length=4,
        )
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction):
        await self.store_view.process_lootbox_modal_submit(
            interaction,
            self.box_id,
            str(self.quantity.value),
            self.source_interaction,
        )


class EcoStoreView(discord.ui.View):
    def __init__(self, cog, author_id: int, guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.current_category = "lootboxes"
        self.last_feedback: str | None = None
        self.add_item(EcoStoreCategorySelect())
        self.sync_controls()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente quem abriu a loja pode usar estes botoes.", ephemeral=True)
            return False
        return True

    def sync_controls(self):
        loot = self.current_category == "lootboxes"
        vips = self.current_category == "vips"
        chances = self.current_category == "chances"
        inventory = self.current_category == "inventory"

        self.action_one.disabled = inventory
        self.action_two.disabled = inventory
        self.action_three.disabled = inventory

        if loot:
            self.action_one.label = "Comprar Comum"
            self.action_two.label = "Comprar Premium"
            self.action_three.label = "Atualizar"
        elif vips:
            self.action_one.label = "Comprar Berserk"
            self.action_two.label = "Comprar Mugetsu"
            self.action_three.label = "Comprar Monarch"
        elif chances:
            self.action_one.label = "Odds Comum"
            self.action_two.label = "Odds Premium"
            self.action_three.label = "Atualizar"
        else:
            self.action_one.label = "-"
            self.action_two.label = "-"
            self.action_three.label = "-"

    async def _refresh_message(self, interaction: discord.Interaction):
        embed = await self.build_embed(interaction.guild)
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except discord.HTTPException:
            pass

    async def _run_vip_purchase(self, interaction: discord.Interaction, sku: str):
        if not interaction.response.is_done():
            await interaction.response.defer()
        self.last_feedback = await self.cog._purchase_item_result(interaction, sku)
        await self._refresh_message(interaction)
        try:
            await interaction.followup.send(self.last_feedback, ephemeral=True)
        except discord.HTTPException:
            pass

    async def process_lootbox_modal_submit(
        self,
        interaction: discord.Interaction,
        box_id: str,
        quantity_raw: str,
        source_interaction: discord.Interaction,
    ):
        raw = (quantity_raw or "").strip()
        if not raw:
            return await interaction.response.send_message("Informe uma quantidade para comprar.", ephemeral=True)
        try:
            qty = int(raw)
        except ValueError:
            return await interaction.response.send_message("Quantidade invalida. Digite apenas numeros inteiros.", ephemeral=True)

        if qty <= 0:
            return await interaction.response.send_message("A quantidade precisa ser maior que zero.", ephemeral=True)
        if qty > LOOTBOX_MAX_PURCHASE_QTY:
            return await interaction.response.send_message(
                f"Quantidade maxima por compra: `{LOOTBOX_MAX_PURCHASE_QTY}`.",
                ephemeral=True,
            )

        feedback = await self.cog._buy_lootbox_for_inventory(interaction, box_id, qty)
        self.last_feedback = feedback
        await interaction.response.send_message(feedback, ephemeral=True)
        await self._refresh_message(source_interaction)

    async def build_embed(self, guild: discord.Guild) -> discord.Embed:
        doc = await asyncio.to_thread(self.cog._get_user_doc, self.author_id, self.guild_id)
        common_box = int(doc.get("common_box", 0))
        premium_box = int(doc.get("premium_box", 0))

        title_map = {
            "lootboxes": "Loja - Lootboxes",
            "vips": "Loja - VIPs",
            "chances": "Loja - Chances",
            "inventory": "Loja - Minhas Moedas e Inventario",
        }
        embed = discord.Embed(title=title_map.get(self.current_category, "Loja"), color=discord.Color.gold())

        if self.current_category == "lootboxes":
            common = LOOTBOX_STORE_ITEMS["loot_common"]
            premium = LOOTBOX_STORE_ITEMS["loot_premium"]
            embed.description = (
                f"**{format_lootbox_name(common['name'])}**\n"
                f"Preco: {format_currency_amount(common['cost_currency'], common['cost_amount'])}\n"
                f"Inventario atual: `{common_box}`\n\n"
                f"**{format_lootbox_name(premium['name'])}**\n"
                f"Preco: {format_currency_amount(premium['cost_currency'], premium['cost_amount'])}\n"
                f"Inventario atual: `{premium_box}`"
            )
        elif self.current_category == "vips":
            shop = await asyncio.to_thread(eco_shop_col.find_one, {"_id": "main_shop"}) or {"items": {}}
            limits = await asyncio.to_thread(
                eco_limits_col.find_one, {"_id": self.cog._limits_doc_id(self.author_id, self.guild_id)}
            ) or {}
            purchased = set(limits.get("purchased_skus", []))
            lines = []
            for sku in ("vip_berserk_30d", "vip_mugetsu_30d", "vip_monarch_30d"):
                item = shop.get("items", {}).get(sku) or SHOP_ITEMS_DEFAULT.get(sku, {})
                status = (
                    "Comprado nesta rodada/reposicao"
                    if sku in purchased
                    else ("Disponivel" if item.get("enabled", True) and item.get("stock", 0) > 0 else "Indisponivel")
                )
                lines.append(
                    f"**{format_vip_name_from_item(item, sku)}**\n"
                    f"Preco: {format_currency_amount('essencia', int(item.get('price_essencia', 0)))}\n"
                    f"Estoque: `{int(item.get('stock', 0))}`\n"
                    f"Status: `{status}`"
                )
            embed.description = (
                "VIPs comprados ficam guardados no inventario e nao sao ativados automaticamente. "
                "Use `/eco inventario` para ativar ou doar.\n\n"
                + "\n\n".join(lines)
            )
        elif self.current_category == "chances":
            common_lines = await asyncio.to_thread(self.cog._build_odds_lines, "loot_common", guild)
            premium_lines = await asyncio.to_thread(self.cog._build_odds_lines, "loot_premium", guild)
            embed.add_field(name=format_lootbox_name("Lootbox Comum"), value="\n".join(common_lines) if common_lines else "Sem dados.", inline=False)
            embed.add_field(name=format_lootbox_name("Lootbox Premium"), value="\n".join(premium_lines) if premium_lines else "Sem dados.", inline=False)
        else:
            embed.description = (
                f"{format_currency_balance_lines(doc)}\n\n"
                f"{format_lootbox_name('Lootbox Comum')}: `{common_box}`\n"
                f"{format_lootbox_name('Lootbox Premium')}: `{premium_box}`"
            )

        embed.add_field(
            name="Seu saldo",
            value=format_currency_balance_lines(doc),
            inline=False,
        )
        if self.last_feedback:
            embed.set_footer(text=self.last_feedback)
        return embed

    @discord.ui.button(label="Acao 1", style=discord.ButtonStyle.primary, row=1)
    async def action_one(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_category == "lootboxes":
            modal = LootboxQuantityModal(self, "loot_common", interaction)
            return await interaction.response.send_modal(modal)
        elif self.current_category == "vips":
            return await self._run_vip_purchase(interaction, "vip_berserk_30d")
        elif self.current_category == "chances":
            self.last_feedback = "Odds da Lootbox Comum exibidas nesta pagina."
        await self._refresh_message(interaction)

    @discord.ui.button(label="Acao 2", style=discord.ButtonStyle.primary, row=1)
    async def action_two(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_category == "lootboxes":
            modal = LootboxQuantityModal(self, "loot_premium", interaction)
            return await interaction.response.send_modal(modal)
        elif self.current_category == "vips":
            return await self._run_vip_purchase(interaction, "vip_mugetsu_30d")
        elif self.current_category == "chances":
            self.last_feedback = "Odds da Lootbox Premium exibidas nesta pagina."
        await self._refresh_message(interaction)

    @discord.ui.button(label="Acao 3", style=discord.ButtonStyle.success, row=1)
    async def action_three(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_category == "lootboxes":
            self.last_feedback = "Loja atualizada."
        elif self.current_category == "vips":
            return await self._run_vip_purchase(interaction, "vip_monarch_30d")
        elif self.current_category == "chances":
            self.last_feedback = "Chances atualizadas."
        await self._refresh_message(interaction)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class EcoLeaderboardSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        options = [
            discord.SelectOption(label="Eter", value="eter", description="Ranking por Eter", emoji=CURRENCY_EMOJIS["eter"]),
            discord.SelectOption(label="Essência", value="essencia", description="Ranking por Essência", emoji=CURRENCY_EMOJIS["essencia"]),
            discord.SelectOption(label="Cristal de Essência", value="cristal_essencia", description="Ranking por Cristal", emoji=CURRENCY_EMOJIS["cristal_essencia"]),
        ]
        super().__init__(placeholder="Selecione a moeda do leaderboard", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        await interaction.response.defer()
        embed = await self.cog._build_leaderboard_embed(interaction.guild, value)
        await interaction.edit_original_response(embed=embed, view=self.view)


class EcoLeaderboardView(discord.ui.View):
    def __init__(self, cog, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.add_item(EcoLeaderboardSelect(cog))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente quem abriu o painel pode usar este menu.", ephemeral=True)
            return False
        return True


class EcoInventoryView(discord.ui.View):
    def __init__(self, cog, author_id: int, guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente o dono do inventario pode usar estes botoes.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ativar VIP", style=discord.ButtonStyle.success)
    async def activate_vip(self, interaction: discord.Interaction, button: discord.ui.Button):
        options = await self.cog._build_vip_inventory_options(self.author_id, self.guild_id)
        if not options:
            return await interaction.response.send_message("Voce nao possui VIP guardado no inventario.", ephemeral=True)
        embed = discord.Embed(
            title="Ativar VIP",
            description="Selecione um VIP. A confirmacao iniciara o tempo do cargo para voce.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=VipActivateSelectView(self.cog, self.author_id, self.guild_id, options),
            ephemeral=True,
        )

    @discord.ui.button(label="Doar VIP", style=discord.ButtonStyle.primary)
    async def donate_vip(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="Doacao de VIP",
            description=(
                "A doacao transfere um VIP do seu inventario para outro membro.\n\n"
                "**Esta acao e irreversivel.** A equipe staff nao se responsabiliza "
                "por VIPs doados por engano."
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=VipDonationWarningView(self.cog, self.author_id, self.guild_id),
            ephemeral=True,
        )


class VipInventorySelect(discord.ui.Select):
    def __init__(self, mode: str, options: list[discord.SelectOption]):
        self.mode = mode
        placeholder = "Selecione o VIP para ativar" if mode == "activate" else "Selecione o VIP para doar"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        sku = self.values[0]
        item = VIP_INVENTORY_ITEMS[sku]
        if self.mode == "activate":
            embed = discord.Embed(
                title="Confirmar ativacao",
                description=(
                    f"VIP: **{format_vip_name(sku)}**\n"
                    f"Duracao: `{item['days']} dias`\n\n"
                    "Ao confirmar, uma unidade sera consumida do inventario e o prazo comecara agora."
                ),
                color=discord.Color.green(),
            )
            confirm_view = VipActivateConfirmView(view.cog, view.author_id, view.guild_id, sku)
        else:
            embed = discord.Embed(
                title="Escolha o destinatario",
                description=f"VIP selecionado: **{format_vip_name(sku)}**\nSelecione quem recebera o item.",
                color=discord.Color.orange(),
            )
            confirm_view = VipDonationRecipientView(view.cog, view.author_id, view.guild_id, sku)
        await interaction.response.edit_message(embed=embed, view=confirm_view)


class VipActivateSelectView(discord.ui.View):
    def __init__(self, cog, author_id: int, guild_id: int, options: list[discord.SelectOption]):
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.add_item(VipInventorySelect("activate", options))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente o dono do inventario pode ativar este VIP.", ephemeral=True)
            return False
        return True


class VipActivateConfirmView(discord.ui.View):
    def __init__(self, cog, author_id: int, guild_id: int, sku: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.sku = sku
        self.processing = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente o dono do inventario pode confirmar.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar Ativacao", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.processing:
            return await interaction.response.send_message("A ativacao ja esta em processamento.", ephemeral=True)
        self.processing = True
        await interaction.response.defer()
        result = await self.cog._activate_inventory_vip(interaction, self.sku)
        await interaction.edit_original_response(content=result, embed=None, view=None)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Ativacao cancelada.", embed=None, view=None)
        self.stop()


class VipDonationWarningView(discord.ui.View):
    def __init__(self, cog, author_id: int, guild_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente o dono do inventario pode doar.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Estou ciente, continuar", style=discord.ButtonStyle.danger)
    async def continue_donation(self, interaction: discord.Interaction, button: discord.ui.Button):
        options = await self.cog._build_vip_inventory_options(self.author_id, self.guild_id)
        if not options:
            return await interaction.response.edit_message(
                content="Voce nao possui VIP guardado no inventario.",
                embed=None,
                view=None,
            )
        embed = discord.Embed(
            title="Doar VIP - selecionar item",
            description="Escolha qual VIP sera transferido. A ativacao ficara a cargo do destinatario.",
            color=discord.Color.orange(),
        )
        await interaction.response.edit_message(
            embed=embed,
            view=VipDonationSelectView(self.cog, self.author_id, self.guild_id, options),
        )

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Doacao cancelada.", embed=None, view=None)
        self.stop()


class VipDonationSelectView(discord.ui.View):
    def __init__(self, cog, author_id: int, guild_id: int, options: list[discord.SelectOption]):
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.add_item(VipInventorySelect("donate", options))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente o dono do inventario pode doar.", ephemeral=True)
            return False
        return True


class VipRecipientSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Selecione o membro que recebera o VIP", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        selected = self.values[0]
        recipient = await view.cog.get_guild_member_safe(interaction.guild, selected.id)
        if not recipient or recipient.bot:
            return await interaction.response.send_message("Selecione um membro valido do servidor.", ephemeral=True)
        if recipient.id == view.author_id:
            return await interaction.response.send_message("Use **Ativar VIP** para utilizar o item em voce.", ephemeral=True)
        item = VIP_INVENTORY_ITEMS[view.sku]
        embed = discord.Embed(
            title="Confirmar doacao",
            description=(
                f"VIP: **{format_vip_name(view.sku)}**\n"
                f"Destinatario: {recipient.mention}\n\n"
                "**A transferencia e irreversivel e nao sera revertida pela staff.**"
            ),
            color=discord.Color.red(),
        )
        await interaction.response.edit_message(
            embed=embed,
            view=VipDonationConfirmView(view.cog, view.author_id, view.guild_id, view.sku, recipient),
        )


class VipDonationRecipientView(discord.ui.View):
    def __init__(self, cog, author_id: int, guild_id: int, sku: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.sku = sku
        self.add_item(VipRecipientSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente o dono do inventario pode doar.", ephemeral=True)
            return False
        return True


class VipDonationConfirmView(discord.ui.View):
    def __init__(self, cog, author_id: int, guild_id: int, sku: str, recipient: discord.Member):
        super().__init__(timeout=120)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.sku = sku
        self.recipient = recipient
        self.processing = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente o dono do inventario pode confirmar.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar Doacao", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.processing:
            return await interaction.response.send_message("A doacao ja esta em processamento.", ephemeral=True)
        self.processing = True
        await interaction.response.defer()
        result = await self.cog._transfer_inventory_vip(interaction, self.sku, self.recipient)
        await interaction.edit_original_response(content=result, embed=None, view=None)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Doacao cancelada.", embed=None, view=None)
        self.stop()


class EconomySystem(commands.Cog):
    eco = app_commands.Group(name="eco", description="Sistema de economia e lootboxes")
    eco_admin = app_commands.Group(name="eco_admin", description="Administracao da economia")

    def __init__(self, bot):
        self.bot = bot
        self.chat_last_earn = {}
        self.action_last_used = {}
        self.voice_eligible_since = {}
        self.economy_boosts = {}
        self.voice_tick.start()

    async def cog_load(self):
        await asyncio.to_thread(self.ensure_defaults)
        await asyncio.to_thread(self._load_active_economy_boosts)

    def cog_unload(self):
        self.voice_tick.cancel()

    def ensure_defaults(self):
        if not ECONOMY_EARN_CHANNEL_IDS:
            log.error("CHAT_COUNT_CHANNEL_ID nao configurado; ganho de Eter por mensagem ficara desativado.")

        common = eco_settings_col.find_one({"_id": "loot_common"})
        if not common:
            eco_settings_col.insert_one(copy.deepcopy(LOOT_COMMON_DEFAULT))
        elif common.get("entries") == OLD_LOOT_COMMON_ENTRIES:
            eco_settings_col.update_one(
                {"_id": "loot_common"},
                {"$set": {"entries": copy.deepcopy(LOOT_COMMON_DEFAULT["entries"]), "updated_at": datetime.now(timezone.utc)}},
            )

        if not eco_settings_col.find_one({"_id": "loot_premium"}):
            eco_settings_col.insert_one(copy.deepcopy(LOOT_PREMIUM_DEFAULT))
        shop = eco_shop_col.find_one({"_id": "main_shop"})
        if not shop:
            eco_shop_col.insert_one(
                {
                    "_id": "main_shop",
                    "items": copy.deepcopy(SHOP_ITEMS_DEFAULT),
                    "vip_stock_policy": VIP_STORE_POLICY_VERSION,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
        else:
            item_updates = {}
            stored_items = shop.get("items", {})
            policy_migration = shop.get("vip_stock_policy") != VIP_STORE_POLICY_VERSION
            for sku, defaults in SHOP_ITEMS_DEFAULT.items():
                stored = stored_items.get(sku)
                if not stored:
                    item_updates[f"items.{sku}"] = copy.deepcopy(defaults)
                    continue
                try:
                    current_stock = max(0, int(stored.get("stock", defaults["stock"])))
                except (TypeError, ValueError):
                    current_stock = int(defaults["stock"])
                    item_updates[f"items.{sku}.stock"] = current_stock
                if stored.get("max_stock") != defaults["max_stock"]:
                    item_updates[f"items.{sku}.max_stock"] = int(defaults["max_stock"])
                if policy_migration:
                    item_updates[f"items.{sku}.stock"] = int(defaults["stock"])
                elif current_stock > defaults["max_stock"]:
                    item_updates[f"items.{sku}.stock"] = int(defaults["max_stock"])
            if policy_migration:
                item_updates["vip_stock_policy"] = VIP_STORE_POLICY_VERSION
            if item_updates:
                item_updates["updated_at"] = datetime.now(timezone.utc)
                updated = eco_shop_col.update_one({"_id": "main_shop"}, {"$set": item_updates})
                if policy_migration and getattr(updated, "acknowledged", False):
                    eco_limits_col.update_many({}, {"$set": {"purchased_skus": []}})
        self._backfill_vip_purchase_transactions()
        self.validate_lootboxes()

    def _backfill_vip_purchase_transactions(self):
        migration_id = "vip_transactions_migration"
        migration = eco_settings_col.find_one({"_id": migration_id}) or {}
        if migration.get("backfill_version") == VIP_TRANSACTION_BACKFILL_VERSION:
            return

        imported = 0
        legacy_logs = eco_logs_col.find({"type": "shop_buy", "sku": {"$in": list(VIP_INVENTORY_ITEMS)}})
        for old_log in legacy_logs:
            sku = old_log.get("sku")
            item = VIP_INVENTORY_ITEMS.get(sku)
            source_id = old_log.get("_id")
            if not item or source_id is None:
                continue
            try:
                role_id = int(old_log.get("role_id", item["role_id"]))
            except (TypeError, ValueError):
                role_id = item["role_id"]
            try:
                price_amount = int(old_log.get("price_essencia", 0))
            except (TypeError, ValueError):
                price_amount = 0
            transaction_id = f"legacy_shop_buy:{source_id}"
            result = eco_vip_transactions_col.update_one(
                {"_id": transaction_id},
                {
                    "$setOnInsert": {
                        "_id": transaction_id,
                        "type": "vip_purchase",
                        "source": "legacy_eco_logs",
                        "status": "completed",
                        "source_log_id": str(source_id),
                        "guild_id": str(old_log.get("guild_id", "")),
                        "buyer_id": str(old_log.get("user_id", "")),
                        "sku": sku,
                        "item_name": item["name"],
                        "role_id": role_id,
                        "days": item["days"],
                        "quantity": 1,
                        "currency": "essencia",
                        "price_amount": price_amount,
                        "delivery": old_log.get("delivery", "inventory"),
                        "inventory_field": old_log.get("inventory_field", item["field"]),
                        "created_at": old_log.get("created_at", datetime.now(timezone.utc)),
                        "imported_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
            if getattr(result, "upserted_id", None) is not None:
                imported += 1

        marker = eco_settings_col.update_one(
            {"_id": migration_id},
            {
                "$set": {
                    "backfill_version": VIP_TRANSACTION_BACKFILL_VERSION,
                    "backfill_imported": imported,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        if getattr(marker, "acknowledged", False):
            log.info("Transacoes VIP antigas importadas de eco_logs: %s", imported)

    def validate_lootboxes(self):
        if not is_db_online():
            log.warning("Validacao de lootboxes adiada: MongoDB indisponivel.")
            return

        for box_id in ("loot_common", "loot_premium"):
            setting = eco_settings_col.find_one({"_id": box_id})
            errors = self._validate_lootbox_setting(setting, box_id)
            if errors:
                log.error("Lootbox invalida %s: %s", box_id, "; ".join(errors))

    def _validate_lootbox_setting(self, setting: dict | None, box_id: str) -> list[str]:
        if not setting:
            return ["configuracao ausente"]

        errors = []
        cost_currency = setting.get("cost_currency")
        if cost_currency not in VALID_ECONOMY_CURRENCIES:
            errors.append(f"moeda de custo invalida: {cost_currency}")

        try:
            cost_amount = int(setting.get("cost_amount", 0))
        except (TypeError, ValueError):
            cost_amount = 0
        if cost_amount <= 0:
            errors.append("custo precisa ser maior que zero")

        entries = setting.get("entries")
        if not isinstance(entries, list) or not entries:
            return errors + ["entradas ausentes"]

        total_weight = 0
        for idx, entry in enumerate(entries):
            prefix = f"entrada {idx + 1}"
            kind = entry.get("kind")
            if kind not in VALID_REWARD_KINDS:
                errors.append(f"{prefix}: tipo invalido {kind}")

            try:
                weight = int(entry.get("weight", 0))
            except (TypeError, ValueError):
                weight = 0
            if weight <= 0:
                errors.append(f"{prefix}: peso precisa ser maior que zero")
            total_weight += weight

            if kind == "currency":
                currency = entry.get("currency")
                if currency not in VALID_ECONOMY_CURRENCIES - {"eter"}:
                    errors.append(f"{prefix}: moeda de recompensa invalida {currency}")
                try:
                    amount = int(entry.get("amount", 0))
                except (TypeError, ValueError):
                    amount = 0
                if amount <= 0:
                    errors.append(f"{prefix}: quantidade precisa ser maior que zero")
            elif kind == "vip_temp":
                try:
                    role_id = int(entry.get("role_id", 0))
                except (TypeError, ValueError):
                    role_id = 0
                if role_id not in VIP_ROLE_IDS:
                    errors.append(f"{prefix}: role_id VIP invalido {entry.get('role_id')}")
                try:
                    days = int(entry.get("days", 0))
                except (TypeError, ValueError):
                    days = 0
                if days <= 0:
                    errors.append(f"{prefix}: dias de VIP precisam ser maiores que zero")
                sku = VIP_SKU_BY_ROLE_ID.get(role_id)
                if sku and days != VIP_INVENTORY_ITEMS[sku]["days"]:
                    errors.append(
                        f"{prefix}: duracao precisa ser {VIP_INVENTORY_ITEMS[sku]['days']} dias para armazenamento"
                    )

        if total_weight != 100:
            errors.append(f"soma dos pesos precisa ser 100, atual {total_weight}")
        return errors

    def _is_valid_chat_earn_message(self, message: discord.Message) -> bool:
        content = (message.content or "").strip()
        if not content:
            return False
        useful = re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]", content)
        return len(useful) >= MIN_CHAT_USEFUL_CHARS

    async def _check_action_cooldown(self, interaction: discord.Interaction, action: str) -> bool:
        now = self._now_ts()
        key = (interaction.guild.id if interaction.guild else 0, interaction.user.id, action)
        last = self.action_last_used.get(key, 0)
        remaining = ECONOMY_ACTION_COOLDOWN_SECONDS - (now - last)
        if remaining > 0:
            await self._send_ephemeral(interaction, f"Aguarde `{remaining:.1f}s` antes de usar esta acao novamente.")
            return False
        self.action_last_used[key] = now
        return True

    def _is_reset_admin(self, user_id: int) -> bool:
        return user_id in {BOT_OWNER_ID, SERVER_OWNER_FIXED_ID}

    def _now_ts(self) -> float:
        return time.time()

    def _economy_boost_doc_id(self, guild_key: str) -> str:
        return f"{ECONOMY_BOOST_SETTINGS_PREFIX}{guild_key}"

    def _load_active_economy_boosts(self):
        now = self._now_ts()
        docs = list(eco_settings_col.find({"_id": {"$regex": f"^{ECONOMY_BOOST_SETTINGS_PREFIX}"}}))
        for doc in docs:
            guild_key = str(doc.get("guild_id") or str(doc.get("_id", "")).removeprefix(ECONOMY_BOOST_SETTINGS_PREFIX))
            expires_at = float(doc.get("expires_at", 0) or 0)
            if not guild_key or expires_at <= now:
                eco_settings_col.delete_one({"_id": doc.get("_id")})
                continue
            self.economy_boosts[guild_key] = {
                "multiplier": max(1, int(doc.get("multiplier", 1))),
                "started_at": float(doc.get("started_at", now) or now),
                "expires_at": expires_at,
                "started_by": doc.get("started_by"),
                "reason": doc.get("reason", ""),
            }

    def _active_economy_boost(self, guild_id: int | None) -> dict | None:
        if guild_id is None:
            return None
        guild_key = self._gid(guild_id)
        boost = self.economy_boosts.get(guild_key)
        if not boost:
            return None
        if self._now_ts() >= float(boost.get("expires_at", 0)):
            self.economy_boosts.pop(guild_key, None)
            return None
        return boost

    def _economy_gain_amount(self, guild_id: int | None) -> int:
        boost = self._active_economy_boost(guild_id)
        if not boost:
            return 1
        return max(1, int(boost.get("multiplier", 1)))

    def _uid(self, user_id: int) -> str:
        return str(user_id)

    def _gid(self, guild_id: int) -> str:
        return str(get_data_guild_id(guild_id))

    def _user_doc_id(self, user_id: int, guild_id: int) -> str:
        return f"{self._gid(guild_id)}:{self._uid(user_id)}"

    def _limits_doc_id(self, user_id: int, guild_id: int) -> str:
        return f"{self._gid(guild_id)}:{self._uid(user_id)}"

    def _ensure_user_doc(self, user_id: int, guild_id: int):
        eco_users_col.update_one(
            {"_id": self._user_doc_id(user_id, guild_id)},
            {
                "$setOnInsert": {
                    "user_id": self._uid(user_id),
                    "guild_id": self._gid(guild_id),
                    "eter": 0,
                    "essencia": 0,
                    "cristal_essencia": 0,
                    "common_box": 0,
                    "premium_box": 0,
                    "vip_inventory": {sku: 0 for sku in VIP_INVENTORY_ITEMS},
                    "stats": {"earned_chat": 0, "earned_voice": 0, "boxes_opened_common": 0, "boxes_opened_premium": 0},
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

    def _get_user_doc(self, user_id: int, guild_id: int) -> dict:
        self._ensure_user_doc(user_id, guild_id)
        return eco_users_col.find_one({"_id": self._user_doc_id(user_id, guild_id)}) or {
            "_id": self._user_doc_id(user_id, guild_id),
            "user_id": self._uid(user_id),
            "guild_id": self._gid(guild_id),
            "eter": 0,
            "essencia": 0,
            "cristal_essencia": 0,
            "common_box": 0,
            "premium_box": 0,
            "vip_inventory": {sku: 0 for sku in VIP_INVENTORY_ITEMS},
            "stats": {},
        }

    def _credit_user(self, user_id: int, guild_id: int, inc: dict) -> bool:
        inc_payload = {k: v for k, v in inc.items() if v}
        if not inc_payload:
            return True
        result = eco_users_col.update_one(
            {"_id": self._user_doc_id(user_id, guild_id)},
            {
                "$inc": inc_payload,
                "$set": {"updated_at": datetime.now(timezone.utc)},
                "$setOnInsert": {"user_id": self._uid(user_id), "guild_id": self._gid(guild_id)},
            },
            upsert=True,
        )
        return bool(getattr(result, "acknowledged", False))

    def _apply_vip_bonus_to_currency_rewards(
        self,
        user_id: int,
        guild_id: int,
        base_rewards: dict,
        bonus_percent: int,
    ) -> tuple[dict, dict, dict]:
        return self._apply_percent_bonus_to_currency_rewards(
            user_id,
            guild_id,
            base_rewards,
            bonus_percent,
            "vip_bonus_remainder",
        )

    def _apply_guild_bonus_to_currency_rewards(
        self,
        user_id: int,
        guild_id: int,
        base_rewards: dict,
        bonus_percent: int,
    ) -> tuple[dict, dict, dict]:
        return self._apply_percent_bonus_to_currency_rewards(
            user_id,
            guild_id,
            base_rewards,
            bonus_percent,
            "guild_bonus_remainder",
        )

    def _apply_percent_bonus_to_currency_rewards(
        self,
        user_id: int,
        guild_id: int,
        base_rewards: dict,
        bonus_percent: int,
        remainder_bucket: str,
    ) -> tuple[dict, dict, dict]:
        total_rewards = dict(base_rewards)
        if bonus_percent <= 0:
            return total_rewards, {}, {}

        doc = self._get_user_doc(user_id, guild_id)
        stats = doc.get("stats") or {}
        remainders = stats.get(remainder_bucket) or {}
        bonus_rewards = {}
        remainder_updates = {}

        for currency, amount in base_rewards.items():
            if currency not in VALID_ECONOMY_CURRENCIES or amount <= 0:
                continue
            raw_bonus = float(remainders.get(currency, 0) or 0) + (float(amount) * bonus_percent / 100)
            whole_bonus = int(raw_bonus)
            remainder_updates[f"stats.{remainder_bucket}.{currency}"] = round(raw_bonus - whole_bonus, 6)
            if whole_bonus > 0:
                bonus_rewards[currency] = whole_bonus
                total_rewards[currency] = int(total_rewards.get(currency, 0)) + whole_bonus

        return total_rewards, bonus_rewards, remainder_updates

    def _merge_currency_bonus_rewards(self, base_rewards: dict, *bonus_reward_sets: dict) -> dict:
        total = dict(base_rewards)
        for bonus_rewards in bonus_reward_sets:
            for currency, amount in (bonus_rewards or {}).items():
                total[currency] = int(total.get(currency, 0)) + int(amount)
        return total

    async def _credit_guild_activity_xp(self, member: discord.Member, source: str, xp_amount: int = 1) -> dict:
        guild_cog = self.bot.get_cog("GuildSystem")
        if not guild_cog or not hasattr(guild_cog, "credit_activity_xp"):
            return {"credited": False, "percent": 0, "guild": None, "monthly_xp": 0}
        try:
            return await asyncio.to_thread(guild_cog.credit_activity_xp, member, source, xp_amount)
        except Exception:
            log.exception("guild_activity_xp_credit_error guild_id=%s member_id=%s source=%s", member.guild.id, member.id, source)
            return {"credited": False, "percent": 0, "guild": None, "monthly_xp": 0}

    def _get_member_guild_bonus(self, member: discord.Member | None) -> dict:
        guild_cog = self.bot.get_cog("GuildSystem")
        if not guild_cog or not hasattr(guild_cog, "get_member_guild_boost_info"):
            return {"percent": 0, "guild": None, "monthly_xp": 0}
        try:
            return guild_cog.get_member_guild_boost_info(member)
        except Exception:
            log.exception("guild_bonus_lookup_error member_id=%s", getattr(member, "id", None))
            return {"percent": 0, "guild": None, "monthly_xp": 0}

    async def _get_member_guild_bonus_async(self, member: discord.Member | None) -> dict:
        return await asyncio.to_thread(self._get_member_guild_bonus, member)

    def _persist_vip_bonus_remainders(self, user_id: int, guild_id: int, remainder_updates: dict) -> bool:
        if remainder_updates:
            result = eco_users_col.update_one(
                {"_id": self._user_doc_id(user_id, guild_id)},
                {
                    "$set": {**remainder_updates, "updated_at": datetime.now(timezone.utc)},
                    "$setOnInsert": {"user_id": self._uid(user_id), "guild_id": self._gid(guild_id)},
                },
                upsert=True,
            )
            return bool(getattr(result, "acknowledged", False))
        return True

    def _reserve_shop_purchase_atomic(self, user_id: int, guild_id: int, sku: str) -> bool | None:
        doc_id = self._limits_doc_id(user_id, guild_id)
        ensured = eco_limits_col.update_one(
            {"_id": doc_id},
            {
                "$setOnInsert": {
                    "_id": doc_id,
                    "user_id": self._uid(user_id),
                    "guild_id": self._gid(guild_id),
                    "purchased_skus": [],
                },
            },
            upsert=True,
        )
        if not getattr(ensured, "acknowledged", False):
            return None

        reserved = eco_limits_col.update_one(
            {"_id": doc_id, "purchased_skus": {"$ne": sku}},
            {"$addToSet": {"purchased_skus": sku}},
        )
        if not getattr(reserved, "acknowledged", False):
            return None
        if getattr(reserved, "matched_count", 0) > 0:
            return True
        return False if is_db_online() else None

    def _release_shop_purchase_atomic(self, user_id: int, guild_id: int, sku: str) -> bool:
        result = eco_limits_col.update_one(
            {"_id": self._limits_doc_id(user_id, guild_id)},
            {"$pull": {"purchased_skus": sku}},
        )
        return bool(getattr(result, "acknowledged", False))

    def _debit_user_atomic(self, user_id: int, guild_id: int, currency: str, amount: int) -> bool:
        if amount <= 0:
            return True
        self._ensure_user_doc(user_id, guild_id)
        updated = eco_users_col.find_one_and_update(
            {
                "_id": self._user_doc_id(user_id, guild_id),
                currency: {"$gte": amount},
            },
            {"$inc": {currency: -amount}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        return updated is not None

    def _consume_box_atomic(self, user_id: int, guild_id: int, box_field: str, amount: int) -> bool:
        if amount <= 0:
            return True
        self._ensure_user_doc(user_id, guild_id)
        updated = eco_users_col.find_one_and_update(
            {
                "_id": self._user_doc_id(user_id, guild_id),
                box_field: {"$gte": amount},
            },
            {"$inc": {box_field: -amount}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        return updated is not None

    def _vip_inventory_counts(self, doc: dict) -> dict[str, int]:
        inventory = doc.get("vip_inventory") or {}
        return {
            sku: max(0, int(inventory.get(sku, 0) or 0))
            for sku in VIP_INVENTORY_ITEMS
        }

    async def _build_vip_inventory_options(self, user_id: int, guild_id: int) -> list[discord.SelectOption]:
        doc = await asyncio.to_thread(self._get_user_doc, user_id, guild_id)
        counts = self._vip_inventory_counts(doc)
        return [
            discord.SelectOption(
                label=item["name"],
                value=sku,
                description=f"Disponivel: {counts[sku]} unidade(s)",
                emoji=VIP_EMOJIS.get(sku),
            )
            for sku, item in VIP_INVENTORY_ITEMS.items()
            if counts[sku] > 0
        ]

    def _consume_vip_inventory_atomic(self, user_id: int, guild_id: int, sku: str, amount: int = 1) -> bool:
        item = VIP_INVENTORY_ITEMS.get(sku)
        if not item:
            return False
        if amount <= 0:
            return True
        self._ensure_user_doc(user_id, guild_id)
        updated = eco_users_col.find_one_and_update(
            {
                "_id": self._user_doc_id(user_id, guild_id),
                item["field"]: {"$gte": amount},
            },
            {"$inc": {item["field"]: -amount}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        return updated is not None

    def _roll_entry(self, entries: list[dict]) -> dict:
        valid_entries = [e for e in entries if int(e.get("weight", 0)) > 0]
        if not valid_entries:
            raise ValueError("Tabela de recompensas invalida: sem pesos positivos.")
        weights = [int(e.get("weight", 0)) for e in valid_entries]
        return random.choices(valid_entries, weights=weights, k=1)[0]

    async def _send_ephemeral(self, interaction: discord.Interaction, content: str):
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)

    def _is_native_economy_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in {BOT_OWNER_ID, SERVER_OWNER_FIXED_ID}:
            return True
        roles = getattr(interaction.user, "roles", [])
        if any(getattr(role, "id", None) == 1117577222249795725 for role in roles):
            return True
        if interaction.channel is None:
            return False
        return interaction.channel.permissions_for(interaction.user).administrator

    def _is_events_team_member(self, interaction: discord.Interaction) -> bool:
        roles = getattr(interaction.user, "roles", [])
        return any(getattr(role, "id", None) == EVENTS_TEAM_ROLE_ID for role in roles)

    async def _send_economy_event_audit_dm(
        self,
        interaction: discord.Interaction,
        *,
        action: str,
        usuario: discord.Member,
        moeda: str,
        valor: int,
        motivo: str,
        before: int | None = None,
        after: int | None = None,
    ):
        actor = interaction.user
        guild = interaction.guild
        embed = discord.Embed(
            title="Auditoria de Economia",
            description="Um membro da equipe de eventos utilizou um comando administrativo de economia.",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Acao", value=action, inline=True)
        embed.add_field(name="Moeda", value=moeda, inline=True)
        embed.add_field(name="Valor", value=f"`{int(valor)}`", inline=True)
        embed.add_field(name="Responsavel", value=f"{actor.mention} (`{actor.id}`)", inline=False)
        embed.add_field(name="Usuario afetado", value=f"{usuario.mention} (`{usuario.id}`)", inline=False)
        embed.add_field(name="Motivo", value=motivo[:1024], inline=False)
        if before is not None and after is not None:
            embed.add_field(name="Saldo", value=f"`{before}` -> `{after}`", inline=False)
        if guild:
            embed.set_footer(text=f"{guild.name} • {guild.id}")

        for user_id in ECONOMY_ADMIN_AUDIT_DM_USER_IDS:
            try:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                await user.send(embed=embed)
            except discord.HTTPException as e:
                log.warning(
                    "economy_event_audit_dm_failed target_id=%s actor_id=%s user_id=%s action=%s error=%s",
                    user_id,
                    actor.id,
                    usuario.id,
                    action,
                    e,
                )

    def _extract_user_id_from_doc(self, doc: dict) -> int | None:
        uid = doc.get("user_id")
        if uid is not None:
            try:
                return int(uid)
            except (TypeError, ValueError):
                pass

        raw_id = str(doc.get("_id", ""))
        if ":" in raw_id:
            maybe_uid = raw_id.split(":", 1)[1]
        else:
            maybe_uid = raw_id
        try:
            return int(maybe_uid)
        except (TypeError, ValueError):
            return None

    async def get_guild_member_safe(self, guild: discord.Guild, user_id) -> discord.Member | None:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return None

        member = guild.get_member(user_id)
        if member:
            return member

        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _build_leaderboard_embed(self, guild: discord.Guild, currency: str, limit: int = 10) -> discord.Embed:
        label = format_currency_label(currency)

        docs = await asyncio.to_thread(
            lambda: list(eco_users_col.find({"guild_id": self._gid(guild.id), currency: {"$gt": 0}}).sort(currency, -1))
        )

        lines = []
        for doc in docs:
            value = int(doc.get(currency, 0))
            uid = self._extract_user_id_from_doc(doc)
            if uid is None:
                continue
            member = await self.get_guild_member_safe(guild, uid)
            if member is None:
                continue
            idx = len(lines) + 1
            user_text = member.mention
            lines.append(f"`#{idx:02d}` {user_text} - {format_currency_amount(currency, value)}")
            if len(lines) >= limit:
                break

        if not lines:
            lines.append("Sem membros atuais com saldo para este ranking.")

        embed = discord.Embed(
            title=f"Leaderboard Admin - {label}",
            description="\n".join(lines),
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
        embed.set_footer(text="Menu acima: altere o tipo de moeda.")
        return embed

    def _validate_temp_role(self, member: discord.Member, role_id: int) -> tuple[discord.Role | None, str | None]:
        role = member.guild.get_role(int(role_id))
        if not role:
            return None, "cargo VIP nao encontrado"
        if role.managed:
            return role, "cargo VIP gerenciado por integracao"

        bot_member = member.guild.me
        if not bot_member:
            return role, "membro do bot nao encontrado no servidor"
        if not bot_member.guild_permissions.manage_roles:
            return role, "bot sem permissao Manage Roles"
        if role >= bot_member.top_role:
            return role, "cargo VIP acima ou igual ao maior cargo do bot"

        return role, None

    async def _apply_temp_role_days(
        self,
        member: discord.Member,
        role_id: int,
        days: int,
        source: str = "loja",
        source_label: str = "Loja Kaguya",
        source_detail: str = "eco_inventory_activate",
        source_actor_id: str | None = None,
    ) -> dict:
        role, error = self._validate_temp_role(member, role_id)
        if error:
            return {"success": False, "role": role, "end_time": None, "error": error}

        now = self._now_ts()
        duration = int(days * 86400)

        query = {"user_id": self._uid(member.id), "guild_id": str(member.guild.id), "role_id": self._uid(role.id)}
        existing = await asyncio.to_thread(temp_col.find_one, query)
        if not is_db_online():
            return {"success": False, "role": role, "end_time": None, "error": "banco indisponivel ao registrar o VIP"}

        if existing and existing.get("end_time", 0) > now:
            new_end = int(existing["end_time"] + duration)
        else:
            new_end = int(now + duration)

        added_role = role not in member.roles
        if added_role:
            try:
                await member.add_roles(role, reason="Economia: recompensa VIP temporario")
            except discord.Forbidden:
                return {"success": False, "role": role, "end_time": None, "error": "bot sem permissao para adicionar o cargo VIP"}
            except discord.HTTPException:
                return {"success": False, "role": role, "end_time": None, "error": "erro da API do Discord ao adicionar o cargo VIP"}

        stored = await asyncio.to_thread(
            temp_col.update_one,
            query,
            {
                "$set": {
                    "end_time": new_end,
                    "source": source,
                    "source_label": source_label,
                    "source_detail": source_detail,
                    "source_actor_id": source_actor_id or self._uid(member.id),
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        if not getattr(stored, "acknowledged", False):
            if added_role:
                try:
                    await member.remove_roles(role, reason="Economia: falha ao persistir VIP temporario")
                except (discord.Forbidden, discord.HTTPException):
                    log.exception("Falha ao remover cargo apos erro de persistencia do VIP para %s", member.id)
                    return {
                        "success": False,
                        "role": role,
                        "end_time": None,
                        "error": "cargo aplicado sem validade registrada; remocao manual necessaria",
                        "keep_consumed": True,
                    }
            return {"success": False, "role": role, "end_time": None, "error": "falha ao registrar validade do VIP"}
        return {"success": True, "role": role, "end_time": new_end, "error": None}

    async def _activate_inventory_vip(self, interaction: discord.Interaction, sku: str) -> str:
        item = VIP_INVENTORY_ITEMS.get(sku)
        if not item:
            return "VIP invalido ou indisponivel."
        if not is_db_online():
            return "Banco indisponivel no momento."

        consumed = await asyncio.to_thread(
            self._consume_vip_inventory_atomic, interaction.user.id, interaction.guild.id, sku
        )
        if not consumed:
            if not is_db_online():
                return "Banco indisponivel ao consultar seu inventario. Nenhum VIP foi ativado."
            return "Este VIP nao esta mais disponivel no seu inventario."

        result = await self._apply_temp_role_days(
            interaction.user,
            item["role_id"],
            item["days"],
            source="loja",
            source_label="Loja Kaguya",
            source_detail=f"eco_inventory_activate:{sku}",
            source_actor_id=self._uid(interaction.user.id),
        )
        if not result["success"]:
            if result.get("keep_consumed"):
                await self._log_economy_failure(
                    interaction.guild,
                    "VIP aplicado sem validade persistida",
                    {
                        "user_id": self._uid(interaction.user.id),
                        "sku": sku,
                        "role_id": item["role_id"],
                        "reason": result["error"],
                        "inventory_refunded": False,
                    },
                )
                return (
                    f"O cargo de **{format_vip_name(sku)}** foi aplicado, mas a validade nao foi registrada. "
                    "O item nao foi devolvido para evitar duplicidade; acione a staff."
                )
            refunded = await asyncio.to_thread(self._credit_user, interaction.user.id, interaction.guild.id, {item["field"]: 1})
            await self._log_economy_failure(
                interaction.guild,
                "Falha ao ativar VIP do inventario",
                {
                    "user_id": self._uid(interaction.user.id),
                    "sku": sku,
                    "role_id": item["role_id"],
                    "reason": result["error"],
                    "inventory_refunded": refunded,
                },
            )
            if refunded:
                return f"Nao foi possivel ativar **{format_vip_name(sku)}** ({result['error']}). O item foi devolvido ao inventario."
            return (
                f"Nao foi possivel ativar **{format_vip_name(sku)}** ({result['error']}) e nao foi possivel "
                "confirmar a devolucao do item. Acione a staff."
            )

        try:
            await asyncio.to_thread(
                eco_logs_col.insert_one,
                {
                    "type": "vip_inventory_activate",
                    "user_id": self._uid(interaction.user.id),
                    "guild_id": self._gid(interaction.guild.id),
                    "sku": sku,
                    "role_id": item["role_id"],
                    "days": item["days"],
                    "end_time": result["end_time"],
                    "created_at": datetime.now(timezone.utc),
                },
            )
        except Exception:
            log.exception("VIP ativado, mas nao foi possivel registrar log de ativacao %s", sku)
        return f"**{format_vip_name(sku)}** ativado com sucesso. Ativo ate <t:{int(result['end_time'])}:R>."

    async def _transfer_inventory_vip(
        self, interaction: discord.Interaction, sku: str, recipient: discord.Member
    ) -> str:
        item = VIP_INVENTORY_ITEMS.get(sku)
        if not item:
            return "VIP invalido ou indisponivel."
        if not is_db_online():
            return "Banco indisponivel no momento."

        recipient = await self.get_guild_member_safe(interaction.guild, recipient.id)
        if not recipient or recipient.bot or recipient.id == interaction.user.id:
            return "O destinatario selecionado nao e valido para esta doacao."

        consumed = await asyncio.to_thread(
            self._consume_vip_inventory_atomic, interaction.user.id, interaction.guild.id, sku
        )
        if not consumed:
            if not is_db_online():
                return "Banco indisponivel ao consultar seu inventario. Nenhum VIP foi doado."
            return "Este VIP nao esta mais disponivel no seu inventario."

        delivered = await asyncio.to_thread(self._credit_user, recipient.id, interaction.guild.id, {item["field"]: 1})
        if not delivered:
            refunded = await asyncio.to_thread(self._credit_user, interaction.user.id, interaction.guild.id, {item["field"]: 1})
            log.error("Falha ao transferir VIP de inventario %s; refund confirmado=%s", sku, refunded)
            if refunded:
                return "Nao foi possivel concluir a doacao. O VIP foi devolvido ao seu inventario."
            return "Nao foi possivel concluir a doacao nem confirmar a devolucao do VIP. Acione a staff."

        try:
            await asyncio.to_thread(
                eco_logs_col.insert_one,
                {
                    "type": "vip_inventory_donation",
                    "donor_id": self._uid(interaction.user.id),
                    "recipient_id": self._uid(recipient.id),
                    "guild_id": self._gid(interaction.guild.id),
                    "sku": sku,
                    "role_id": item["role_id"],
                    "days": item["days"],
                    "created_at": datetime.now(timezone.utc),
                },
            )
        except Exception:
            log.exception("VIP doado, mas nao foi possivel registrar log da doacao %s", sku)

        return (
            f"Doacao concluida: **{format_vip_name(sku)}** foi enviado para {recipient.mention}. "
            "O destinatario podera ativa-lo em `/eco inventario`."
        )

    async def _log_economy_failure(self, guild: discord.Guild, title: str, payload: dict, lines: list[str] | None = None):
        await asyncio.to_thread(
            eco_logs_col.insert_one,
            {
                "type": "economy_failure",
                "guild_id": self._gid(guild.id),
                "title": title,
                "payload": payload,
                "created_at": datetime.now(timezone.utc),
            }
        )
        await self._log_action(guild, title, lines or [str(payload)])

    async def _log_action(self, guild: discord.Guild, title: str, lines: list[str]):
        await asyncio.to_thread(
            eco_logs_col.insert_one,
            {
                "type": "discord_log",
                "guild_id": self._gid(guild.id),
                "title": title,
                "lines": lines,
                "created_at": datetime.now(timezone.utc),
            }
        )
        if not ECONOMY_LOG_CHANNEL_ID:
            return
        channel = guild.get_channel(ECONOMY_LOG_CHANNEL_ID)
        if not channel:
            return
        embed = discord.Embed(title=title, description="\n".join(lines), color=discord.Color.blue(), timestamp=datetime.now())
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            return

    async def _record_vip_purchase_transaction(
        self,
        interaction: discord.Interaction,
        sku: str,
        entry: dict,
        inventory_item: dict,
        price: int,
    ):
        created_at = datetime.now(timezone.utc)
        document = {
            "type": "vip_purchase",
            "source": "kaguya_shop",
            "status": "completed",
            "guild_id": self._gid(interaction.guild.id),
            "buyer_id": self._uid(interaction.user.id),
            "buyer_name": str(interaction.user),
            "sku": sku,
            "item_name": str(entry.get("name", sku)),
            "role_id": inventory_item["role_id"],
            "days": inventory_item["days"],
            "quantity": 1,
            "currency": "essencia",
            "price_amount": price,
            "delivery": "inventory",
            "inventory_field": inventory_item["field"],
            "created_at": created_at,
        }
        transaction_id = None
        try:
            result = await asyncio.to_thread(eco_vip_transactions_col.insert_one, document)
            if getattr(result, "acknowledged", False):
                transaction_id = str(result.inserted_id)
            else:
                log.error("Compra VIP entregue sem confirmacao do registro de transacao: sku=%s buyer=%s", sku, interaction.user.id)
        except Exception:
            log.exception("Compra VIP entregue, mas falhou ao registrar transacao: sku=%s buyer=%s", sku, interaction.user.id)

        lines = [
            f"Comprador: {interaction.user.mention} (`{interaction.user.id}`)",
            f"VIP: **{format_vip_name(sku, document['item_name'])}** (`{sku}`)",
            f"Valor: {format_currency_amount('essencia', price)}",
            "Entrega: inventario",
        ]
        if transaction_id:
            lines.append(f"Transacao: `{transaction_id}`")
        else:
            lines.append("Transacao: falha ao confirmar registro no banco")
        try:
            await self._log_action(interaction.guild, "Economia - Compra de VIP", lines)
        except Exception:
            log.exception("Falha ao publicar log da compra VIP: sku=%s buyer=%s", sku, interaction.user.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.channel.id not in ECONOMY_EARN_CHANNEL_IDS:
            return
        if not self._is_valid_chat_earn_message(message):
            return

        now = self._now_ts()
        key = (message.guild.id, message.author.id)
        last = self.chat_last_earn.get(key, 0)
        if now - last < 5:
            return

        self.chat_last_earn[key] = now
        gain = self._economy_gain_amount(message.guild.id)
        base_rewards = {"eter": gain}
        guild_bonus = await self._get_member_guild_bonus_async(message.author)
        bonus = get_member_vip_bonus(message.author)
        _vip_total, vip_bonus_rewards, vip_remainder_updates = await asyncio.to_thread(
            self._apply_vip_bonus_to_currency_rewards,
            message.author.id,
            message.guild.id,
            base_rewards,
            bonus["percent"],
        )
        _guild_total, guild_bonus_rewards, guild_remainder_updates = await asyncio.to_thread(
            self._apply_guild_bonus_to_currency_rewards,
            message.author.id,
            message.guild.id,
            base_rewards,
            int(guild_bonus.get("percent", 0) or 0),
        )
        rewards = self._merge_currency_bonus_rewards(base_rewards, vip_bonus_rewards, guild_bonus_rewards)
        delivered = int(rewards.get("eter", gain))
        credited = await asyncio.to_thread(
            self._credit_user,
            message.author.id,
            message.guild.id,
            {"eter": delivered, "stats.earned_chat": delivered},
        )
        if credited:
            remainder_updates = {**vip_remainder_updates, **guild_remainder_updates}
            await asyncio.to_thread(self._persist_vip_bonus_remainders, message.author.id, message.guild.id, remainder_updates)
            await self._credit_guild_activity_xp(message.author, "message", 1)

    def _is_voice_eligible(self, member: discord.Member) -> bool:
        if member.bot or not member.voice or not member.voice.channel:
            return False
        state = member.voice
        if member.guild.afk_channel and state.channel.id == member.guild.afk_channel.id:
            return False
        if state.self_mute or state.mute:
            return False
        if state.self_deaf or state.deaf:
            return False
        active_members = [
            voice_member
            for voice_member in state.channel.members
            if not voice_member.bot
            and voice_member.voice
            and voice_member.voice.channel
            and not voice_member.voice.self_mute
            and not voice_member.voice.mute
            and not voice_member.voice.self_deaf
            and not voice_member.voice.deaf
        ]
        if len(active_members) < 2:
            return False
        return True

    @tasks.loop(seconds=10)
    async def voice_tick(self):
        now = self._now_ts()
        seen_keys = set()
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    key = (guild.id, member.id)
                    seen_keys.add(key)
                    if not self._is_voice_eligible(member):
                        self.voice_eligible_since.pop(key, None)
                        continue

                    start = self.voice_eligible_since.get(key)
                    if start is None:
                        self.voice_eligible_since[key] = now
                        continue

                    if now - start >= 10:
                        self.voice_eligible_since[key] = now
                        gain = self._economy_gain_amount(guild.id)
                        base_rewards = {"eter": gain}
                        guild_bonus = await self._get_member_guild_bonus_async(member)
                        bonus = get_member_vip_bonus(member)
                        _vip_total, vip_bonus_rewards, vip_remainder_updates = await asyncio.to_thread(
                            self._apply_vip_bonus_to_currency_rewards,
                            member.id,
                            guild.id,
                            base_rewards,
                            bonus["percent"],
                        )
                        _guild_total, guild_bonus_rewards, guild_remainder_updates = await asyncio.to_thread(
                            self._apply_guild_bonus_to_currency_rewards,
                            member.id,
                            guild.id,
                            base_rewards,
                            int(guild_bonus.get("percent", 0) or 0),
                        )
                        rewards = self._merge_currency_bonus_rewards(base_rewards, vip_bonus_rewards, guild_bonus_rewards)
                        delivered = int(rewards.get("eter", gain))
                        credited = await asyncio.to_thread(
                            self._credit_user,
                            member.id,
                            guild.id,
                            {"eter": delivered, "stats.earned_voice": delivered},
                        )
                        if credited:
                            remainder_updates = {**vip_remainder_updates, **guild_remainder_updates}
                            await asyncio.to_thread(self._persist_vip_bonus_remainders, member.id, guild.id, remainder_updates)
                            await self._credit_guild_activity_xp(member, "voice", 1)

        for key in list(self.voice_eligible_since.keys()):
            if key not in seen_keys:
                self.voice_eligible_since.pop(key, None)

    @voice_tick.before_loop
    async def before_voice_tick(self):
        await self.bot.wait_until_ready()

    def _format_balance_embed(self, user: discord.Member, doc: dict) -> discord.Embed:
        stats = doc.get("stats", {})
        embed = discord.Embed(title=f"Economia de {user.display_name}", color=discord.Color.blurple())
        embed.add_field(name=format_currency_label("eter"), value=f"`{int(doc.get('eter', 0))}`", inline=True)
        embed.add_field(name=format_currency_label("essencia"), value=f"`{int(doc.get('essencia', 0))}`", inline=True)
        embed.add_field(name=format_currency_label("cristal_essencia"), value=f"`{int(doc.get('cristal_essencia', 0))}`", inline=True)
        embed.add_field(name=format_lootbox_name("Lootbox Comum"), value=f"`{int(doc.get('common_box', 0))}`", inline=True)
        embed.add_field(name=format_lootbox_name("Lootbox Premium"), value=f"`{int(doc.get('premium_box', 0))}`", inline=True)
        embed.add_field(
            name="Progresso",
            value=(
                f"Ganho no chat: `{int(stats.get('earned_chat', 0))}`\n"
                f"Ganho em voz: `{int(stats.get('earned_voice', 0))}`\n"
                f"Caixas comuns abertas: `{int(stats.get('boxes_opened_common', 0))}`\n"
                f"Caixas premium abertas: `{int(stats.get('boxes_opened_premium', 0))}`"
            ),
            inline=False,
        )
        vip_bonus = get_member_vip_bonus(user)
        guild_bonus = self._get_member_guild_bonus(user)
        boost_lines = []
        if vip_bonus.get("percent"):
            boost_lines.append(f"{format_vip_bonus_label(vip_bonus)}")
        if guild_bonus.get("percent"):
            boost_lines.append(f"{format_guild_bonus_label(guild_bonus)}")
        if boost_lines:
            total_percent = int(vip_bonus.get("percent", 0) or 0) + int(guild_bonus.get("percent", 0) or 0)
            embed.add_field(
                name="Boosts de Eter",
                value="\n".join(boost_lines + [f"Total em chat/call: `+{total_percent}%`"]),
                inline=False,
            )
        return embed

    def _build_odds_lines(self, box_id: str, guild: discord.Guild) -> list[str]:
        setting = eco_settings_col.find_one({"_id": box_id})
        if not setting:
            return []
        entries = setting.get("entries", [])
        total_weight = sum(int(e.get("weight", 0)) for e in entries) or 1
        lines = []
        for e in entries:
            pct = (int(e.get("weight", 0)) / total_weight) * 100
            if e["kind"] == "currency":
                label = format_currency_amount(e["currency"], int(e["amount"]))
            else:
                role = guild.get_role(int(e["role_id"]))
                sku = VIP_SKU_BY_ROLE_ID.get(int(e["role_id"]))
                role_name = role.name if role else f"VIP {e['role_id']}"
                label = f"{format_vip_name(sku, role_name) if sku else role_name} ({e.get('days', 30)}d)"
            lines.append(f"- `{pct:.2f}%` - {label}")
        return lines

    @eco.command(name="ajuda", description="Explica como funciona a economia.")
    async def eco_ajuda(self, interaction: discord.Interaction):
        from .commands.eco_ajuda_command import execute

        await execute(self, interaction)

    @eco.command(name="saldo", description="Mostra seu saldo da economia.")
    async def eco_saldo(self, interaction: discord.Interaction):
        from .commands.eco_saldo_command import execute

        await execute(self, interaction)

    @eco.command(name="saldo_usuario", description="Mostra o saldo de um usuario especifico.")
    @check_owner_or_perm(administrator=True)
    async def eco_saldo_usuario(self, interaction: discord.Interaction, usuario: discord.Member):
        from .commands.eco_saldo_usuario_command import execute

        await execute(self, interaction, usuario)

    @eco.command(name="inventario", description="Mostra itens e limites da sua conta.")
    async def eco_inventario(self, interaction: discord.Interaction):
        from .commands.eco_inventario_command import execute

        await execute(self, interaction)

    async def _open_box(self, interaction: discord.Interaction, box_id: str, quantidade: int):
        if not await ensure_db_online(interaction, "abrir lootbox"):
            return
        if not await self._check_action_cooldown(interaction, f"open_box:{box_id}"):
            return
        setting = await asyncio.to_thread(eco_settings_col.find_one, {"_id": box_id})
        if not setting:
            return await interaction.followup.send("Configuracao da caixa nao encontrada.", ephemeral=True)
        validation_errors = self._validate_lootbox_setting(setting, box_id)
        if validation_errors:
            log.error("Abertura bloqueada por lootbox invalida %s: %s", box_id, "; ".join(validation_errors))
            return await interaction.followup.send("A configuracao desta caixa esta invalida. Avise a administracao.", ephemeral=True)
        entries = setting.get("entries", [])
        if not any(int(e.get("weight", 0)) > 0 for e in entries):
            return await interaction.followup.send("A tabela de recompensas desta caixa esta invalida.", ephemeral=True)

        qty = max(1, min(10, quantidade))
        box_field = "common_box" if box_id == "loot_common" else "premium_box"

        currency_rewards = {"essencia": 0, "cristal_essencia": 0}
        vip_rewards = {}
        for _ in range(qty):
            reward = self._roll_entry(entries)
            if reward["kind"] == "currency":
                currency_rewards[reward["currency"]] += int(reward["amount"])
            elif reward["kind"] == "vip_temp":
                role_id = int(reward["role_id"])
                sku = VIP_SKU_BY_ROLE_ID.get(role_id)
                if not sku:
                    return await interaction.followup.send(
                        "A configuracao desta caixa possui um VIP sem item de inventario. Avise a administracao.",
                        ephemeral=True,
                    )
                vip_rewards[sku] = vip_rewards.get(sku, 0) + 1

        consumed = await asyncio.to_thread(
            self._consume_box_atomic, interaction.user.id, interaction.guild.id, box_field, qty
        )
        if not consumed:
            if not is_db_online():
                return await interaction.followup.send(
                    "Banco indisponivel ao consultar seu inventario. Nenhuma caixa foi aberta.",
                    ephemeral=True,
                )
            return await interaction.followup.send("Voce nao possui caixas suficientes no inventario para abrir essa quantidade.", ephemeral=True)

        bonus = get_member_vip_bonus(interaction.user)
        total_currency_rewards, vip_bonus_rewards, remainder_updates = await asyncio.to_thread(
            self._apply_vip_bonus_to_currency_rewards,
            interaction.user.id,
            interaction.guild.id,
            currency_rewards,
            bonus["percent"],
        )
        operation_doc = {
            "type": "open_box",
            "status": "pending",
            "box_id": box_id,
            "user_id": self._uid(interaction.user.id),
            "guild_id": self._gid(interaction.guild.id),
            "quantity": qty,
            "source_inventory": box_field,
            "source_amount": qty,
            "currency_rewards": currency_rewards,
            "vip_bonus": bonus,
            "vip_bonus_rewards": vip_bonus_rewards,
            "delivered_currency_rewards": total_currency_rewards,
            "vip_inventory_rewards": vip_rewards,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        vip_lines = []
        operation_id = None
        try:
            operation = await asyncio.to_thread(eco_logs_col.insert_one, operation_doc)
            operation_id = getattr(operation, "inserted_id", None)
            stat_key = "stats.boxes_opened_common" if box_id == "loot_common" else "stats.boxes_opened_premium"
            rewards_to_credit = {**total_currency_rewards, stat_key: qty}
            for sku, amount in vip_rewards.items():
                item = VIP_INVENTORY_ITEMS[sku]
                rewards_to_credit[item["field"]] = amount
                vip_lines.append(f"{format_vip_name(sku)}: `{amount}` unidade(s) adicionada(s) ao inventario")
            credited = await asyncio.to_thread(self._credit_user, interaction.user.id, interaction.guild.id, rewards_to_credit)
            if not credited:
                raise RuntimeError("falha ao creditar recompensas no inventario")
            await asyncio.to_thread(
                self._persist_vip_bonus_remainders,
                interaction.user.id,
                interaction.guild.id,
                remainder_updates,
            )
        except Exception as exc:
            log.exception("Erro inesperado ao abrir lootbox %s", box_id)
            refunded = await asyncio.to_thread(self._credit_user, interaction.user.id, interaction.guild.id, {box_field: qty})
            if operation_id is not None:
                await asyncio.to_thread(
                    eco_logs_col.update_one,
                    {"_id": operation_id},
                    {
                        "$set": {
                            "status": "failed",
                            "failure_reason": str(exc),
                            "refund_currency": box_field,
                            "refund_amount": qty,
                            "refund_confirmed": refunded,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    },
                )
            if not refunded:
                return await interaction.followup.send(
                    "Ocorreu uma falha ao abrir a lootbox e nao foi possivel confirmar a devolucao. Acione a staff.",
                    ephemeral=True,
                )
            return await interaction.followup.send(
                "Ocorreu uma falha ao abrir a lootbox. As caixas foram devolvidas ao inventario.",
                ephemeral=True,
            )

        embed = discord.Embed(title=f"{setting['name']} aberta", color=discord.Color.green())
        embed.add_field(name="Quantidade", value=f"`{qty}`", inline=True)
        embed.add_field(name="Consumido do inventario", value=f"`{qty}` {box_field}", inline=True)
        reward_lines = []
        for currency in ("essencia", "cristal_essencia"):
            base_amount = int(currency_rewards.get(currency, 0))
            bonus_amount = int(vip_bonus_rewards.get(currency, 0))
            total_amount = int(total_currency_rewards.get(currency, base_amount))
            line = f"{format_currency_label(currency)}: `{total_amount}`"
            if bonus_amount:
                line += f" (`{base_amount}` + bônus VIP `{bonus_amount}`)"
            reward_lines.append(line)
        embed.add_field(
            name="Recompensas",
            value="\n".join(reward_lines),
            inline=False,
        )
        if bonus["percent"]:
            bonus_lines = [
                f"{format_vip_bonus_label(bonus)} aplicado nas moedas da lootbox.",
            ]
            if vip_bonus_rewards:
                bonus_lines.extend(
                    f"+ {format_currency_amount(currency, amount)}"
                    for currency, amount in vip_bonus_rewards.items()
                )
            else:
                bonus_lines.append("O bônus fracionado foi acumulado para as próximas recompensas.")
            embed.add_field(name="Bônus VIP", value="\n".join(bonus_lines), inline=False)
        if vip_lines:
            embed.add_field(name="Recompensas VIP", value="\n".join(f"- {line}" for line in vip_lines), inline=False)
            embed.add_field(
                name="Como usar",
                value="O VIP nao foi ativado. Abra `/eco inventario` para ativa-lo ou doa-lo.",
                inline=False,
            )

        final_log_payload = {
            "status": "completed",
            "vip_inventory_results": [
                {
                    "sku": sku,
                    "quantity": amount,
                    "role_id": VIP_INVENTORY_ITEMS[sku]["role_id"],
                    "days": VIP_INVENTORY_ITEMS[sku]["days"],
                }
                for sku, amount in vip_rewards.items()
            ],
            "completed_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        try:
            if operation_id is not None:
                await asyncio.to_thread(eco_logs_col.update_one, {"_id": operation_id}, {"$set": final_log_payload})
            else:
                await asyncio.to_thread(
                    eco_logs_col.insert_one,
                    {
                        **operation_doc,
                        **final_log_payload,
                    }
                )
        except Exception:
            log.exception("Premios entregues, mas nao foi possivel finalizar log da lootbox %s", box_id)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @eco.command(name="abrir_comum", description="Abre Lootbox Comum do inventario.")
    @app_commands.describe(quantidade="Quantidade de caixas (1 a 10)")
    async def eco_abrir_comum(self, interaction: discord.Interaction, quantidade: int = 1):
        from .commands.eco_abrir_comum_command import execute

        await execute(self, interaction, quantidade)

    @eco.command(name="abrir_premium", description="Abre Lootbox Premium do inventario.")
    @app_commands.describe(quantidade="Quantidade de caixas (1 a 10)")
    async def eco_abrir_premium(self, interaction: discord.Interaction, quantidade: int = 1):
        from .commands.eco_abrir_premium_command import execute

        await execute(self, interaction, quantidade)

    @eco.command(name="loja", description="Mostra a loja de essencias.")
    async def eco_loja(self, interaction: discord.Interaction):
        view = EcoStoreView(self, interaction.user.id, interaction.guild.id)
        await interaction.response.send_message(embed=await view.build_embed(interaction.guild), view=view, ephemeral=True)

    async def _buy_lootbox_for_inventory(self, interaction: discord.Interaction, box_id: str, quantity: int = 1) -> str:
        if not is_db_online():
            return "Banco de dados indisponivel no momento."

        now = self._now_ts()
        key = (interaction.guild.id, interaction.user.id, f"shop_buy_box:{box_id}")
        last = self.action_last_used.get(key, 0)
        remaining = ECONOMY_ACTION_COOLDOWN_SECONDS - (now - last)
        if remaining > 0:
            return "Aguarde alguns segundos para tentar novamente."
        self.action_last_used[key] = now

        user_id = interaction.user.id
        guild_id = interaction.guild.id
        item = LOOTBOX_STORE_ITEMS.get(box_id)
        if not item:
            return "Item de lootbox nao encontrado."
        qty = max(1, min(LOOTBOX_MAX_PURCHASE_QTY, int(quantity)))
        total_cost = int(item["cost_amount"]) * qty
        currency = str(item["cost_currency"])
        inventory_key = str(item["inventory_key"])

        debited = await asyncio.to_thread(self._debit_user_atomic, user_id, guild_id, currency, total_cost)
        if not debited:
            if not is_db_online():
                return "Banco indisponivel ao realizar a compra. Nenhum saldo foi consumido."
            doc = await asyncio.to_thread(self._get_user_doc, user_id, guild_id)
            current = int(doc.get(currency, 0))
            missing = max(total_cost - current, 0)
            return f"Saldo insuficiente: faltam {format_currency_amount(currency, missing)}."

        stored = await asyncio.to_thread(self._credit_user, user_id, guild_id, {inventory_key: qty})
        if not stored:
            refunded = await asyncio.to_thread(self._credit_user, user_id, guild_id, {currency: total_cost})
            if refunded:
                return "Nao foi possivel guardar as caixas compradas. Seu saldo foi devolvido."
            return "Nao foi possivel guardar as caixas nem confirmar o estorno. Acione a staff."
        await asyncio.to_thread(
            eco_logs_col.insert_one,
            {
                "type": "shop_buy_box",
                "user_id": self._uid(user_id),
                "guild_id": self._gid(guild_id),
                "box_id": box_id,
                "inventory_key": inventory_key,
                "quantity": qty,
                "price_currency": currency,
                "price_amount": total_cost,
                "created_at": datetime.now(timezone.utc),
            }
        )
        return (
            f"Voce comprou `{qty}` {item['name']}(s) por {format_currency_amount(currency, total_cost)}.\n"
            "Elas foram adicionadas ao seu inventario."
        )

    async def _purchase_item_result(self, interaction: discord.Interaction, sku: str) -> str:
        if not await ensure_db_online(interaction, "comprar item da economia"):
            return "Banco indisponivel no momento."
        if not await self._check_action_cooldown(interaction, f"shop_buy:{sku}"):
            return "Aguarde alguns segundos para tentar novamente."
        shop = await asyncio.to_thread(eco_shop_col.find_one, {"_id": "main_shop"}) or {"items": {}}
        entry = shop.get("items", {}).get(sku)
        if not entry or not entry.get("enabled", True):
            return "Item nao disponivel no momento."
        if entry.get("stock", 0) <= 0:
            return "Estoque esgotado para este item. Aguarde reposicao."

        inventory_item = VIP_INVENTORY_ITEMS.get(sku)
        if not inventory_item:
            return "Este VIP nao possui configuracao de inventario. Avise a administracao."
        role_id = inventory_item["role_id"]

        reserve_purchase = await asyncio.to_thread(
            self._reserve_shop_purchase_atomic, interaction.user.id, interaction.guild.id, sku
        )
        if reserve_purchase is None:
            return "Banco indisponivel ao reservar a compra. Nenhum saldo foi consumido."
        if not reserve_purchase:
            return "Voce ja comprou este VIP nesta rodada/reposicao da loja (limite 1 por pessoa)."

        price = int(entry["price_essencia"])
        debited = await asyncio.to_thread(self._debit_user_atomic, interaction.user.id, interaction.guild.id, "essencia", price)
        if not debited:
            released = await asyncio.to_thread(
                self._release_shop_purchase_atomic, interaction.user.id, interaction.guild.id, sku
            )
            if not is_db_online() or not released:
                return "Nao foi possivel confirmar a compra nem liberar a reserva. Tente novamente depois ou acione a staff."
            saldo_doc = await asyncio.to_thread(self._get_user_doc, interaction.user.id, interaction.guild.id)
            saldo = int(saldo_doc.get("essencia", 0))
            return f"{format_currency_label('essencia')} insuficiente. Faltam {format_currency_amount('essencia', max(price - saldo, 0))}."

        stock_ok = await asyncio.to_thread(
            eco_shop_col.find_one_and_update,
            {"_id": "main_shop", f"items.{sku}.stock": {"$gte": 1}},
            {"$inc": {f"items.{sku}.stock": -1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        if not stock_ok:
            refunded = await asyncio.to_thread(self._credit_user, interaction.user.id, interaction.guild.id, {"essencia": price})
            released = await asyncio.to_thread(
                self._release_shop_purchase_atomic, interaction.user.id, interaction.guild.id, sku
            )
            if refunded and released:
                return "Estoque mudou durante a compra. Saldo devolvido."
            return "Estoque esgotou durante a compra e nao foi possivel confirmar todo o estorno. Acione a staff."

        stored = await asyncio.to_thread(
            self._credit_user, interaction.user.id, interaction.guild.id, {inventory_item["field"]: 1}
        )
        if not stored:
            log.error("Falha ao guardar VIP comprado no inventario %s", sku)
            refunded = await asyncio.to_thread(self._credit_user, interaction.user.id, interaction.guild.id, {"essencia": price})
            await asyncio.to_thread(
                eco_shop_col.update_one,
                {"_id": "main_shop"},
                {"$inc": {f"items.{sku}.stock": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            )
            released = await asyncio.to_thread(
                self._release_shop_purchase_atomic, interaction.user.id, interaction.guild.id, sku
            )
            if refunded and released:
                return "Nao foi possivel guardar o VIP. Compra desfeita e saldo devolvido."
            return "Nao foi possivel guardar o VIP nem confirmar todo o estorno. Acione a staff."

        try:
            await asyncio.to_thread(
                eco_logs_col.insert_one,
                {
                    "type": "shop_buy",
                    "user_id": self._uid(interaction.user.id),
                    "guild_id": self._gid(interaction.guild.id),
                    "sku": sku,
                    "price_essencia": price,
                    "role_id": role_id,
                    "delivery": "inventory",
                    "inventory_field": inventory_item["field"],
                    "created_at": datetime.now(timezone.utc),
                }
            )
        except Exception:
            log.exception("VIP comprado, mas nao foi possivel registrar log de compra %s", sku)
        await self._record_vip_purchase_transaction(interaction, sku, entry, inventory_item, price)
        return (
            f"Compra concluida: **{format_vip_name_from_item(entry, sku)}** por {format_currency_amount('essencia', price)}. "
            "O VIP foi guardado; use `/eco inventario` para ativar ou doar."
        )

    async def _purchase_item(self, interaction: discord.Interaction, sku: str):
        if not await ensure_db_online(interaction, "comprar item da economia"):
            return
        if not await self._check_action_cooldown(interaction, f"shop_buy:{sku}"):
            return
        shop = await asyncio.to_thread(eco_shop_col.find_one, {"_id": "main_shop"}) or {"items": {}}
        entry = shop.get("items", {}).get(sku)
        if not entry or not entry.get("enabled", True):
            return await self._send_ephemeral(interaction, "Item nao disponivel no momento.")
        if entry.get("stock", 0) <= 0:
            return await self._send_ephemeral(interaction, "Estoque esgotado para este item.")

        item_value = sku
        inventory_item = VIP_INVENTORY_ITEMS.get(item_value)
        if not inventory_item:
            return await self._send_ephemeral(
                interaction, "Este VIP nao possui configuracao de inventario. Avise a administracao."
            )
        role_id = inventory_item["role_id"]

        reserve_purchase = await asyncio.to_thread(
            self._reserve_shop_purchase_atomic, interaction.user.id, interaction.guild.id, item_value
        )
        if reserve_purchase is None:
            return await self._send_ephemeral(
                interaction, "Banco indisponivel ao reservar a compra. Nenhum saldo foi consumido."
            )
        if not reserve_purchase:
            return await self._send_ephemeral(interaction, "Voce ja comprou esse item (limite 1 por pessoa).")

        price = int(entry["price_essencia"])
        debited = await asyncio.to_thread(self._debit_user_atomic, interaction.user.id, interaction.guild.id, "essencia", price)
        if not debited:
            released = await asyncio.to_thread(
                self._release_shop_purchase_atomic, interaction.user.id, interaction.guild.id, item_value
            )
            if not is_db_online() or not released:
                return await self._send_ephemeral(
                    interaction,
                    "Nao foi possivel confirmar a compra nem liberar a reserva. Tente novamente depois ou acione a staff.",
                )
            return await self._send_ephemeral(interaction, f"{format_currency_label('essencia')} insuficiente para esta compra.")

        stock_ok = await asyncio.to_thread(
            eco_shop_col.find_one_and_update,
            {"_id": "main_shop", f"items.{item_value}.stock": {"$gte": 1}},
            {"$inc": {f"items.{item_value}.stock": -1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        if not stock_ok:
            refunded = await asyncio.to_thread(self._credit_user, interaction.user.id, interaction.guild.id, {"essencia": price})
            released = await asyncio.to_thread(
                self._release_shop_purchase_atomic, interaction.user.id, interaction.guild.id, item_value
            )
            if refunded and released:
                return await self._send_ephemeral(interaction, "Estoque mudou durante a compra. Saldo devolvido.")
            return await self._send_ephemeral(
                interaction, "Estoque esgotou durante a compra e nao foi possivel confirmar todo o estorno. Acione a staff."
            )

        stored = await asyncio.to_thread(
            self._credit_user, interaction.user.id, interaction.guild.id, {inventory_item["field"]: 1}
        )
        if not stored:
            log.error("Falha ao guardar VIP comprado no inventario %s", item_value)
            refunded = await asyncio.to_thread(self._credit_user, interaction.user.id, interaction.guild.id, {"essencia": price})
            await asyncio.to_thread(
                eco_shop_col.update_one,
                {"_id": "main_shop"},
                {"$inc": {f"items.{item_value}.stock": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            )
            released = await asyncio.to_thread(
                self._release_shop_purchase_atomic, interaction.user.id, interaction.guild.id, item_value
            )
            if not refunded or not released:
                return await self._send_ephemeral(
                    interaction, "Nao foi possivel guardar o VIP nem confirmar todo o estorno. Acione a staff."
                )
            return await self._send_ephemeral(
                interaction, "Nao foi possivel guardar o VIP. Compra desfeita e saldo devolvido."
            )

        try:
            await asyncio.to_thread(
                eco_logs_col.insert_one,
                {
                    "type": "shop_buy",
                    "user_id": self._uid(interaction.user.id),
                    "guild_id": self._gid(interaction.guild.id),
                    "sku": item_value,
                    "price_essencia": price,
                    "role_id": role_id,
                    "delivery": "inventory",
                    "inventory_field": inventory_item["field"],
                    "created_at": datetime.now(timezone.utc),
                }
            )
        except Exception:
            log.exception("VIP comprado, mas nao foi possivel registrar log de compra %s", item_value)
        await self._record_vip_purchase_transaction(interaction, item_value, entry, inventory_item, price)

        await self._send_ephemeral(
            interaction,
            f"Compra concluida: **{format_vip_name_from_item(entry, item_value)}** por {format_currency_amount('essencia', price)}.\n"
            "O VIP foi guardado; use `/eco inventario` para ativar ou doar.",
        )

    @eco_admin.command(name="set_saldo", description="Define saldo de uma moeda para um usuario.")
    @check_owner_or_perm(allowed_role_id=EVENTS_TEAM_ROLE_ID, administrator=True)
    @app_commands.describe(motivo="Motivo obrigatorio para auditoria da alteracao.")
    @app_commands.choices(
        moeda=[
            Choice(name="Eter", value="eter"),
            Choice(name="Essência", value="essencia"),
            Choice(name="Cristal de Essência", value="cristal_essencia"),
        ]
    )
    async def eco_admin_set_saldo(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        moeda: Choice[str],
        valor: int,
        motivo: str,
    ):
        from .commands.eco_admin_set_saldo_command import execute

        await execute(self, interaction, usuario, moeda, valor, motivo)

    @eco_admin.command(name="add_saldo", description="Adiciona saldo de uma moeda para um usuario.")
    @check_owner_or_perm(allowed_role_id=EVENTS_TEAM_ROLE_ID, administrator=True)
    @app_commands.describe(motivo="Motivo obrigatorio para auditoria da alteracao.")
    @app_commands.choices(
        moeda=[
            Choice(name="Eter", value="eter"),
            Choice(name="Essência", value="essencia"),
            Choice(name="Cristal de Essência", value="cristal_essencia"),
        ]
    )
    async def eco_admin_add_saldo(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        moeda: Choice[str],
        valor: int,
        motivo: str,
    ):
        from .commands.eco_admin_add_saldo_command import execute

        await execute(self, interaction, usuario, moeda, valor, motivo)

    @eco_admin.command(name="restock", description="Repoe estoque da loja.")
    @check_owner_or_perm(administrator=True)
    @app_commands.choices(
        item=[
            Choice(name="Todos", value="all"),
            Choice(name="VIP Berserk", value="vip_berserk_30d"),
            Choice(name="VIP Mugetsu", value="vip_mugetsu_30d"),
            Choice(name="VIP Monarch", value="vip_monarch_30d"),
        ]
    )
    async def eco_admin_restock(self, interaction: discord.Interaction, item: Choice[str], quantidade: int = 0):
        from .commands.eco_admin_restock_command import execute

        await execute(self, interaction, item, quantidade)

    @eco_admin.command(name="leaderboard", description="Leaderboard da economia por tipo de moeda (admin).")
    @check_owner_or_perm(administrator=True)
    async def eco_admin_leaderboard(self, interaction: discord.Interaction):
        from .commands.eco_admin_leaderboard_command import execute

        await execute(self, interaction)

    @eco_admin.command(name="transacoes", description="Lista compras de VIP realizadas na loja da Kaguya.")
    @check_owner_or_perm(administrator=True)
    @app_commands.describe(usuario="Mostra apenas as compras deste membro")
    async def eco_admin_transacoes(self, interaction: discord.Interaction, usuario: discord.Member = None):
        from .commands.eco_admin_transacoes_command import execute

        await execute(self, interaction, usuario)

    @app_commands.command(name="duplicar", description="Ativa ganho 2x da economia por tempo limitado.")
    @check_owner_or_perm(administrator=True)
    @app_commands.describe(
        duracao="Duracao do ganho 2x. Exemplos: 2h, 1d. Use 0 para desativar.",
        motivo="Motivo opcional exibido na confirmacao.",
    )
    async def duplicar(self, interaction: discord.Interaction, duracao: str, motivo: str = ""):
        from .commands.duplicar_command import execute

        await execute(self, interaction, duracao, motivo)

    @app_commands.command(name="admin_reset", description="Reset administrativo da economia (com confirmacao).")
    @check_owner_or_perm(administrator=True)
    @app_commands.choices(
        alvo=[Choice(name="Usuario", value="usuario"), Choice(name="Todos", value="todos")],
        escopo=[
            Choice(name="Tudo", value="tudo"),
            Choice(name="Saldos", value="saldos"),
            Choice(name="Caixas", value="caixas"),
            Choice(name="Limites Loja", value="limites_loja"),
            Choice(name="Historico", value="historico"),
            Choice(name="Estoque Loja", value="estoque_loja"),
            Choice(name="Cooldowns", value="cooldowns"),
        ],
    )
    async def admin_reset(self, interaction: discord.Interaction, alvo: Choice[str], escopo: Choice[str], confirmar: str, usuario: discord.Member = None):
        from .commands.admin_reset_command import execute

        await execute(self, interaction, alvo, escopo, confirmar, usuario)

    async def execute_admin_reset(self, interaction: discord.Interaction, payload: dict) -> str:
        target_mode = payload["target_mode"]
        scope = payload["scope"]
        target_user_id = payload.get("target_user_id")
        guild_id = self._gid(interaction.guild.id)

        counts = {"users": 0, "limits": 0, "logs": 0, "admin_logs": 0}

        async def run_users_update(update_doc):
            if target_mode == "usuario":
                res = await asyncio.to_thread(
                    eco_users_col.update_one,
                    {"_id": self._user_doc_id(target_user_id, interaction.guild.id)},
                    update_doc,
                )
                counts["users"] += int(res.modified_count)
            else:
                res = await asyncio.to_thread(eco_users_col.update_many, {"guild_id": guild_id}, update_doc)
                counts["users"] += int(res.modified_count)

        if scope in {"saldos", "tudo"}:
            await run_users_update({"$set": {"eter": 0, "essencia": 0, "cristal_essencia": 0, "updated_at": datetime.now(timezone.utc)}})

        if scope in {"caixas", "tudo"}:
            reset_fields = {
                "stats.boxes_opened_common": 0,
                "stats.boxes_opened_premium": 0,
                "updated_at": datetime.now(timezone.utc),
            }
            if scope == "tudo":
                reset_fields.update(
                    {
                        "common_box": 0,
                        "premium_box": 0,
                        "vip_inventory": {sku: 0 for sku in VIP_INVENTORY_ITEMS},
                    }
                )
            await run_users_update(
                {
                    "$set": reset_fields
                }
            )

        if scope in {"limites_loja", "tudo"}:
            if target_mode == "usuario":
                res = await asyncio.to_thread(
                    eco_limits_col.delete_one, {"_id": self._limits_doc_id(target_user_id, interaction.guild.id)}
                )
                counts["limits"] += int(res.deleted_count)
            else:
                res = await asyncio.to_thread(eco_limits_col.delete_many, {"guild_id": guild_id})
                counts["limits"] += int(res.deleted_count)

        if scope in {"historico", "tudo"}:
            if target_mode == "usuario":
                q = {"guild_id": guild_id, "user_id": self._uid(target_user_id)}
            else:
                q = {"guild_id": guild_id}
            res = await asyncio.to_thread(eco_logs_col.delete_many, q)
            counts["logs"] += int(res.deleted_count)

        if scope in {"estoque_loja", "tudo"}:
            shop = await asyncio.to_thread(eco_shop_col.find_one, {"_id": "main_shop"}) or {"items": {}}
            sets = {}
            for sku, item in shop.get("items", {}).items():
                sets[f"items.{sku}.stock"] = int(item.get("max_stock", item.get("stock", 0)))
            if sets:
                await asyncio.to_thread(eco_shop_col.update_one, {"_id": "main_shop"}, {"$set": sets}, upsert=True)
            if scope == "estoque_loja":
                await asyncio.to_thread(
                    eco_limits_col.update_many,
                    {"guild_id": guild_id},
                    {"$set": {"purchased_skus": []}},
                )

        if scope in {"cooldowns", "tudo"}:
            if target_mode == "usuario" and target_user_id:
                self.chat_last_earn.pop((interaction.guild.id, target_user_id), None)
                self.voice_eligible_since.pop((interaction.guild.id, target_user_id), None)
            else:
                self.chat_last_earn.clear()
                self.voice_eligible_since.clear()

        admin_log_doc = {
            "type": "admin_reset",
            "guild_id": guild_id,
            "executor_id": self._uid(interaction.user.id),
            "target_mode": target_mode,
            "scope": scope,
            "target_user_id": self._uid(target_user_id) if target_user_id else None,
            "counts": counts,
            "created_at": datetime.now(timezone.utc),
        }
        await asyncio.to_thread(eco_admin_logs_col.insert_one, admin_log_doc)
        counts["admin_logs"] += 1

        await self._log_action(
            interaction.guild,
            "Economia - Admin Reset",
            [
                f"Executor: <@{interaction.user.id}>",
                f"Alvo: {target_mode}",
                f"Escopo: {scope}",
                f"Usuario alvo: {target_user_id or '-'}",
                f"Impacto users/limits/logs: {counts['users']}/{counts['limits']}/{counts['logs']}",
            ],
        )

        return (
            "Reset executado com sucesso.\n"
            f"- users alterados: `{counts['users']}`\n"
            f"- limites removidos: `{counts['limits']}`\n"
            f"- logs removidos: `{counts['logs']}`"
        )


async def setup(bot):
    await bot.add_cog(EconomySystem(bot))
