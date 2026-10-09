import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord import ui
import time
import re
import asyncio
import logging
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone


from admin_audit import send_admin_audit_dm
from database import is_db_online, vip_col, vip_recovery_logs_col, vip_role_presets_col, temp_col


from utils import (
    DISCORD_EMBED_DESCRIPTION_LIMIT,
    check_owner_or_perm,
    process_icon,
    BOT_OWNER_ID,
    has_full_access,
    can_manage_role,
    bot_can_manage_role,
    ensure_db_online,
    ensure_guild_interaction,
    truncate_discord_text,
)

log = logging.getLogger(__name__)
HEX_COLOR_RE = re.compile(r"^[0-9a-fA-F]{6}$")


def parse_hex_color(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    value = raw_value.strip().replace("#", "")
    if not value:
        return None
    if not HEX_COLOR_RE.fullmatch(value):
        raise ValueError("Use formato HEX de 6 dígitos, como #FFAA00.")
    return int(value, 16)


def build_role_color_kwargs(
    guild: discord.Guild,
    primary: str | None,
    secondary: str | None = None,
    reset_gradient_on_primary_only: bool = False,
) -> dict:
    p = parse_hex_color(primary)
    s = parse_hex_color(secondary)

    if p is None and s is not None:
        raise ValueError("Informe a cor primária para usar gradiente.")

    if s is not None and "ENHANCED_ROLE_COLORS" not in guild.features:
        raise ValueError("Este servidor não possui suporte a gradiente de cargos.")

    kwargs = {}
    if p is not None:
        kwargs["color"] = discord.Color(p)
    if s is not None:
        kwargs["secondary_color"] = discord.Color(s)

    if p is not None and s is None and reset_gradient_on_primary_only:
        kwargs["secondary_color"] = None

    return kwargs

def _to_hex(color_obj) -> str:
    if not color_obj:
        return "-"
    return f"#{int(color_obj.value):06X}"


def build_color_panel_embed(role: discord.Role) -> discord.Embed:
    secondary = getattr(role, "secondary_color", None) or getattr(role, "secondary_colour", None)
    mode = "Gradiente" if secondary else "Cor normal"
    explanation = (
        "1 cor (primaria): cor normal.\n"
        "2 cores (primaria + secundaria): gradiente."
    )

    embed = discord.Embed(
        title="Painel de Cores do Cargo",
        description=f"Cargo: {role.mention}\nModo atual: **{mode}**",
        color=role.color,
    )
    embed.add_field(name="Cor primaria", value=_to_hex(role.color), inline=True)
    embed.add_field(name="Cor secundaria", value=_to_hex(secondary), inline=True)
    embed.add_field(name="Como funciona", value=explanation, inline=False)
    return embed


TIME_LITERAL_RE = re.compile(r"^(\d+)([smhd])$")
TIME_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration_literal(value: str) -> int | None:
    m = TIME_LITERAL_RE.fullmatch(str(value).strip().lower())
    if not m:
        return None
    return int(m.group(1)) * TIME_MULTIPLIERS[m.group(2)]


def _to_int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def vip_document_id(guild_id: int | str, user_id: int | str) -> str:
    return f"{guild_id}:{user_id}"


def vip_document_user_id(data: dict) -> str | None:
    user_id = data.get("user_id")
    if user_id is not None:
        return str(user_id)
    raw_id = str(data.get("_id", ""))
    return raw_id.rsplit(":", 1)[-1] if raw_id else None


def _without_snapshot_metadata(data: dict | None) -> dict | None:
    if data is None:
        return None
    ignored = {"last_seen_at", "last_activity_at", "inactivity_observed_at", "highlight_last_activity_at", "highlight_inactivity_observed_at", "cleanup_checked_at", "updated_at"}
    return {key: value for key, value in data.items() if key not in ignored}


def _expected_document_after_update(old_doc: dict, update_payload: dict) -> dict | None:
    if any(operator not in {"$set", "$unset"} for operator in update_payload):
        return None
    expected = dict(old_doc)
    expected.update(update_payload.get("$set", {}))
    for key in update_payload.get("$unset", {}):
        expected.pop(key, None)
    return expected


async def _vip_write_target(user_id: str, guild_id: int | str | None) -> tuple[str, dict | None]:
    legacy = await asyncio.to_thread(vip_col.find_one, {"_id": user_id})
    if guild_id is None:
        return user_id, legacy

    gid = str(guild_id)
    if legacy and legacy.get("guild_id") in (None, "", gid):

        return user_id, legacy

    scoped_id = vip_document_id(gid, user_id)
    scoped = await asyncio.to_thread(vip_col.find_one, {"_id": scoped_id})
    if scoped:
        return scoped_id, scoped


    return user_id if legacy is None else scoped_id, None


async def update_vip_role_with_snapshot(
    user_id: int | str,
    update_doc: dict,
    source: str,
    actor_id: int | str | None = None,
    guild_id: int | str | None = None,
    upsert: bool = False,
):
    uid = str(user_id)
    document_id, old_doc = await _vip_write_target(uid, guild_id)
    update_payload = {operator: dict(values) for operator, values in update_doc.items()}
    if guild_id is not None:
        update_payload.setdefault("$set", {}).update({"guild_id": str(guild_id), "user_id": uid})
    expected_doc = _expected_document_after_update(old_doc, update_payload) if old_doc else None
    if expected_doc and _without_snapshot_metadata(expected_doc) == _without_snapshot_metadata(old_doc):
        return None
    result = await asyncio.to_thread(vip_col.update_one, {"_id": document_id}, update_payload, upsert=upsert)
    new_doc = await asyncio.to_thread(vip_col.find_one, {"_id": document_id})
    if _without_snapshot_metadata(old_doc) == _without_snapshot_metadata(new_doc):
        return result
    action = "create" if old_doc is None and new_doc is not None else "update"

    try:
        await asyncio.to_thread(
            vip_recovery_logs_col.insert_one,
            {
                "type": "vip_role_upsert",
                "action": action,
                "source": source,
                "user_id": uid,
                "document_id": document_id,
                "actor_id": str(actor_id) if actor_id is not None else None,
                "guild_id": str(guild_id) if guild_id is not None else None,
                "old_doc": old_doc,
                "new_doc": new_doc,
                "role_id": new_doc.get("role_id") if new_doc else None,
                "highlight_id": new_doc.get("highlight_id") if new_doc else None,
                "created_at": datetime.now(timezone.utc),
            },
        )
    except Exception as e:
        log.error("Falha ao registrar snapshot vip_roles document_id=%s source=%s: %s", document_id, source, e)

    return result


MONARCH_VIP_ID = 1351596017631494195
MUGETSU_VIP_ID = 1121511055059861524
BERSERK_VIP_ID = 999723165225857074
BOOSTER_PREMIUM_ROLE_ID = 764698895254159391

LOG_CARGOS_ID = 1444675225743528087


VIP_COMMON_TOP_ROLE_ID = 999723169793445938
VIP_COMMON_BOTTOM_ROLE_ID = 999723270263812177



MONARCH_HIGHLIGHT_TOP_ROLE_ID = 1351596516258611260
MONARCH_HIGHLIGHT_BOTTOM_ROLE_ID = 1507906571391467621

VIP_CONFIG = {
    BOOSTER_PREMIUM_ROLE_ID: 20,
    BERSERK_VIP_ID: 20,
    MUGETSU_VIP_ID: 25,
    MONARCH_VIP_ID: 30
}

RESTORE_MEMBER_LIMIT = 20
RESTORE_MEMBER_DELAY_SECONDS = 0.25
RECONCILE_ABSENT_VIP_LIMIT_PER_RUN = 5
RECONCILE_ABSENT_VIP_DELAY_SECONDS = 2.0
MANUAL_VIP_MEMBER_REMOVAL_TTL_SECONDS = 30
COMMON_VIP_INACTIVITY_DAYS = 21
MONARCH_HIGHLIGHT_INACTIVITY_DAYS = 28
COMMON_VIP_ACTIVITY_WRITE_INTERVAL_SECONDS = 300
COMMON_VIP_DELETE_RETRY_SECONDS = 3600
COMMON_VIP_SOURCES = {"command:/vip", "command:/vip:common"}



class NotificationModal(ui.Modal, title="Notificar Cargo"):
    mensagem = ui.TextInput(label="Mensagem", style=discord.TextStyle.paragraph, max_length=2000)
    def __init__(self, role):
        super().__init__()
        self.role = role
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("🔔 Notificado!", ephemeral=True)
        await interaction.channel.send(
            content=f"🔔 **Aviso de {interaction.user.mention}:**\n\n{self.mensagem.value}\n\n|| {self.role.mention} ||",
            allowed_mentions=discord.AllowedMentions(roles=[self.role])
        )

class VipNameModal(ui.Modal, title="Mudar Nome"):
    name = ui.TextInput(label="Novo Nome", max_length=50)
    def __init__(self, role):
        super().__init__()
        self.role = role
    async def on_submit(self, interaction: discord.Interaction):
        blocked = ["admin", "dono", "moderador", "staff", "suporte", "owner"]
        if any(x in self.name.value.lower() for x in blocked):
            return await interaction.response.send_message("❌ Esse nome é proibido.", ephemeral=True)
        await self.role.edit(name=self.name.value)
        await interaction.response.send_message("✅ Nome alterado.", ephemeral=True)

class VipColorModal(ui.Modal, title="Mudar Cor"):
    color = ui.TextInput(label="Cor Primária HEX", placeholder="#FF0000", max_length=7)
    secondary = ui.TextInput(label="Cor Secundária HEX (Opcional)", placeholder="#00AAFF", required=False, max_length=7)
    def __init__(self, role):
        super().__init__()
        self.role = role
    async def on_submit(self, interaction: discord.Interaction):
        try:
            kwargs = build_role_color_kwargs(
                interaction.guild,
                self.color.value,
                self.secondary.value,
                reset_gradient_on_primary_only=True,
            )
            await self.role.edit(**kwargs)
            await interaction.response.send_message("Cor/gradiente alterado!", embed=build_color_panel_embed(self.role), ephemeral=True)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        except Exception:
            return await interaction.response.send_message("❌ Não foi possível atualizar as cores do cargo.", ephemeral=True)

class VipMemberSelect(ui.UserSelect):
    def __init__(self, role, limit):
        super().__init__(placeholder="➕ Adicionar membros...", min_values=1, max_values=25)
        self.role = role; self.limit = limit
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if (len(self.role.members) + len(self.values)) > self.limit:
            return await interaction.followup.send("🚫 Limite excedido.", ephemeral=True)
        added = []
        for m in self.values:
            if self.role not in m.roles:
                try:
                    await m.add_roles(self.role)
                    added.append(m.mention)
                except: pass
        await interaction.followup.send(f"✅ Adicionado: {', '.join(added)}" if added else "Ninguém novo.", ephemeral=True)

class VipMemberRemoveSelect(ui.UserSelect):
    def __init__(self, cog, role):
        super().__init__(placeholder="➖ Remover membros...", min_values=1, max_values=25)
        self.cog = cog
        self.role = role
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        removed = []
        for m in self.values:
            if self.role in m.roles:
                if m.id == interaction.user.id: continue
                try:
                    self.cog._mark_manual_vip_member_removal(m.guild.id, m.id, self.role.id)
                    await m.remove_roles(self.role, reason="VIP painel: membro removido pelo dono do cargo")
                    removed.append(m.mention)
                except: pass
        msg = f"🗑️ Removido: {', '.join(removed)}" if removed else "Ninguém removido."
        await interaction.followup.send(msg, ephemeral=True)

class VipMembersView(ui.View):
    def __init__(self, cog, role, limit):
        super().__init__(timeout=None)
        self.add_item(VipMemberSelect(role, limit))
        self.add_item(VipMemberRemoveSelect(cog, role))


class VipMainView(ui.View):
    def __init__(self, cog, role, limit):
        super().__init__(timeout=None)
        self.cog = cog; self.bot = cog.bot; self.role = role; self.limit = limit
        self._mentionable_state = bool(role.mentionable)
        self._sync_mention_button()

    async def _ensure_owner_binding(self, it: discord.Interaction) -> bool:
        data = await self.cog._get_vip_doc(it.guild, it.user.id)
        role_id = _to_int_or_none(data.get("role_id")) if data else None
        if role_id != self.role.id:
            await it.response.send_message(
                "Este cargo VIP nao esta vinculado ao seu registro. Operacao bloqueada.",
                ephemeral=True,
            )
            return False
        return True

    def _sync_mention_button(self):
        for child in self.children:
            if getattr(child, "custom_id", None) != "vip_toggle_mentionable":
                continue
            if self._mentionable_state:
                child.label = "Mencoes: liberadas"
                child.style = discord.ButtonStyle.success
            else:
                child.label = "Mencoes: bloqueadas"
                child.style = discord.ButtonStyle.secondary
            break

    @ui.button(label="Nome", style=discord.ButtonStyle.primary, row=0)
    async def edit_name(self, it, b):
        if not await self._ensure_owner_binding(it):
            return
        await it.response.send_modal(VipNameModal(self.role))

    @ui.button(label="Cor", style=discord.ButtonStyle.secondary, row=0)
    async def edit_color(self, it, b):
        if not await self._ensure_owner_binding(it):
            return
        await it.response.send_modal(VipColorModal(self.role))

    @ui.button(label="Icone", style=discord.ButtonStyle.success, row=0)
    async def edit_icon(self, it, b):
        if not await self._ensure_owner_binding(it):
            return
        await it.response.send_message("Envie a imagem para o icone do VIP agora (30s).", ephemeral=True)
        try:
            msg = await self.bot.wait_for('message', check=lambda m: m.author.id == it.user.id and m.attachments, timeout=30.0)
            data = await msg.attachments[0].read()
            await self.role.edit(display_icon=process_icon(data))
            await it.followup.send("Icone atualizado.", ephemeral=True)
        except: await it.followup.send("Erro ou tempo esgotado.", ephemeral=True)

    @ui.button(label="Membros", style=discord.ButtonStyle.success, row=1)
    async def manage(self, it, b):
        if not await self._ensure_owner_binding(it):
            return
        members = self.role.members
        desc = "\n".join([f"`{i:02d}.` {m.mention}" for i, m in enumerate(members, 1)]) if members else "Ninguem."
        desc = truncate_discord_text(desc, DISCORD_EMBED_DESCRIPTION_LIMIT, "\n[conteudo truncado]")
        embed = discord.Embed(title=f"Membros VIP: {self.role.name}", description=desc, color=self.role.color)
        embed.set_footer(text=f"Vagas: {len(members)} / {self.limit}")
        await it.response.send_message(embed=embed, view=VipMembersView(self.cog, self.role, self.limit), ephemeral=True)

    @ui.button(label="Notificar", style=discord.ButtonStyle.secondary, row=1)
    async def ping_role(self, it, b):
        if not await self._ensure_owner_binding(it):
            return
        await it.response.send_modal(NotificationModal(self.role))

    @ui.button(label="Mencoes: bloqueadas", style=discord.ButtonStyle.secondary, row=2, custom_id="vip_toggle_mentionable")
    async def toggle_mentionable(self, it, b):
        if not await self._ensure_owner_binding(it):
            return

        new_value = not self._mentionable_state
        try:
            edited_role = await self.role.edit(
                mentionable=new_value,
                reason=f"VIP painel: mencoes alteradas por {it.user} ({it.user.id})",
            )
        except discord.Forbidden:
            return await it.response.send_message(
                "Nao tenho permissao para alterar a permissao de mencao deste cargo.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            log.error("Erro ao alterar mentionable do VIP role_id=%s: %s", self.role.id, e)
            return await it.response.send_message(
                "Nao consegui alterar a permissao de mencao agora. Tente novamente em instantes.",
                ephemeral=True,
            )

        self.role = edited_role or it.guild.get_role(self.role.id) or self.role
        self._mentionable_state = new_value
        self._sync_mention_button()
        status = "liberadas para todos" if self._mentionable_state else "bloqueadas para membros comuns"
        await it.response.edit_message(view=self)
        await it.followup.send(f"Mencoes do cargo agora estao {status}.", ephemeral=True)

    @ui.button(label="Excluir", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, it, b):
        if not await self._ensure_owner_binding(it):
            return
        if not await ensure_db_online(it, "a exclusão do VIP"):
            return
        async with self.cog._get_vip_lock(it.user.id, it.guild.id):
            try:
                await self.role.delete(reason="VIP pessoal excluído pelo dono")
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.warning("vip_owner_delete_failed guild_id=%s user_id=%s role_id=%s error=%s",
                            it.guild.id, it.user.id, self.role.id, exc)
                return await it.response.send_message(
                    "Não consegui excluir o cargo VIP. Verifique minhas permissões e a hierarquia.", ephemeral=True,
                )
            await self.cog._update_vip_role_with_snapshot(
                it.user.id,
                {
                    "$set": {
                        "status": "inactive",
                        "entitlement_active": False,
                        "disabled_reason": "deleted_by_owner",
                        "disabled_at": datetime.now(timezone.utc),
                        "last_role_id": str(self.role.id),
                    },
                    "$unset": {"role_id": ""},
                },
                "vip_panel:delete_role",
                actor_id=it.user.id,
                guild_id=it.guild.id,
            )
            updated = await self.cog._get_vip_doc(it.guild, it.user.id)
            if not updated or updated.get("status") != "inactive":
                log.error("vip_owner_delete_db_failed guild_id=%s user_id=%s role_id=%s",
                          it.guild.id, it.user.id, self.role.id)
                return await it.response.send_message(
                    "O cargo foi excluído, mas não consegui atualizar o registro. Avise a administração.", ephemeral=True,
                )
        await it.response.send_message("VIP deletado.", ephemeral=True); self.stop()


class VipHighlightView(ui.View):
    def __init__(self, cog, role):
        super().__init__(timeout=None)
        self.cog = cog; self.bot = cog.bot; self.role = role

    async def _ensure_owner_binding(self, it: discord.Interaction) -> bool:
        data = await self.cog._get_vip_doc(it.guild, it.user.id)
        role_id = _to_int_or_none(data.get("highlight_id")) if data else None
        if role_id != self.role.id:
            await it.response.send_message(
                "Este destaque nao esta vinculado ao seu registro. Operacao bloqueada.",
                ephemeral=True,
            )
            return False
        return True

    @ui.button(label="Nome", style=discord.ButtonStyle.primary)
    async def edit_name(self, it, b):
        if not await self._ensure_owner_binding(it):
            return
        await it.response.send_modal(VipNameModal(self.role))

    @ui.button(label="Cor", style=discord.ButtonStyle.secondary)
    async def edit_color(self, it, b):
        if not await self._ensure_owner_binding(it):
            return
        await it.response.send_modal(VipColorModal(self.role))

    @ui.button(label="Icone", style=discord.ButtonStyle.success)
    async def edit_icon(self, it, b):
        if not await self._ensure_owner_binding(it):
            return
        await it.response.send_message("Envie a imagem do destaque agora (30s).", ephemeral=True)
        try:
            msg = await self.bot.wait_for('message', check=lambda m: m.author.id == it.user.id and m.attachments, timeout=30.0)
            data = await msg.attachments[0].read()
            await self.role.edit(display_icon=process_icon(data))
            await it.followup.send("Icone atualizado.", ephemeral=True)
        except: await it.followup.send("Erro ou tempo esgotado.", ephemeral=True)

    @ui.button(label="Excluir", style=discord.ButtonStyle.danger)
    async def delete_highlight(self, it, b):
        if not await self._ensure_owner_binding(it):
            return
        if not await ensure_db_online(it, "a exclusão do destaque"):
            return
        async with self.cog._get_vip_lock(it.user.id, it.guild.id):
            try:
                await self.role.delete(reason="Destaque VIP excluído pelo dono")
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.warning("vip_highlight_delete_failed guild_id=%s user_id=%s role_id=%s error=%s",
                            it.guild.id, it.user.id, self.role.id, exc)
                return await it.response.send_message(
                    "Não consegui excluir o destaque. Verifique minhas permissões e a hierarquia.", ephemeral=True,
                )
            await self.cog._update_vip_role_with_snapshot(
                it.user.id,
                {
                    "$set": {
                        "highlight_active": False,
                        "last_highlight_id": str(self.role.id),
                        "highlight_disabled_reason": "deleted_by_owner",
                        "highlight_disabled_at": datetime.now(timezone.utc),
                        "highlight_missing_role": False,
                    },
                    "$unset": {"highlight_id": ""},
                },
                "vip_panel:delete_highlight",
                actor_id=it.user.id,
                guild_id=it.guild.id,
            )
            updated = await self.cog._get_vip_doc(it.guild, it.user.id)
            if not updated or updated.get("highlight_active") is not False:
                log.error("vip_highlight_delete_db_failed guild_id=%s user_id=%s role_id=%s",
                          it.guild.id, it.user.id, self.role.id)
                return await it.response.send_message(
                    "O destaque foi excluído, mas não consegui atualizar o registro. Avise a administração.", ephemeral=True,
                )
        await it.response.send_message("Destaque removido.", ephemeral=True); self.stop()


class VipAdminView(ui.View):
    def __init__(self, data, title, user_id, notice=None):
        super().__init__(timeout=180)
        self.data = data
        self.title = title
        self.user_id = user_id
        self.notice = notice
        self.page = 0
        self.per_page = 5
        self.total_pages = max(1, (len(data) + self.per_page - 1) // self.per_page)
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page == self.total_pages - 1
        self.counter_btn.label = f"Página {self.page + 1}/{self.total_pages}"

    def get_embed(self):
        start = self.page * self.per_page
        current = self.data[start:start+self.per_page]
        description = "\n\n".join(current) or "Nenhum registro encontrado."
        description = truncate_discord_text(description, DISCORD_EMBED_DESCRIPTION_LIMIT, "\n[conteúdo truncado]")
        e = discord.Embed(
            title=self.title,
            description=description,
            color=discord.Color.dark_theme(),
        )
        footer = f"Página {self.page + 1}/{self.total_pages} • {len(self.data)} registro(s)"
        if self.notice:
            footer += f" • {self.notice}"
        e.set_footer(text=footer[:2048])
        return e

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("Somente quem abriu a consulta pode navegar neste painel.", ephemeral=True)
        return False

    @ui.button(label="<", style=discord.ButtonStyle.secondary, disabled=True)
    async def prev_btn(self, it, b):
        self.page -= 1; self.update_buttons(); await it.response.edit_message(embed=self.get_embed(), view=self)
    @ui.button(label="1/1", style=discord.ButtonStyle.gray, disabled=True)
    async def counter_btn(self, it, b): pass
    @ui.button(label=">", style=discord.ButtonStyle.secondary, disabled=True)
    async def next_btn(self, it, b):
        self.page += 1; self.update_buttons(); await it.response.edit_message(embed=self.get_embed(), view=self)


class TempRoleAdjustModal(ui.Modal, title="Remover Tempo do Temprole"):
    dias = ui.TextInput(label="Dias", placeholder="0", required=False, max_length=5)
    horas = ui.TextInput(label="Horas", placeholder="0", required=False, max_length=3)
    minutos = ui.TextInput(label="Minutos", placeholder="0", required=False, max_length=3)
    segundos = ui.TextInput(label="Segundos", placeholder="0", required=False, max_length=3)

    def __init__(self, panel_view):
        super().__init__()
        self.panel_view = panel_view

    @staticmethod
    def _parse_non_negative_int(raw: str) -> int:
        value = str(raw or "").strip()
        if value == "":
            return 0
        if not value.isdigit():
            raise ValueError
        return int(value)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            d = self._parse_non_negative_int(self.dias.value)
            h = self._parse_non_negative_int(self.horas.value)
            m = self._parse_non_negative_int(self.minutos.value)
            s = self._parse_non_negative_int(self.segundos.value)
        except ValueError:
            return await interaction.response.send_message(
                "Formato invalido. Informe apenas numeros inteiros em dias/horas/minutos/segundos.",
                ephemeral=True,
            )

        seconds = (d * 86400) + (h * 3600) + (m * 60) + s
        if seconds <= 0:
            return await interaction.response.send_message(
                "Informe um valor maior que zero em pelo menos um campo.",
                ephemeral=True,
            )
        await self.panel_view.apply_time_reduction(interaction, seconds)


class TempRoleAdjustView(ui.View):
    def __init__(self, author_id: int, member: discord.Member, role: discord.Role):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.member = member
        self.role = role

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Apenas quem abriu o painel pode usar estes botoes.", ephemeral=True)
            return False
        return True

    def _query(self):
        return {
            "user_id": str(self.member.id),
            "guild_id": str(self.member.guild.id),
            "role_id": str(self.role.id),
        }

    def _fmt_remaining(self, end_time: float, now_ts: float) -> str:
        remaining = int(max(end_time - now_ts, 0))
        d = remaining // 86400
        h = (remaining % 86400) // 3600
        m = (remaining % 3600) // 60
        s = remaining % 60
        chunks = []
        if d:
            chunks.append(f"{d}d")
        if h:
            chunks.append(f"{h}h")
        if m:
            chunks.append(f"{m}m")
        if s or not chunks:
            chunks.append(f"{s}s")
        return " ".join(chunks)

    async def _fetch_doc(self):
        return await asyncio.to_thread(temp_col.find_one, self._query())

    async def build_embed(self) -> discord.Embed:
        now_ts = time.time()
        data = await self._fetch_doc()
        embed = discord.Embed(
            title="Painel de Ajuste de Temprole",
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="Usuario", value=self.member.mention, inline=True)
        embed.add_field(name="Cargo", value=self.role.mention, inline=True)

        if not data:
            embed.add_field(name="Status", value="Nenhum registro ativo encontrado.", inline=False)
            embed.set_footer(text="Use /temprole para adicionar novamente.")
            return embed

        end_time = float(data.get("end_time", 0))
        status = "Ativo" if end_time > now_ts else "Expirado"
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Expira em", value=f"<t:{int(end_time)}:F>", inline=True)
        embed.add_field(name="Restante", value=f"`{self._fmt_remaining(end_time, now_ts)}`", inline=True)
        embed.add_field(
            name="Acoes disponiveis",
            value="Use os botoes abaixo para remover tempo em blocos ou abrir ajuste customizado.",
            inline=False,
        )
        embed.set_footer(text="Quando o tempo chegar a 0, o temprole e removido automaticamente.")
        return embed

    async def _remove_role_from_member(self):
        if self.role not in self.member.roles:
            return True
        try:
            await self.member.remove_roles(self.role, reason="Temprole removido pelo painel admin")
            return True
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            log.warning("temprole_manual_removal_failed guild_id=%s user_id=%s role_id=%s error=%s",
                        self.member.guild.id, self.member.id, self.role.id, exc)
            return False

    async def apply_time_reduction(self, interaction: discord.Interaction, seconds: int):
        if seconds <= 0:
            return await interaction.response.send_message("O valor precisa ser maior que zero.", ephemeral=True)

        data = await self._fetch_doc()
        if not data:
            embed = await self.build_embed()
            return await interaction.response.edit_message(embed=embed, view=self)

        now_ts = time.time()
        current_end = float(data.get("end_time", 0))
        new_end = current_end - float(seconds)

        if new_end <= now_ts:
            if not await self._remove_role_from_member():
                return await interaction.response.send_message(
                    "Não consegui retirar o cargo. Verifique minhas permissões e a hierarquia; o tempo foi mantido para nova tentativa.",
                    ephemeral=True,
                )
            await asyncio.to_thread(temp_col.delete_one, {"_id": data["_id"]})
            embed = await self.build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send("Tempo removido. O temprole foi encerrado.", ephemeral=True)
            if self.role.id in VIP_CONFIG:
                await send_admin_audit_dm(
                    interaction.client,
                    category="vip",
                    action="Temprole VIP encerrado",
                    guild=self.member.guild,
                    actor=interaction.user,
                    target=self.member,
                    details={
                        "Cargo": f"{self.role.mention} (`{self.role.id}`)",
                        "Expiração anterior": f"<t:{int(current_end)}:F>",
                        "Tempo removido": self._fmt_remaining(seconds, 0),
                    },
                    source="command:/temprole_remover",
                )
            return

        await asyncio.to_thread(
            temp_col.update_one,
            {"_id": data["_id"]},
            {"$set": {"end_time": new_end}},
        )
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
        if self.role.id in VIP_CONFIG:
            await send_admin_audit_dm(
                interaction.client,
                category="vip",
                action="Temprole VIP reduzido",
                guild=self.member.guild,
                actor=interaction.user,
                target=self.member,
                details={
                    "Cargo": f"{self.role.mention} (`{self.role.id}`)",
                    "Expiração anterior": f"<t:{int(current_end)}:F>",
                    "Nova expiração": f"<t:{int(new_end)}:F>",
                    "Tempo removido": self._fmt_remaining(seconds, 0),
                },
                source="command:/temprole_remover",
            )

    async def remove_all(self, interaction: discord.Interaction):
        existing = await self._fetch_doc()
        if existing and not await self._remove_role_from_member():
            return await interaction.response.send_message(
                "Não consegui retirar o cargo. Verifique minhas permissões e a hierarquia; o registro foi mantido.",
                ephemeral=True,
            )
        result = await asyncio.to_thread(temp_col.delete_many, self._query())
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
        if existing and getattr(result, "deleted_count", 0) > 0 and self.role.id in VIP_CONFIG:
            await send_admin_audit_dm(
                interaction.client,
                category="vip",
                action="Temprole VIP removido",
                guild=self.member.guild,
                actor=interaction.user,
                target=self.member,
                details={
                    "Cargo": f"{self.role.mention} (`{self.role.id}`)",
                    "Expiração anterior": f"<t:{int(float(existing.get('end_time', 0)))}:F>",
                },
                source="command:/temprole_remover",
            )

    @ui.button(label="-10m", style=discord.ButtonStyle.secondary, row=0)
    async def minus_10m(self, interaction: discord.Interaction, button: ui.Button):
        await self.apply_time_reduction(interaction, 600)

    @ui.button(label="-1h", style=discord.ButtonStyle.secondary, row=0)
    async def minus_1h(self, interaction: discord.Interaction, button: ui.Button):
        await self.apply_time_reduction(interaction, 3600)

    @ui.button(label="-6h", style=discord.ButtonStyle.secondary, row=0)
    async def minus_6h(self, interaction: discord.Interaction, button: ui.Button):
        await self.apply_time_reduction(interaction, 21600)

    @ui.button(label="-1d", style=discord.ButtonStyle.secondary, row=0)
    async def minus_1d(self, interaction: discord.Interaction, button: ui.Button):
        await self.apply_time_reduction(interaction, 86400)

    @ui.button(label="Ajuste Custom", style=discord.ButtonStyle.primary, row=1)
    async def custom_adjust(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(TempRoleAdjustModal(self))

    @ui.button(label="Remover Total", style=discord.ButtonStyle.danger, row=1)
    async def remove_total(self, interaction: discord.Interaction, button: ui.Button):
        await self.remove_all(interaction)

    @ui.button(label="Atualizar", style=discord.ButtonStyle.success, row=1)
    async def refresh(self, interaction: discord.Interaction, button: ui.Button):
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)


class VipSystem(commands.Cog):
    cargo_temporario = app_commands.Group(
        name="cargo_temporario",
        description="Conceder, consultar e ajustar cargos com prazo de validade.",
    )

    def __init__(self, bot):
        self.bot = bot
        self._vip_locks = {}
        self._manual_vip_member_removals = {}
        self._common_vip_owners = {}
        self._common_vip_activity_written = {}
        self._monarch_highlight_owners = {}
        self._monarch_highlight_activity_written = {}
        self._common_vip_cache_loaded = False
        self._monarch_highlight_cache_loaded = False
        if not self.check_temproles.is_running():
            self.check_temproles.start()
        if not self.reconcile_absent_vips.is_running():
            self.reconcile_absent_vips.start()
        if not self.check_inactive_common_vips.is_running():
            self.check_inactive_common_vips.start()
        if not self.check_inactive_monarch_highlights.is_running():
            self.check_inactive_monarch_highlights.start()

    def cog_unload(self):
        if self.check_temproles.is_running():
            self.check_temproles.cancel()
        if self.reconcile_absent_vips.is_running():
            self.reconcile_absent_vips.cancel()
        if self.check_inactive_common_vips.is_running():
            self.check_inactive_common_vips.cancel()
        if self.check_inactive_monarch_highlights.is_running():
            self.check_inactive_monarch_highlights.cancel()


    def get_vip_limit(self, member):
        limit = 0
        for vid, max_m in VIP_CONFIG.items():
            if any(r.id == vid for r in member.roles) and max_m > limit: limit = max_m
        return limit

    def is_monarch(self, member):
        return any(r.id == MONARCH_VIP_ID for r in member.roles) or has_full_access(member)

    def _get_vip_lock(self, user_id: int, guild_id: int | None = None) -> asyncio.Lock:
        key = (guild_id, user_id)
        lock = self._vip_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._vip_locks[key] = lock
        return lock

    def _cleanup_manual_vip_member_removals(self, now: float | None = None):
        now = now or time.time()
        expired = [key for key, expires_at in self._manual_vip_member_removals.items() if expires_at <= now]
        for key in expired:
            self._manual_vip_member_removals.pop(key, None)

    def _mark_manual_vip_member_removal(self, guild_id: int, user_id: int, role_id: int):
        now = time.time()
        self._cleanup_manual_vip_member_removals(now)
        key = (int(guild_id), int(user_id), int(role_id))
        self._manual_vip_member_removals[key] = now + MANUAL_VIP_MEMBER_REMOVAL_TTL_SECONDS

    def _consume_manual_vip_member_removal(self, guild_id: int, user_id: int, role_id: int) -> bool:
        now = time.time()
        self._cleanup_manual_vip_member_removals(now)
        key = (int(guild_id), int(user_id), int(role_id))
        expires_at = self._manual_vip_member_removals.pop(key, None)
        return bool(expires_at and expires_at > now)

    def _is_vip_eligible(self, member: discord.Member) -> bool:
        return any(r.id in VIP_CONFIG for r in member.roles) or has_full_access(member)

    def _is_personal_vip_role(self, role: discord.Role | None) -> bool:
        return bool(role and not role.managed and role.id not in VIP_CONFIG)

    def _build_personal_vip_role_name(self, member: discord.Member) -> str:

        return member.display_name[:100]

    def _legacy_doc_belongs_to_guild(self, guild: discord.Guild, data: dict) -> bool:
        if data.get("guild_id") is not None:
            return str(data.get("guild_id")) == str(guild.id)
        for key in ("role_id", "highlight_id"):
            role_id = _to_int_or_none(data.get(key))
            if role_id is not None and guild.get_role(role_id) is not None:
                return True
        return False

    async def _get_vip_doc(self, guild: discord.Guild, user_id: int | str) -> dict | None:
        uid = str(user_id)
        legacy = await asyncio.to_thread(vip_col.find_one, {"_id": uid})
        if legacy and self._legacy_doc_belongs_to_guild(guild, legacy):
            return legacy

        document_id = vip_document_id(guild.id, uid)
        data = await asyncio.to_thread(vip_col.find_one, {"_id": document_id})
        if data:
            return data

        return None

    async def _log_role_recovery(self, member: discord.Member, role: discord.Role, source: str):
        try:
            await asyncio.to_thread(
                vip_recovery_logs_col.insert_one,
                {
                    "type": "vip_role_recovery",
                    "source": source,
                    "user_id": str(member.id),
                    "guild_id": str(member.guild.id),
                    "role_id": str(role.id),
                    "created_at": datetime.now(timezone.utc),
                },
            )
        except Exception as e:
            log.error("Falha ao registrar recuperacao VIP user_id=%s source=%s: %s", member.id, source, e)

    async def _position_role_between(
        self,
        guild: discord.Guild,
        role: discord.Role,
        first_anchor_id: int,
        second_anchor_id: int,
        label: str,
    ) -> bool:
        first_anchor = guild.get_role(first_anchor_id)
        second_anchor = guild.get_role(second_anchor_id)
        if not first_anchor or not second_anchor:
            return False

        lower_anchor, upper_anchor = sorted(
            (first_anchor, second_anchor),
            key=lambda anchor: anchor.position,
        )
        target_position = lower_anchor.position + 1
        if lower_anchor.position < role.position < upper_anchor.position:
            return True
        try:
            await role.edit(
                position=target_position,
                reason=(
                    f"Auto-posicionamento {label} entre "
                    f"{first_anchor_id} e {second_anchor_id}"
                ),
            )
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def _position_common_vip_role(self, guild: discord.Guild, role: discord.Role) -> bool:
        return await self._position_role_between(
            guild,
            role,
            VIP_COMMON_TOP_ROLE_ID,
            VIP_COMMON_BOTTOM_ROLE_ID,
            "VIP comum",
        )

    async def _position_monarch_highlight_role(self, guild: discord.Guild, role: discord.Role) -> bool:
        return await self._position_role_between(
            guild,
            role,
            MONARCH_HIGHLIGHT_TOP_ROLE_ID,
            MONARCH_HIGHLIGHT_BOTTOM_ROLE_ID,
            "destaque Monarch",
        )

    async def _get_guild_member_safe(self, guild: discord.Guild, user_id) -> discord.Member | None:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return None
        member = guild.get_member(uid)
        if member:
            return member
        try:
            return await guild.fetch_member(uid)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _find_manual_role_change_actor(
        self,
        member: discord.Member,
        changed_role_ids: set[int],
    ) -> tuple[discord.abc.User | None, str | None]:
        after_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        for attempt in range(3):
            await asyncio.sleep(0.75)
            try:
                async for entry in member.guild.audit_logs(
                    limit=8,
                    action=discord.AuditLogAction.member_role_update,
                    after=after_time,
                ):
                    if getattr(entry.target, "id", None) != member.id:
                        continue
                    audit_roles = {
                        role.id
                        for diff in (entry.before, entry.after)
                        for role in (getattr(diff, "roles", None) or [])
                    }
                    if changed_role_ids & audit_roles:
                        return entry.user, entry.reason
            except discord.Forbidden:
                log.warning("vip_manual_audit_missing_permission guild_id=%s", member.guild.id)
                return None, None
            except discord.HTTPException as exc:
                log.warning(
                    "vip_manual_audit_lookup_failed guild_id=%s status=%s attempt=%s",
                    member.guild.id,
                    exc.status,
                    attempt + 1,
                )
        return None, None

    async def _audit_manual_vip_role_change(self, before: discord.Member, after: discord.Member):
        before_role_ids = {role.id for role in before.roles}
        after_role_ids = {role.id for role in after.roles}
        added_ids = (after_role_ids - before_role_ids) & set(VIP_CONFIG)
        removed_ids = (before_role_ids - after_role_ids) & set(VIP_CONFIG)
        if not added_ids and not removed_ids:
            return

        actor, reason = await self._find_manual_role_change_actor(after, added_ids | removed_ids)
        if actor is None or getattr(actor, "bot", False):
            return
        if self.bot.user and actor.id == self.bot.user.id:
            return

        role_lines = []
        for role_id in sorted(added_ids):
            role = after.guild.get_role(role_id)
            role_lines.append(f"Adicionado: {role.mention if role else role_id} (`{role_id}`)")
        for role_id in sorted(removed_ids):
            role = after.guild.get_role(role_id)
            role_lines.append(f"Removido: {role.mention if role else role_id} (`{role_id}`)")

        if added_ids and removed_ids:
            action = "VIP alterado manualmente"
        elif added_ids:
            action = "VIP concedido manualmente"
        else:
            action = "VIP removido manualmente"
        await send_admin_audit_dm(
            self.bot,
            category="vip",
            action=action,
            guild=after.guild,
            actor=actor,
            target=after,
            reason=reason or "Alteração manual de cargo no Discord",
            details={"Cargos": "\n".join(role_lines)},
            source="discord_audit_log:member_role_update",
        )

    async def enviar_log(self, g, t, f, c=discord.Color.blue()):
        ch = g.get_channel(LOG_CARGOS_ID)
        if ch:
            e = discord.Embed(title=t, color=c, timestamp=datetime.now())
            for n,v in f: e.add_field(name=n, value=v, inline=False)
            await ch.send(embed=e)

    async def _update_vip_role_with_snapshot(
        self,
        user_id: int | str,
        update_doc: dict,
        source: str,
        actor_id: int | str | None = None,
        guild_id: int | str | None = None,
        upsert: bool = False,
    ):
        return await update_vip_role_with_snapshot(user_id, update_doc, source, actor_id, guild_id, upsert)

    def _preset_id(self, guild_id: int | str, user_id: int | str) -> str:
        return f"{guild_id}:{user_id}"

    async def archive_vip_role_preset(
        self,
        member: discord.Member,
        role: discord.Role,
        reason: str,
        source: str,
    ) -> bool:
        now = datetime.now(timezone.utc)
        preset_id = self._preset_id(member.guild.id, member.id)
        old_preset = await asyncio.to_thread(vip_role_presets_col.find_one, {"_id": preset_id})
        member_ids = [str(m.id) for m in role.members]
        preset_doc = {
            "user_id": str(member.id),
            "guild_id": str(member.guild.id),
            "last_role_id": str(role.id),
            "role_name": role.name,
            "color": int(role.color.value),
            "hoist": bool(role.hoist),
            "mentionable": bool(role.mentionable),
            "member_ids": member_ids,
            "archived_at": now,
            "updated_at": now,
            "reason": reason,
            "source": source,
        }
        try:
            await asyncio.to_thread(
                vip_role_presets_col.update_one,
                {"_id": preset_id},
                {"$set": preset_doc, "$setOnInsert": {"_id": preset_id}},
                upsert=True,
            )
            new_preset = await asyncio.to_thread(vip_role_presets_col.find_one, {"_id": preset_id})
            await asyncio.to_thread(
                vip_recovery_logs_col.insert_one,
                {
                    "type": "vip_role_preset_archive",
                    "user_id": str(member.id),
                    "guild_id": str(member.guild.id),
                    "last_role_id": str(role.id),
                    "old_doc": old_preset,
                    "new_doc": new_preset,
                    "reason": reason,
                    "source": source,
                    "created_at": now,
                },
            )
            return True
        except Exception as e:
            log.error("Falha ao arquivar preset VIP user_id=%s role_id=%s source=%s: %s", member.id, role.id, source, e)
            return False

    async def _restore_vip_role_from_preset(
        self,
        member: discord.Member,
        limit: int,
        source: str,
    ) -> tuple[discord.Role | None, dict]:
        preset_id = self._preset_id(member.guild.id, member.id)
        preset = await asyncio.to_thread(vip_role_presets_col.find_one, {"_id": preset_id})
        if not preset:
            return None, {"preset_found": False, "restored_members": 0, "ignored_members": 0}

        try:
            color = discord.Color(int(preset.get("color", 0) or 0))
        except (TypeError, ValueError):
            color = discord.Color.default()
        role_name = str(preset.get("role_name") or self._build_personal_vip_role_name(member))[:100]

        try:
            role = await member.guild.create_role(
                name=role_name,
                color=color,
                hoist=bool(preset.get("hoist", False)),
                mentionable=bool(preset.get("mentionable", False)),
                reason="Restauracao de preset VIP",
            )
            await self._position_common_vip_role(member.guild, role)
        except (discord.Forbidden, discord.HTTPException) as e:
            log.error("Falha ao recriar cargo VIP por preset user_id=%s: %s", member.id, e)
            return None, {"preset_found": True, "restored_members": 0, "ignored_members": 0, "error": str(e)}

        member_ids = [str(member.id)]
        for uid in preset.get("member_ids", []):
            if str(uid) not in member_ids:
                member_ids.append(str(uid))

        restored = 0
        ignored = 0
        max_members = min(max(int(limit or 1), 1), RESTORE_MEMBER_LIMIT)
        for uid in member_ids[:max_members]:
            target = await self._get_guild_member_safe(member.guild, uid)
            if not target:
                ignored += 1
                continue
            if role in target.roles:
                restored += 1
                continue
            try:
                await target.add_roles(role, reason="Restauracao de membros do preset VIP")
                restored += 1
                await asyncio.sleep(RESTORE_MEMBER_DELAY_SECONDS)
            except (discord.Forbidden, discord.HTTPException):
                ignored += 1

        ignored += max(0, len(member_ids) - max_members)
        await asyncio.to_thread(
            vip_recovery_logs_col.insert_one,
            {
                "type": "vip_role_preset_restore",
                "user_id": str(member.id),
                "guild_id": str(member.guild.id),
                "preset_id": preset_id,
                "new_role_id": str(role.id),
                "restored_members": restored,
                "ignored_members": ignored,
                "source": source,
                "created_at": datetime.now(timezone.utc),
            },
        )
        return role, {
            "preset_found": True,
            "restored_members": restored,
            "ignored_members": ignored,
        }

    async def _deactivate_personal_vip_role(
        self,
        member: discord.Member,
        role: discord.Role | None,
        reason: str,
        source: str,
    ) -> bool:
        last_role_id = str(role.id) if role else None
        if last_role_id is None:
            data = await self._get_vip_doc(member.guild, member.id)
            if data and data.get("role_id") is not None:
                last_role_id = str(data.get("role_id"))
        personal_role = role if self._is_personal_vip_role(role) else None
        archived = True
        if personal_role:
            archived = await self.archive_vip_role_preset(member, personal_role, reason, source)
        if not archived:
            await self._mark_vip_needs_review(member.id, "preset_archive_failed", source, member.guild, old_doc=None)
            return False

        now = datetime.now(timezone.utc)
        sets = {
            "status": "inactive",
            "entitlement_active": False,
            "disabled_reason": reason,
            "disabled_at": now,
            "last_role_id": last_role_id,
            "missing_role": role is None,
        }
        await self._update_vip_role_with_snapshot(
            member.id,
            {"$set": sets},
            f"{source}:deactivate",
            guild_id=member.guild.id,
        )
        if personal_role:
            try:
                await personal_role.delete(reason=f"VIP pessoal desativado: {reason}")
            except (discord.Forbidden, discord.HTTPException) as e:
                log.warning("Nao foi possivel remover cargo VIP desativado user_id=%s role_id=%s: %s", member.id, personal_role.id, e)
        elif role:
            log.warning("Cargo VIP nao pessoal preservado em desativacao user_id=%s role_id=%s", member.id, role.id)
        return True

    async def _deactivate_monarch_highlight_role(
        self,
        member: discord.Member,
        role: discord.Role | None,
        reason: str,
        source: str,
    ) -> bool:
        doc = await self._get_vip_doc(member.guild, member.id)
        if not doc or not doc.get("highlight_id"):
            return False
        return await self._remove_monarch_highlight(member, doc, reason, source)

    async def _record_highlight_delete_failure(self, member: discord.Member, reason: str, source: str, error: str):
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=COMMON_VIP_DELETE_RETRY_SECONDS)
        await self._update_vip_role_with_snapshot(
            member.id,
            {"$set": {"highlight_review_required": True, "highlight_cleanup_reason": "highlight_delete_failed",
                      "highlight_delete_reason": reason, "highlight_cleanup_source": source,
                      "highlight_cleanup_checked_at": datetime.now(timezone.utc), "highlight_retry_after": retry_at}},
            f"{source}:highlight_delete_failed", guild_id=member.guild.id,
        )
        log.warning("monarch_highlight_delete_failed guild_id=%s user_id=%s reason=%s error=%s",
                    member.guild.id, member.id, reason, error)

    async def _remove_monarch_highlight(self, member: discord.Member, doc: dict, reason: str, source: str) -> bool:
        guild = member.guild
        role_id = _to_int_or_none(doc.get("highlight_id"))
        if not role_id or not is_db_online():
            return False
        role = guild.get_role(role_id)
        if role is None:
            try:
                role = next((candidate for candidate in await guild.fetch_roles() if candidate.id == role_id), None)
            except (discord.Forbidden, discord.HTTPException) as exc:
                await self._record_highlight_delete_failure(member, reason, source, type(exc).__name__)
                return False
        if role and (not self._is_personal_vip_role(role) or role.id == _to_int_or_none(doc.get("role_id"))
                     or not bot_can_manage_role(guild, role)):
            await self._record_highlight_delete_failure(member, reason, source, "unsafe_role_or_hierarchy")
            return False
        conflicting = await asyncio.to_thread(
            vip_col.find_one,
            {"_id": {"$ne": doc["_id"]}, "$or": [
                {"highlight_id": {"$in": [str(role_id), role_id]}},
                {"role_id": {"$in": [str(role_id), role_id]}},
            ]},
        )
        if not is_db_online():
            return False
        if conflicting:
            await self._record_highlight_delete_failure(member, reason, source, "shared_role")
            return False
        if doc.get("guild_id") is None:
            scoped = await asyncio.to_thread(
                vip_col.update_one,
                {"_id": doc["_id"], "highlight_id": doc["highlight_id"], "guild_id": {"$exists": False}},
                {"$set": {"guild_id": str(guild.id), "user_id": str(member.id)}},
            )
            if not is_db_online() or not scoped or not scoped.matched_count:
                return False
        if role:
            try:
                await role.delete(reason=f"Destaque Monarch desativado: {reason}")
            except discord.NotFound:
                role = None
            except (discord.Forbidden, discord.HTTPException) as exc:
                await self._record_highlight_delete_failure(member, reason, source, type(exc).__name__)
                return False
        now = datetime.now(timezone.utc)
        await self._update_vip_role_with_snapshot(
            member.id,
            {"$set": {"highlight_active": False, "highlight_review_required": False,
                      "highlight_disabled_reason": reason, "highlight_disabled_at": now,
                      "last_highlight_id": str(role_id), "highlight_missing_role": role is None,
                      "highlight_deleted_at": now},
             "$unset": {"highlight_id": "", "highlight_cleanup_reason": "", "highlight_cleanup_source": "",
                        "highlight_cleanup_checked_at": "", "highlight_delete_reason": "", "highlight_retry_after": ""}},
            f"{source}:deactivate_highlight", guild_id=guild.id,
        )
        saved = await asyncio.to_thread(vip_col.find_one, {"_id": doc["_id"]})
        if not saved or saved.get("highlight_id") is not None or saved.get("highlight_active") is not False:
            log.error("monarch_highlight_state_not_saved guild_id=%s user_id=%s role_id=%s", guild.id, member.id, role_id)
            return False
        self._monarch_highlight_owners.pop((guild.id, member.id), None)
        log.info("monarch_highlight_deleted guild_id=%s user_id=%s role_id=%s reason=%s", guild.id, member.id, role_id, reason)
        try:
            await self.enviar_log(
                guild, "Destaque Monarch excluído",
                [("Dono", member.mention), ("Cargo", f"{role.name if role else 'Cargo ausente'} (`{role_id}`)"),
                 ("Motivo", reason)], discord.Color.orange(),
            )
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            log.warning("monarch_highlight_audit_channel_failed guild_id=%s role_id=%s error=%s", guild.id, role_id, exc)
        return True

    async def _mark_highlight_needs_review(
        self,
        member: discord.Member,
        reason: str,
        source: str,
        old_doc: dict | None = None,
    ) -> bool:
        data = old_doc if old_doc is not None else await self._get_vip_doc(member.guild, member.id)
        if not data:
            return False
        if (
            data.get("highlight_review_required")
            and data.get("highlight_cleanup_reason") == reason
            and data.get("highlight_missing_role")
        ):
            return False

        await self._update_vip_role_with_snapshot(
            member.id,
            {
                "$set": {
                    "highlight_review_required": True,
                    "highlight_missing_role": True,
                    "highlight_cleanup_reason": reason,
                    "highlight_cleanup_source": source,
                    "highlight_cleanup_checked_at": datetime.now(timezone.utc),
                }
            },
            f"{source}:highlight_needs_review",
            guild_id=member.guild.id,
        )
        return True

    async def _member_still_in_guild(self, guild: discord.Guild, user_id: int) -> bool:
        if guild.get_member(user_id):
            return True
        try:
            await guild.fetch_member(user_id)
            return True
        except discord.NotFound:
            return False
        except (discord.Forbidden, discord.HTTPException):

            return True

    def _vip_doc_belongs_to_guild(self, guild: discord.Guild, data: dict) -> bool:
        guild_id = data.get("guild_id")
        if guild_id is not None:
            return str(guild_id) == str(guild.id)

        return self._legacy_doc_belongs_to_guild(guild, data)

    def _already_reviewing_absent_member(self, data: dict) -> bool:
        return bool(
            data.get("status") == "needs_review"
            and data.get("review_required")
            and data.get("missing_member")
            and data.get("cleanup_reason") == "member_not_found"
        )

    async def _mark_vip_needs_review(
        self,
        user_id: int,
        reason: str,
        source: str,
        guild: discord.Guild | None = None,
        missing_member: bool = False,
        missing_role: bool = False,
        old_doc: dict | None = None,
    ) -> bool:
        uid = str(user_id)
        now = datetime.now(timezone.utc)
        data = old_doc if old_doc is not None else (
            await self._get_vip_doc(guild, uid) if guild else await asyncio.to_thread(vip_col.find_one, {"_id": uid})
        )
        if not data:
            return False
        if (
            data.get("status") == "needs_review"
            and bool(data.get("review_required"))
            and data.get("cleanup_reason") == reason
            and bool(data.get("missing_member")) == bool(missing_member)
            and bool(data.get("missing_role")) == bool(missing_role)
        ):
            return False

        await asyncio.to_thread(
            vip_recovery_logs_col.insert_one,
            {
                "type": "vip_role_delete_attempt",
                "user_id": uid,
                "old_doc": data,
                "reason": reason,
                "source": source,
                "created_at": now,
            },
        )
        await self._update_vip_role_with_snapshot(
            uid,
            {
                "$set": {
                    "status": "needs_review",
                    "review_required": True,
                    "missing_member": bool(missing_member),
                    "missing_role": bool(missing_role),
                    "cleanup_reason": reason,
                    "cleanup_source": source,
                    "cleanup_checked_at": now,
                }
            },
            f"{source}:needs_review",
            guild_id=guild.id if guild else None,
        )
        log.warning("VIP permanente marcado para revisao: user_id=%s source=%s reason=%s", uid, source, reason)
        if guild:
            await self.enviar_log(
                guild,
                "VIP Marcado para Revisao",
                [
                    ("User", f"ID {user_id}"),
                    ("Origem", source),
                    ("Motivo", reason),
                    ("Registro DB", "Mantido em vip_roles com status needs_review"),
                ],
                discord.Color.orange(),
            )
        return True

    async def _cleanup_absent_vip_owner(self, guild: discord.Guild, user_id: int, source: str) -> bool:
        if await self._member_still_in_guild(guild, user_id):
            return False

        uid = str(user_id)
        gid = str(guild.id)
        data = await self._get_vip_doc(guild, uid)
        if not data:
            await asyncio.to_thread(temp_col.delete_many, {"user_id": uid, "guild_id": gid})
            return True
        if not self._vip_doc_belongs_to_guild(guild, data):
            await asyncio.to_thread(temp_col.delete_many, {"user_id": uid, "guild_id": gid})
            return True

        missing_role = False
        for key in ("role_id", "highlight_id"):
            rid = data.get(key)
            if rid is None:
                continue
            try:
                if guild.get_role(int(rid)) is None:
                    missing_role = True
            except (TypeError, ValueError):
                missing_role = True

        await self._mark_vip_needs_review(
            user_id,
            "member_not_found",
            source,
            guild,
            missing_member=True,
            missing_role=missing_role,
            old_doc=data,
        )
        await asyncio.to_thread(temp_col.delete_many, {"user_id": uid, "guild_id": gid})
        return True
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        async with self._get_vip_lock(member.id, member.guild.id):
            await self._cleanup_absent_vip_owner(member.guild, member.id, "on_member_remove")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        async with self._get_vip_lock(member.id, member.guild.id):
            data = await self._get_vip_doc(member.guild, member.id)
            if not data or not self._vip_doc_belongs_to_guild(member.guild, data):
                return
            await self._update_vip_role_with_snapshot(
                member.id,
                {"$set": {"last_seen_at": datetime.now(timezone.utc), "missing_member": False}},
                "on_member_join:last_seen",
                guild_id=member.guild.id,
            )

            recovered = []
            rid = data.get("role_id")
            hid = data.get("highlight_id")

            if rid and not self._is_vip_eligible(member):
                role = None
                try:
                    role = member.guild.get_role(int(rid))
                except (TypeError, ValueError):
                    role = None
                if data.get("status") != "inactive" or data.get("entitlement_active") is not False:
                    await self._deactivate_personal_vip_role(
                        member,
                        role,
                        "vip_expired_or_missing",
                        "on_member_join",
                    )
            elif rid:
                role = member.guild.get_role(int(rid))
                if not role:
                    await self._mark_vip_needs_review(
                        member.id,
                        "role_not_found",
                        "on_member_join",
                        member.guild,
                        missing_role=True,
                        old_doc=data,
                    )
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason="Auto-recuperacao VIP ao entrar")
                        recovered.append(role.mention)
                        await self._log_role_recovery(member, role, "on_member_join:restore_role")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            if hid:
                role = member.guild.get_role(int(hid))
                if not self.is_monarch(member):
                    await self._deactivate_monarch_highlight_role(
                        member,
                        role,
                        "monarch_expired_or_missing",
                        "on_member_join",
                    )
                elif not role:
                    await self._mark_highlight_needs_review(
                        member,
                        "highlight_role_not_found",
                        "on_member_join",
                        old_doc=data,
                    )
                elif role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason="Auto-recuperacao destaque ao entrar")
                        recovered.append(role.mention)
                        await self._log_role_recovery(member, role, "on_member_join:restore_highlight")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            if recovered:
                await self.enviar_log(
                    member.guild,
                    "VIP Recuperado",
                    [("User", member.mention), ("Cargos restaurados", ", ".join(recovered))],
                    discord.Color.green(),
                )

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        await self._audit_manual_vip_role_change(before, after)
        if after.id == BOT_OWNER_ID:
            return
        before_role_ids = {role.id for role in before.roles}
        after_role_ids = {role.id for role in after.roles}
        changed_role_ids = before_role_ids.symmetric_difference(after_role_ids)
        if not changed_role_ids:
            return
        removed_role_ids = before_role_ids - after_role_ids
        if any(
            self._consume_manual_vip_member_removal(after.guild.id, after.id, role_id)
            for role_id in removed_role_ids
        ):
            return

        async with self._get_vip_lock(after.id, after.guild.id):
            data = await self._get_vip_doc(after.guild, after.id)
            if not data or not self._vip_doc_belongs_to_guild(after.guild, data):
                return

            restored = []
            rid = data.get("role_id")
            hid = data.get("highlight_id")
            linked_role_ids = {
                role_id for role_id in (_to_int_or_none(rid), _to_int_or_none(hid)) if role_id is not None
            }
            relevant_role_ids = set(VIP_CONFIG) | linked_role_ids
            if not (changed_role_ids & relevant_role_ids):
                return

            if rid and not self._is_vip_eligible(after):
                role = None
                try:
                    role = after.guild.get_role(int(rid))
                except (TypeError, ValueError):
                    role = None
                if data.get("status") != "inactive" or data.get("entitlement_active") is not False:
                    await self._deactivate_personal_vip_role(
                        after,
                        role,
                        "vip_expired_or_missing",
                        "on_member_update",
                    )
            elif rid:
                role = after.guild.get_role(int(rid))
                if not role:
                    await self._mark_vip_needs_review(
                        after.id,
                        "role_not_found",
                        "on_member_update",
                        after.guild,
                        missing_role=True,
                        old_doc=data,
                    )
                if role and role not in after.roles and self._is_vip_eligible(after):
                    try:
                        await after.add_roles(role, reason="Auto-recuperacao VIP")
                        restored.append(role.mention)
                        await self._log_role_recovery(after, role, "on_member_update:restore_role")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            if hid:
                role = after.guild.get_role(int(hid))
                if not self.is_monarch(after):
                    await self._deactivate_monarch_highlight_role(
                        after,
                        role,
                        "monarch_expired_or_missing",
                        "on_member_update",
                    )
                elif not role:
                    await self._mark_highlight_needs_review(
                        after,
                        "highlight_role_not_found",
                        "on_member_update",
                        old_doc=data,
                    )
                elif role and role not in after.roles:
                    try:
                        await after.add_roles(role, reason="Auto-recuperacao destaque")
                        restored.append(role.mention)
                        await self._log_role_recovery(after, role, "on_member_update:restore_highlight")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            if restored:
                await self.enviar_log(
                    after.guild,
                    "VIP Auto-Recuperado",
                    [("User", after.mention), ("Cargos restaurados", ", ".join(restored))],
                    discord.Color.green(),
                )



    @app_commands.command(name="vip", description="Gerencia seus cargos VIP comum e destaque.")
    @app_commands.describe(
        cor_primaria="Cor primária em HEX (ex: #FFAA00)",
        cor_secundaria="Cor secundária em HEX para gradiente (opcional)",
    )
    async def vip(self, it, cor_primaria: str = None, cor_secundaria: str = None):
        from .commands.vip_command import execute

        await execute(self, it, cor_primaria, cor_secundaria)

    @app_commands.command(name="vincular_vip", description="Admin: Vincula cargo VIP.")
    @check_owner_or_perm(manage_roles=True)
    async def vincular_vip(self, it, usuario: discord.Member, cargo: discord.Role):
        if not await ensure_guild_interaction(it, "o comando /vincular_vip"):
            return

        from .commands.vincular_vip_command import execute

        await execute(self, it, usuario, cargo)

    @app_commands.command(name="temprole", description="Define tempo de cargo temporario (padrao: substituir).")
    @app_commands.describe(
        usuario="Usuario que recebera o cargo temporario",
        cargo="Cargo temporario",
        tempo="Duracao (ex: 1d, 2h, 30m, 10s)",
        somar="Se true, soma no tempo atual em vez de substituir"
    )
    @check_owner_or_perm(manage_roles=True)
    async def temprole(
        self,
        it: discord.Interaction,
        usuario: discord.Member,
        cargo: discord.Role,
        tempo: str,
        somar: bool = False
    ):
        if not await ensure_guild_interaction(it, "o comando /temprole"):
            return

        from .commands.temprole_command import execute

        await execute(self, it, usuario, cargo, tempo, somar)

    @cargo_temporario.command(name="conceder", description="Concede um cargo por tempo determinado.")
    @app_commands.describe(tempo="Duração: 1d, 2h, 30m ou 10s", somar="Somar ao prazo atual")
    @check_owner_or_perm(manage_roles=True)
    async def cargo_temporario_conceder(
        self, it: discord.Interaction, usuario: discord.Member, cargo: discord.Role,
        tempo: str, somar: bool = False,
    ):
        if not await ensure_guild_interaction(it, "o comando /cargo_temporario conceder"):
            return
        from .commands.temprole_command import execute
        await execute(self, it, usuario, cargo, tempo, somar)

    @app_commands.command(name="temprole_remover", description="Abre painel para reduzir/remover tempo de um temprole.")
    @check_owner_or_perm(manage_roles=True)
    async def temprole_remover(self, it: discord.Interaction, usuario: discord.Member, cargo: discord.Role):
        if not await ensure_guild_interaction(it, "o comando /temprole_remover"):
            return

        from .commands.temprole_remover_command import execute

        await execute(self, it, usuario, cargo)

    @cargo_temporario.command(name="ajustar", description="Abre o painel para reduzir o prazo ou retirar o cargo.")
    @check_owner_or_perm(manage_roles=True)
    async def cargo_temporario_ajustar(self, it: discord.Interaction, usuario: discord.Member, cargo: discord.Role):
        if not await ensure_guild_interaction(it, "o comando /cargo_temporario ajustar"):
            return
        from .commands.temprole_remover_command import execute
        await execute(self, it, usuario, cargo)

    @app_commands.command(name="vervips", description="Lista todos os membros com cargos temporários ativos.")
    @check_owner_or_perm(administrator=True)
    @app_commands.choices(
        origem=[
            app_commands.Choice(name="Todos", value="todos"),
            app_commands.Choice(name="Adicionado por /temprole", value="temprole"),
            app_commands.Choice(name="Adicionado pela loja Kaguya", value="loja"),
            app_commands.Choice(name="Legado/sem origem", value="legado"),
        ]
    )
    async def vervips(self, it: discord.Interaction, origem: app_commands.Choice[str] = None):
        if not await ensure_guild_interaction(it, "o comando /vervips"):
            return

        from .commands.vervips_command import execute

        await execute(self, it, origem.value if origem else "todos")

    @cargo_temporario.command(name="consultar", description="Lista cargos temporários ativos e seus prazos.")
    @check_owner_or_perm(administrator=True)
    @app_commands.choices(
        origem=[
            app_commands.Choice(name="Todos", value="todos"),
            app_commands.Choice(name="Concedido pela staff", value="temprole"),
            app_commands.Choice(name="Loja Kaguya", value="loja"),
            app_commands.Choice(name="Legado/sem origem", value="legado"),
        ]
    )
    async def cargo_temporario_consultar(self, it: discord.Interaction, origem: app_commands.Choice[str] = None):
        if not await ensure_guild_interaction(it, "o comando /cargo_temporario consultar"):
            return
        from .commands.vervips_command import execute
        await execute(self, it, origem.value if origem else "todos")

    @app_commands.command(name="fix_database", description="⚠️ Admin: Corrige e unifica tempos duplicados no banco.")
    @check_owner_or_perm(administrator=True)
    async def fix_database(self, it: discord.Interaction):
        if not await ensure_guild_interaction(it, "o comando /fix_database"):
            return

        from .commands.fix_database_command import execute

        await execute(self, it)

    @app_commands.command(name="admin_vip", description="Lista VIPs.")
    @check_owner_or_perm(administrator=True)
    async def admin_vip(self, it):
        if not await ensure_guild_interaction(it, "o comando /admin_vip"):
            return

        from .commands.admin_vip_command import execute

        await execute(self, it)

    @app_commands.command(name="organizar_vips", description="Reposiciona cargos VIP comuns e destaques Monarch.")
    @app_commands.describe(
        incluir_nao_vinculados="Tambem classifica cargos nas faixas VIP sem vinculo no banco: 1 membro=destaque, +1=comum."
    )
    @check_owner_or_perm(administrator=True)
    async def organizar_vips(self, it: discord.Interaction, incluir_nao_vinculados: bool = True):
        if not await ensure_guild_interaction(it, "o comando /organizar_vips"):
            return

        from .commands.organizar_vips_command import execute

        await execute(self, it, incluir_nao_vinculados)

    @tasks.loop(seconds=60)
    async def check_temproles(self):
        now = time.time()
        expired = await asyncio.to_thread(lambda: list(temp_col.find({"end_time": {"$lte": now}})))
        for i in expired:
            try:
                g = self.bot.get_guild(int(i.get("guild_id")))
                if not g:
                    log.warning("temprole_expiry_guild_unavailable record_id=%s", i.get("_id"))
                    continue
                r = g.get_role(int(i.get("role_id")))
                if r:
                    m = g.get_member(int(i.get("user_id")))
                    if m is None:
                        try:
                            m = await g.fetch_member(int(i.get("user_id")))
                        except discord.NotFound:
                            m = None
                        except (discord.Forbidden, discord.HTTPException) as e:
                            log.warning("temprole_expiry_member_lookup_failed record_id=%s error=%s", i.get("_id"), e)
                            continue
                    if m and r in m.roles:
                        try:
                            await m.remove_roles(r, reason="Temprole expirado")
                        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as e:
                            log.warning("temprole_expiry_removal_failed record_id=%s error=%s", i.get("_id"), e)
                            continue
                await asyncio.to_thread(temp_col.delete_one, {"_id": i["_id"]})
            except (TypeError, ValueError, KeyError) as e:
                log.warning("temprole_expiry_invalid_record record_id=%s error=%s", i.get("_id"), e)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not is_db_online():
            return
        await self._hydrate_inactivity_owner_cache(message.guild, message.author.id)
        key = (message.guild.id, message.author.id)
        document_id = self._common_vip_owners.get(key)
        highlight_document_id = self._monarch_highlight_owners.get(key)
        if document_id is None and highlight_document_id is None:
            return
        async with self._get_vip_lock(message.author.id, message.guild.id):
            now = datetime.now(timezone.utc)
            if document_id is not None:
                last_write = self._common_vip_activity_written.get(key)
                if not last_write or (now - last_write).total_seconds() >= COMMON_VIP_ACTIVITY_WRITE_INTERVAL_SECONDS:
                    result = await asyncio.to_thread(
                        vip_col.update_one,
                        {"_id": document_id, "role_source": {"$in": list(COMMON_VIP_SOURCES)}, "role_id": {"$exists": True}},
                        {"$set": {"last_activity_at": now}},
                    )
                    if result and result.matched_count:
                        self._common_vip_activity_written[key] = now
            if highlight_document_id is not None:
                last_write = self._monarch_highlight_activity_written.get(key)
                if not last_write or (now - last_write).total_seconds() >= COMMON_VIP_ACTIVITY_WRITE_INTERVAL_SECONDS:
                    result = await asyncio.to_thread(
                        vip_col.update_one,
                        {"_id": highlight_document_id, "highlight_id": {"$exists": True}},
                        {"$set": {"highlight_last_activity_at": now}},
                    )
                    if result and result.matched_count:
                        self._monarch_highlight_activity_written[key] = now

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or not after.channel or after.channel == member.guild.afk_channel or not is_db_online():
            return
        await self._hydrate_inactivity_owner_cache(member.guild, member.id)
        key = (member.guild.id, member.id)
        document_id = self._common_vip_owners.get(key)
        highlight_document_id = self._monarch_highlight_owners.get(key)
        if document_id is None and highlight_document_id is None:
            return
        async with self._get_vip_lock(member.id, member.guild.id):
            now = datetime.now(timezone.utc)
            if document_id is not None:
                doc = await asyncio.to_thread(vip_col.find_one, {"_id": document_id})
                if doc and doc.get("role_source") in COMMON_VIP_SOURCES and doc.get("role_id") and doc.get("status") != "inactive":
                    await self._record_common_vip_voice_activity(member.guild, member, doc, now, after.channel)
            if highlight_document_id is not None:
                doc = await asyncio.to_thread(vip_col.find_one, {"_id": highlight_document_id})
                if doc and doc.get("highlight_id"):
                    await self._record_monarch_highlight_voice_activity(member.guild, member, doc, now, after.channel)

    async def _hydrate_inactivity_owner_cache(self, guild: discord.Guild, user_id: int):
        key = (guild.id, user_id)
        if ((key in self._common_vip_owners or self._common_vip_cache_loaded)
                and (key in self._monarch_highlight_owners or self._monarch_highlight_cache_loaded)):
            return
        doc = await self._get_vip_doc(guild, user_id)
        if not doc or not is_db_online():
            return
        if not self._common_vip_cache_loaded and doc.get("role_source") in COMMON_VIP_SOURCES and doc.get("role_id") and doc.get("status") != "inactive":
            self._common_vip_owners[key] = doc["_id"]
        if not self._monarch_highlight_cache_loaded and doc.get("highlight_id"):
            self._monarch_highlight_owners[key] = doc["_id"]

    async def _record_common_vip_voice_activity(self, guild: discord.Guild, member: discord.Member, doc: dict, now: datetime, channel=None):
        channel = channel or (member.voice.channel if member.voice else None)
        if not channel or channel == guild.afk_channel:
            return False
        result = await asyncio.to_thread(
            vip_col.update_one,
            {"_id": doc["_id"], "role_source": {"$in": list(COMMON_VIP_SOURCES)}, "role_id": doc["role_id"]},
            {"$set": {"last_activity_at": now}},
        )
        return bool(result and result.matched_count)

    async def _record_monarch_highlight_voice_activity(self, guild: discord.Guild, member: discord.Member, doc: dict, now: datetime, channel=None):
        channel = channel or (member.voice.channel if member.voice else None)
        if not channel or channel == guild.afk_channel:
            return False
        result = await asyncio.to_thread(
            vip_col.update_one,
            {"_id": doc["_id"], "highlight_id": doc["highlight_id"]},
            {"$set": {"highlight_last_activity_at": now}},
        )
        return bool(result and result.matched_count)

    async def _delete_inactive_common_vip(self, guild: discord.Guild, user_id: int, document_id, cutoff: datetime):
        async with self._get_vip_lock(user_id, guild.id):
            if not is_db_online():
                return
            doc = await asyncio.to_thread(vip_col.find_one, {"_id": document_id})
            if not doc or doc.get("role_source") not in COMMON_VIP_SOURCES or not self._vip_doc_belongs_to_guild(guild, doc):
                return
            selected_doc = await self._get_vip_doc(guild, user_id)
            if not is_db_online():
                return
            if not selected_doc or selected_doc["_id"] != document_id:
                return
            if doc.get("status") == "inactive" or (doc.get("status") == "needs_review" and doc.get("cleanup_reason") not in {"inactivity_delete_failed", "member_not_found"}):
                return
            role_id = _to_int_or_none(doc.get("role_id"))
            activity_at = doc.get("last_activity_at")
            if not role_id or not isinstance(activity_at, datetime):
                return
            if activity_at.tzinfo is None:
                activity_at = activity_at.replace(tzinfo=timezone.utc)
            if activity_at > cutoff:
                if doc.get("cleanup_reason") == "inactivity_delete_failed":
                    await self._update_vip_role_with_snapshot(
                        user_id,
                        {"$set": {"status": "active", "review_required": False},
                         "$unset": {"cleanup_reason": "", "cleanup_checked_at": "", "inactivity_retry_after": ""}},
                        "inactivity:activity_resumed", guild_id=guild.id,
                    )
                return
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    member = None
                except (discord.Forbidden, discord.HTTPException):
                    return
            if member and (member.bot or (member.voice and member.voice.channel and member.voice.channel != guild.afk_channel)):
                if not member.bot:
                    await self._record_common_vip_voice_activity(guild, member, doc, datetime.now(timezone.utc))
                return
            role = guild.get_role(role_id)
            if role and (not self._is_personal_vip_role(role) or role.id == _to_int_or_none(doc.get("highlight_id")) or not bot_can_manage_role(guild, role)):
                log.warning("vip_inactivity_unsafe_role guild_id=%s user_id=%s role_id=%s", guild.id, user_id, role_id)
                return
            conflicting = await asyncio.to_thread(
                vip_col.find_one,
                {"_id": {"$ne": document_id}, "role_id": {"$in": [str(role_id), role_id]}},
            )
            if not is_db_online():
                return
            if conflicting:
                log.warning("vip_inactivity_shared_role guild_id=%s user_id=%s role_id=%s", guild.id, user_id, role_id)
                return
            if doc.get("guild_id") is None:
                scoped = await asyncio.to_thread(
                    vip_col.update_one,
                    {"_id": document_id, "role_id": doc["role_id"], "guild_id": {"$exists": False}},
                    {"$set": {"guild_id": str(guild.id), "user_id": str(user_id)}},
                )
                if not is_db_online() or not scoped or not scoped.matched_count:
                    return
            if role:
                try:
                    await role.delete(reason=f"VIP comum sem atividade do dono por {COMMON_VIP_INACTIVITY_DAYS} dias")
                except discord.NotFound:
                    role = None
                except (discord.Forbidden, discord.HTTPException) as exc:
                    retry_after = datetime.now(timezone.utc) + timedelta(seconds=COMMON_VIP_DELETE_RETRY_SECONDS)
                    await self._update_vip_role_with_snapshot(
                        user_id,
                        {"$set": {"status": "needs_review", "review_required": True,
                                  "cleanup_reason": "inactivity_delete_failed", "cleanup_checked_at": datetime.now(timezone.utc),
                                  "inactivity_retry_after": retry_after}},
                        "inactivity:delete_failed", guild_id=guild.id,
                    )
                    log.warning("vip_inactivity_delete_failed guild_id=%s user_id=%s role_id=%s error=%s", guild.id, user_id, role_id, exc)
                    return
            now = datetime.now(timezone.utc)
            await self._update_vip_role_with_snapshot(
                user_id,
                {"$set": {"status": "inactive", "entitlement_active": False, "review_required": False,
                          "last_role_id": str(role_id), "disabled_reason": "owner_inactive_21_days",
                          "disabled_at": now, "inactivity_deleted_at": now},
                 "$unset": {"role_id": "", "inactivity_retry_after": "", "cleanup_reason": "", "cleanup_checked_at": ""}},
                "inactivity:delete_common_role", guild_id=guild.id,
            )
            saved = await asyncio.to_thread(vip_col.find_one, {"_id": document_id})
            if not saved or saved.get("status") != "inactive" or saved.get("role_id") is not None:
                log.error("vip_inactivity_state_not_saved guild_id=%s user_id=%s role_id=%s", guild.id, user_id, role_id)
                return
            self._common_vip_owners.pop((guild.id, user_id), None)
            log.info("vip_inactivity_role_deleted guild_id=%s user_id=%s role_id=%s", guild.id, user_id, role_id)
            try:
                await self.enviar_log(
                    guild, "VIP comum excluído por inatividade",
                    [("Dono", member.mention if member else f"<@{user_id}>"), ("Cargo excluído", f"{role.name if role else 'Cargo ausente'} (`{role_id}`)"),
                     ("Última atividade registrada", f"<t:{int(activity_at.timestamp())}:F>")],
                    discord.Color.orange(),
                )
            except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
                log.warning("vip_inactivity_audit_channel_failed guild_id=%s role_id=%s error=%s", guild.id, role_id, exc)

    @tasks.loop(minutes=10)
    async def check_inactive_common_vips(self):
        try:
            await self._check_inactive_common_vips_once()
        except Exception:
            log.exception("check_inactive_common_vips_iteration_failed")

    async def _check_inactive_common_vips_once(self):
        if not is_db_online():
            return
        docs = await asyncio.to_thread(lambda: list(vip_col.find({"role_source": {"$in": list(COMMON_VIP_SOURCES)}, "role_id": {"$exists": True}})))
        if not is_db_online():
            return
        owners = {}
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=COMMON_VIP_INACTIVITY_DAYS)
        for doc in docs:
            uid = _to_int_or_none(vip_document_user_id(doc))
            if uid is None or doc.get("status") == "inactive":
                continue
            for guild in self.bot.guilds:
                if not self._vip_doc_belongs_to_guild(guild, doc):
                    continue
                owners[(guild.id, uid)] = doc["_id"]
                activity_at = doc.get("last_activity_at")
                observed_at = doc.get("inactivity_observed_at")
                if isinstance(observed_at, datetime) and observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=timezone.utc)
                if not isinstance(activity_at, datetime) or not isinstance(observed_at, datetime) or observed_at < now - timedelta(minutes=30):
                    # Historical activity and activity during bot/database outages are unknown.
                    await asyncio.to_thread(
                        vip_col.update_one,
                        {"_id": doc["_id"], "role_id": doc["role_id"]},
                        {"$set": {"last_activity_at": now, "inactivity_observed_at": now}},
                    )
                    continue
                await asyncio.to_thread(
                    vip_col.update_one,
                    {"_id": doc["_id"], "role_id": doc["role_id"]},
                    {"$set": {"inactivity_observed_at": now}},
                )
                if not is_db_online():
                    return
                if activity_at.tzinfo is None:
                    activity_at = activity_at.replace(tzinfo=timezone.utc)
                member = guild.get_member(uid)
                if member and not member.bot and await self._record_common_vip_voice_activity(guild, member, doc, now):
                    continue
                retry_after = doc.get("inactivity_retry_after")
                if isinstance(retry_after, datetime):
                    if retry_after.tzinfo is None:
                        retry_after = retry_after.replace(tzinfo=timezone.utc)
                    if retry_after > now:
                        continue
                if activity_at <= cutoff:
                    await self._delete_inactive_common_vip(guild, uid, doc["_id"], cutoff)
        self._common_vip_owners = owners
        self._common_vip_cache_loaded = True
        self._common_vip_activity_written = {key: value for key, value in self._common_vip_activity_written.items() if key in owners}

    async def _delete_inactive_monarch_highlight(self, guild: discord.Guild, user_id: int, document_id, cutoff: datetime):
        async with self._get_vip_lock(user_id, guild.id):
            if not is_db_online():
                return
            doc = await asyncio.to_thread(vip_col.find_one, {"_id": document_id})
            if not doc or not doc.get("highlight_id") or not self._vip_doc_belongs_to_guild(guild, doc):
                return
            selected_doc = await self._get_vip_doc(guild, user_id)
            if not is_db_online() or not selected_doc or selected_doc["_id"] != document_id:
                return
            activity_at = doc.get("highlight_last_activity_at")
            if not isinstance(activity_at, datetime):
                return
            if activity_at.tzinfo is None:
                activity_at = activity_at.replace(tzinfo=timezone.utc)
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    if activity_at <= cutoff:
                        absent_owner = SimpleNamespace(id=user_id, guild=guild, mention=f"<@{user_id}>")
                        await self._remove_monarch_highlight(absent_owner, doc, "owner_absent_28_days", "highlight_inactivity")
                    return
                except (discord.Forbidden, discord.HTTPException):
                    return
            if member.bot:
                return
            if not self.is_monarch(member):
                await self._remove_monarch_highlight(member, doc, "monarch_expired_or_missing", "highlight_reconciler")
                return
            if member.voice and member.voice.channel and member.voice.channel != guild.afk_channel:
                await self._record_monarch_highlight_voice_activity(guild, member, doc, datetime.now(timezone.utc))
                return
            if activity_at > cutoff:
                if doc.get("highlight_cleanup_reason") == "highlight_delete_failed":
                    await self._update_vip_role_with_snapshot(
                        user_id,
                        {"$set": {"highlight_review_required": False},
                         "$unset": {"highlight_cleanup_reason": "", "highlight_cleanup_source": "",
                                    "highlight_cleanup_checked_at": "", "highlight_delete_reason": "", "highlight_retry_after": ""}},
                        "highlight_inactivity:activity_resumed", guild_id=guild.id,
                    )
                return
            await self._remove_monarch_highlight(member, doc, "owner_inactive_28_days", "highlight_inactivity")

    @tasks.loop(minutes=10)
    async def check_inactive_monarch_highlights(self):
        try:
            await self._check_inactive_monarch_highlights_once()
        except Exception:
            log.exception("check_inactive_monarch_highlights_iteration_failed")

    async def _check_inactive_monarch_highlights_once(self):
        if not is_db_online():
            return
        docs = await asyncio.to_thread(lambda: list(vip_col.find({"highlight_id": {"$exists": True}})))
        if not is_db_online():
            return
        owners = {}
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=MONARCH_HIGHLIGHT_INACTIVITY_DAYS)
        for doc in docs:
            uid = _to_int_or_none(vip_document_user_id(doc))
            if uid is None or not doc.get("highlight_id"):
                continue
            for guild in self.bot.guilds:
                if not self._vip_doc_belongs_to_guild(guild, doc):
                    continue
                owners[(guild.id, uid)] = doc["_id"]
                activity_at = doc.get("highlight_last_activity_at")
                observed_at = doc.get("highlight_inactivity_observed_at")
                if isinstance(observed_at, datetime) and observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=timezone.utc)
                if not isinstance(activity_at, datetime) or not isinstance(observed_at, datetime) or observed_at < now - timedelta(minutes=30):
                    await asyncio.to_thread(
                        vip_col.update_one,
                        {"_id": doc["_id"], "highlight_id": doc["highlight_id"]},
                        {"$set": {"highlight_last_activity_at": now, "highlight_inactivity_observed_at": now}},
                    )
                    continue
                await asyncio.to_thread(
                    vip_col.update_one,
                    {"_id": doc["_id"], "highlight_id": doc["highlight_id"]},
                    {"$set": {"highlight_inactivity_observed_at": now}},
                )
                if not is_db_online():
                    return
                if activity_at.tzinfo is None:
                    activity_at = activity_at.replace(tzinfo=timezone.utc)
                member = guild.get_member(uid)
                if member and not member.bot and self.is_monarch(member) and await self._record_monarch_highlight_voice_activity(guild, member, doc, now):
                    continue
                retry_after = doc.get("highlight_retry_after")
                if isinstance(retry_after, datetime):
                    if retry_after.tzinfo is None:
                        retry_after = retry_after.replace(tzinfo=timezone.utc)
                    if retry_after > now:
                        continue
                if activity_at <= cutoff or (member and not self.is_monarch(member)) or doc.get("highlight_cleanup_reason") == "highlight_delete_failed":
                    await self._delete_inactive_monarch_highlight(guild, uid, doc["_id"], cutoff)
        self._monarch_highlight_owners = owners
        self._monarch_highlight_cache_loaded = True
        self._monarch_highlight_activity_written = {
            key: value for key, value in self._monarch_highlight_activity_written.items() if key in owners
        }

    @tasks.loop(minutes=10)
    async def reconcile_absent_vips(self):
        records = await asyncio.to_thread(lambda: list(vip_col.find({})))
        if not records:
            return

        checked_absent = 0
        for guild in self.bot.guilds:
            member_ids = {m.id for m in guild.members}
            for doc in records:
                if doc.get("status") == "inactive" or self._already_reviewing_absent_member(doc):
                    continue
                if not self._vip_doc_belongs_to_guild(guild, doc):
                    continue
                uid_raw = vip_document_user_id(doc)
                try:
                    uid = int(uid_raw)
                except (TypeError, ValueError):
                    continue
                if uid in member_ids:
                    continue
                if checked_absent >= RECONCILE_ABSENT_VIP_LIMIT_PER_RUN:
                    log.info(
                        "Reconciliacao VIP pausada apos %s verificacoes REST nesta rodada.",
                        checked_absent,
                    )
                    return
                async with self._get_vip_lock(uid, guild.id):
                    await self._cleanup_absent_vip_owner(guild, uid, "reconciler")
                checked_absent += 1
                await asyncio.sleep(RECONCILE_ABSENT_VIP_DELAY_SECONDS)

    @check_temproles.before_loop
    async def before_check(self): await self.bot.wait_until_ready()

    @reconcile_absent_vips.before_loop
    async def before_reconcile(self): await self.bot.wait_until_ready()

    @check_inactive_common_vips.before_loop
    async def before_inactivity_check(self): await self.bot.wait_until_ready()

    @check_inactive_monarch_highlights.before_loop
    async def before_monarch_highlight_check(self): await self.bot.wait_until_ready()

    @check_temproles.error
    async def check_temproles_error(self, error):
        log.exception("check_temproles_failed error=%s", error)

    @reconcile_absent_vips.error
    async def reconcile_absent_vips_error(self, error):
        log.exception("reconcile_absent_vips_failed error=%s", error)

    @check_inactive_common_vips.error
    async def check_inactive_common_vips_error(self, error):
        log.exception("check_inactive_common_vips_failed error=%s", error)

    @check_inactive_monarch_highlights.error
    async def check_inactive_monarch_highlights_error(self, error):
        log.exception("check_inactive_monarch_highlights_failed error=%s", error)

async def setup(bot):
    await bot.add_cog(VipSystem(bot))
