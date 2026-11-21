import asyncio

import discord

from database import TransactionUnavailable, get_db_failure_generation
from cogs.economia.slot_checkout_view import SlotCheckoutView
from cogs.economia.slot_upgrades import SlotPurchaseError, buy_slot, vip_extras
from utils import bot_can_manage_role


async def read_role(cog, guild, actor_id):
    generation = get_db_failure_generation()
    document = await cog._get_vip_doc(guild, actor_id)
    if get_db_failure_generation() != generation:
        raise TransactionUnavailable("Não consegui confirmar seu registro VIP no banco.")
    if (not document or not document.get("role_id") or document.get("status") != "active"
            or document.get("entitlement_active") is False):
        raise SlotPurchaseError("Você precisa ter um cargo VIP pessoal ativo. Abra `/vip` para gerenciá-lo.")
    try:
        role_id = int(document["role_id"])
    except (TypeError, ValueError) as error:
        raise SlotPurchaseError("O vínculo do cargo VIP está inválido. Consulte a administração.") from error
    try:
        member = await guild.fetch_member(actor_id)
        role = next((role for role in await guild.fetch_roles() if role.id == role_id), None)
    except discord.HTTPException as error:
        raise SlotPurchaseError("Não consegui confirmar seu cargo VIP no Discord. Tente novamente.") from error
    if (not cog._is_personal_vip_role(role) or role.is_default() or str(role.id) == str(document.get("highlight_id"))
            or not bot_can_manage_role(guild, role) or not guild.me.guild_permissions.manage_roles
            or not cog._is_vip_eligible(member) or not any(item.id == role.id for item in member.roles)):
        raise SlotPurchaseError("Seu cargo VIP pessoal precisa estar ativo e disponível para edição.")
    return document, role.id, cog.get_vip_limit(member)


async def execute(cog, interaction):
    await interaction.response.defer(ephemeral=True)
    guild, actor_id = interaction.guild, interaction.user.id
    try:
        document, role_id, base_limit = await read_role(cog, guild, actor_id)
    except (SlotPurchaseError, TransactionUnavailable) as error:
        return await interaction.followup.send(str(error), ephemeral=True)

    count = vip_extras(document, role_id)

    async def purchase(_, operation_id):
        async with cog._get_vip_lock(actor_id, guild.id):
            current, current_role, current_limit = await read_role(cog, guild, actor_id)
            if current["_id"] != document["_id"] or current_role != role_id or current_limit != base_limit:
                raise SlotPurchaseError("Seu cargo ou limite VIP mudou. Abra `/vip_vagas` novamente.")
            return await asyncio.to_thread(buy_slot, "vip", guild.id, actor_id, document["_id"],
                                           count, operation_id, role_id=role_id)

    view = SlotCheckoutView(interaction, "vip", base_limit, count, purchase)
    await interaction.followup.send(view.description(), view=view, ephemeral=True)
