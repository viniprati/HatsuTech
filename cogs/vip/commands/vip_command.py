from __future__ import annotations
from ..cog import *


class VipPanelTypeSelect(ui.Select):
    def __init__(self, cog, cor_primaria: str | None, cor_secundaria: str | None):
        self.cog = cog
        self.cor_primaria = cor_primaria
        self.cor_secundaria = cor_secundaria
        options = [
            discord.SelectOption(
                label="Cargo comum",
                value="common",
                description="Gerencia seu cargo VIP pessoal com membros, notificação e menções.",
                emoji="💎",
            ),
            discord.SelectOption(
                label="Cargo destaque",
                value="highlight",
                description="Gerencia o cargo destaque exclusivo do Monarch.",
                emoji="✨",
            ),
        ]
        super().__init__(placeholder="Escolha qual cargo VIP deseja gerenciar", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "common":
            await open_common_panel(self.cog, interaction, self.cor_primaria, self.cor_secundaria)
            return

        from .vip_highlight_command import execute_highlight

        await execute_highlight(self.cog, interaction, self.cor_primaria, self.cor_secundaria)


class VipPanelTypeView(ui.View):
    def __init__(self, cog, author_id: int, cor_primaria: str | None, cor_secundaria: str | None):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.add_item(VipPanelTypeSelect(cog, cor_primaria, cor_secundaria))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Este painel VIP pertence a outro usuário.", ephemeral=True)
            return False
        return True


async def execute(self, it, cor_primaria: str = None, cor_secundaria: str = None):
    if not await ensure_guild_interaction(it, "o comando /vip"):
        return
    if not await ensure_db_online(it, "o comando /vip"):
        return

    has_common = self.get_vip_limit(it.user) > 0 or has_full_access(it.user)
    has_highlight = self.is_monarch(it.user)
    if not has_common and not has_highlight:
        return await it.response.send_message("🚫 Você não possui VIP.", ephemeral=True)

    embed = discord.Embed(
        title="💎 Painel VIP",
        description=(
            "Selecione abaixo qual cargo deseja gerenciar.\n\n"
            "**Cargo comum**\n"
            "Gerencia seu cargo VIP pessoal, membros, notificação e menções.\n\n"
            "**Cargo destaque**\n"
            "Gerencia o destaque exclusivo do Monarch."
        ),
        color=discord.Color.purple(),
    )
    if cor_primaria or cor_secundaria:
        embed.set_footer(text="As cores informadas serão aplicadas ao cargo escolhido.")

    await it.response.send_message(
        embed=embed,
        view=VipPanelTypeView(self, it.user.id, cor_primaria, cor_secundaria),
        ephemeral=True,
    )


async def open_common_panel(self, it, cor_primaria: str = None, cor_secundaria: str = None):
    await it.response.defer(ephemeral=True)
    if not await ensure_guild_interaction(it, "a opção Cargo comum do /vip"):
        return
    if not await ensure_db_online(it, "a opção Cargo comum do /vip"):
        return
    limit = self.get_vip_limit(it.user)
    if limit == 0 and not has_full_access(it.user):
        return await it.followup.send("🚫 Você não possui VIP.", ephemeral=True)
    position_note = None

    async with self._get_vip_lock(it.user.id, it.guild.id):
        data = await self._get_vip_doc(it.guild, it.user.id)
        rid = data.get("role_id") if data else None
        restore_info = None

        role = None
        if rid is not None:
            try:
                role = it.guild.get_role(int(rid))
            except (TypeError, ValueError):
                role = None

        if not role:
            role, restore_info = await self._restore_vip_role_from_preset(it.user, limit, "command:/vip")
            if not role:
                role_name = self._build_personal_vip_role_name(it.user)
                try:
                    role = await it.guild.create_role(name=role_name, mentionable=False)
                    positioned = await self._position_common_vip_role(it.guild, role)
                    if not positioned:
                        position_note = "⚠️ Não consegui posicionar seu cargo VIP na faixa configurada (âncora ausente ou sem permissão)."
                except discord.Forbidden:
                    return await it.followup.send(
                        "❌ Não tenho permissão para criar cargos VIP (Manage Roles/hierarquia).",
                        ephemeral=True
                    )
                except discord.HTTPException as e:
                    log.error(f"Erro HTTP ao criar cargo VIP para {it.user.id}: {e}")
                    return await it.followup.send(
                        "❌ Falha ao criar seu cargo VIP. Tente novamente em instantes.",
                        ephemeral=True
                    )

        positioned_existing = await self._position_common_vip_role(it.guild, role)
        if not positioned_existing and not position_note:
            position_note = "⚠️ Não consegui reposicionar seu cargo VIP na faixa configurada (âncora ausente ou sem permissão)."

        await self._update_vip_role_with_snapshot(
            it.user.id,
            {
                "$set": {
                    "role_id": str(role.id),
                    "role_source": "command:/vip:common",
                    "status": "active",
                    "entitlement_active": True,
                    "review_required": False,
                    "missing_role": False,
                    "missing_member": False,
                    "last_seen_at": datetime.now(timezone.utc),
                },
                "$unset": {
                    "cleanup_reason": "",
                    "cleanup_source": "",
                    "cleanup_checked_at": "",
                    "disabled_reason": "",
                    "disabled_at": "",
                },
            },
            "command:/vip:common",
            actor_id=it.user.id,
            guild_id=it.guild.id,
            upsert=True
        )

        if role not in it.user.roles:
            try:
                await it.user.add_roles(role)
            except discord.Forbidden:
                return await it.followup.send(
                    "❌ Cargo criado, mas não consegui aplicá-lo por falta de permissão/hierarquia.",
                    ephemeral=True
                )
            except discord.HTTPException as e:
                log.error(f"Erro HTTP ao aplicar cargo VIP {role.id} em {it.user.id}: {e}")
                return await it.followup.send(
                    "❌ Cargo criado, mas não consegui aplicá-lo agora. Tente novamente.",
                    ephemeral=True
                )

        if cor_primaria or cor_secundaria:
            try:
                color_kwargs = build_role_color_kwargs(
                    it.guild,
                    cor_primaria,
                    cor_secundaria,
                    reset_gradient_on_primary_only=True,
                )
                await role.edit(**color_kwargs)
                await it.followup.send(embed=build_color_panel_embed(role), ephemeral=True)
            except ValueError as e:
                return await it.followup.send(f"❌ {e}", ephemeral=True)
            except discord.Forbidden:
                return await it.followup.send("❌ Não tenho permissão para editar as cores deste cargo.", ephemeral=True)
            except discord.HTTPException as e:
                log.error(f"Erro ao editar cores do VIP {role.id}: {e}")
                return await it.followup.send("❌ Não foi possível aplicar as cores agora.", ephemeral=True)

        await it.followup.send(
            embed=discord.Embed(title=f"💎 Painel VIP: {role.name}", color=role.color),
            view=VipMainView(self, role, limit),
            ephemeral=True
        )
        if position_note:
            await it.followup.send(position_note, ephemeral=True)
        if restore_info and restore_info.get("preset_found"):
            await it.followup.send(
                "Preset VIP restaurado: "
                f"{restore_info.get('restored_members', 0)} membros aplicados, "
                f"{restore_info.get('ignored_members', 0)} ignorados.",
                ephemeral=True,
            )
