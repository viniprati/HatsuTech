"""Own-server profile cards; all settings are scoped to the interaction author."""
from __future__ import annotations

import asyncio
import io
import logging
import time
from uuid import uuid4

import discord

from utils import is_allowed_guild
from ..profile_service import member_facts

log = logging.getLogger(__name__)
THEMES = {"cafe": "Café", "sakura": "Sakura", "midnight": "Meia-noite"}


class FeaturedSelect(discord.ui.Select):
    def __init__(self, cog, owner_id: int, guild_id: int, achievements: list[dict]):
        self.cog, self.owner_id, self.guild_id = cog, owner_id, guild_id
        unlocked = [badge for badge in achievements if badge["unlocked"]]
        options = [discord.SelectOption(label=badge["name"], value=badge["id"]) for badge in unlocked]
        self.allowed_values = {option.value for option in options}
        super().__init__(
            placeholder="Escolha até três insígnias para destacar",
            min_values=0, max_values=min(3, len(options)), options=options,
        )

    async def callback(self, it: discord.Interaction):
        if it.user.id != self.owner_id or it.guild_id != self.guild_id:
            return await it.response.send_message("Este painel pertence a outra pessoa.", ephemeral=True)
        if len(self.values) > 3 or not set(self.values).issubset(self.allowed_values):
            return await it.response.send_message("Selecione até três insígnias disponíveis.", ephemeral=True)
        await it.response.defer(ephemeral=True)
        saved = await asyncio.to_thread(
            self.cog.profiles.save_settings, self.guild_id, self.owner_id,
            {"featured": list(self.values)},
        )
        await it.edit_original_response(
            content="Destaques salvos. Use `/perfil` para ver o cartão atualizado." if saved else
            "Não consegui salvar seus destaques agora. Tente novamente mais tarde.",
            view=None, allowed_mentions=discord.AllowedMentions.none(),
        )


class ProfileView(discord.ui.View):
    def __init__(self, cog, owner_id: int, guild_id: int, profile: dict):
        super().__init__(timeout=180)
        self.cog, self.owner_id, self.guild_id, self.profile = cog, owner_id, guild_id, profile

    async def interaction_check(self, it: discord.Interaction) -> bool:
        if it.user.id == self.owner_id and it.guild_id == self.guild_id:
            return True
        await it.response.send_message("Use `/perfil` para abrir seu próprio cartão.", ephemeral=True)
        return False

    async def on_error(self, it, error, item):
        log.error("profile_component_failed request_id=%s error_type=%s", it.id, type(error).__name__)
        message = "Não consegui atualizar o perfil agora. Tente novamente mais tarde."
        if it.response.is_done():
            await it.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:
            await it.response.send_message(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label="Ver conquistas", style=discord.ButtonStyle.secondary)
    async def achievements(self, it: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="Conquistas do Café", color=0x55C5BD)
        for badge in self.profile["achievements"]:
            status = "Desbloqueada" if badge["unlocked"] else (
                f"{int(badge['progress'] * 100)}%" if badge["available"] else "Dados indisponíveis"
            )
            embed.add_field(name=f"{badge['name']} · {status}", value=badge["description"], inline=False)
        embed.set_footer(text="A presença conta sete dias distintos de participação; não precisa ser seguida.")
        await it.response.send_message(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label="Destacar insígnias", style=discord.ButtonStyle.secondary)
    async def feature(self, it: discord.Interaction, button: discord.ui.Button):
        if not any(badge["unlocked"] for badge in self.profile["achievements"]):
            return await it.response.send_message("Suas primeiras insígnias aparecerão aqui quando forem desbloqueadas.", ephemeral=True)
        view = discord.ui.View(timeout=120)
        view.add_item(FeaturedSelect(self.cog, self.owner_id, self.guild_id, self.profile["achievements"]))
        await it.response.send_message("Escolha suas insígnias em destaque:", view=view, ephemeral=True,
                                       allowed_mentions=discord.AllowedMentions.none())


async def execute(cog, it: discord.Interaction, *, tema=None, sobre=None, publico=False):
    if not it.guild or not is_allowed_guild(it.guild.id):
        return await it.response.send_message("Use `/perfil` em um servidor autorizado.", ephemeral=True)
    if not isinstance(it.user, discord.Member) or it.user.bot:
        return await it.response.send_message("O perfil está disponível para membros do servidor.", ephemeral=True)
    if sobre is not None and len(sobre) > 100:
        return await it.response.send_message("Escreva até 100 caracteres no campo sobre.", ephemeral=True)
    theme = getattr(tema, "value", tema)
    if theme is not None and theme not in THEMES:
        return await it.response.send_message("Escolha um dos temas disponíveis.", ephemeral=True)
    if cog.profile_render_slots.locked():
        return await it.response.send_message("Estou preparando outros cartões. Tente novamente em alguns segundos.", ephemeral=True)

    request_id = uuid4().hex[:12]
    started = time.monotonic()
    async with cog.profile_render_slots:
        await it.response.defer(ephemeral=not publico, thinking=True)
        try:
            facts = member_facts(it.user)
            profile = await asyncio.to_thread(cog.profiles.read_profile, facts, request_id)
            if sobre is not None or theme is not None:
                # Normalize settings using the same rules as profile reads.
                from ..profile_rules import build_profile
                settings = {}
                if sobre is not None:
                    settings["bio"] = sobre
                if theme is not None:
                    settings["theme"] = theme
                normalized = build_profile(facts, profile_doc=settings, data_available=False)
                settings = {key: normalized[key] for key in settings}
                saved = await asyncio.to_thread(cog.profiles.save_settings, it.guild.id, it.user.id, settings)
                if not saved:
                    return await it.edit_original_response(
                        content="Não consegui salvar sua personalização agora. Tente novamente mais tarde.",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                profile.update(settings)
            avatar = None
            try:
                # Asset comes exclusively from Discord, with a bounded requested size.
                avatar = await asyncio.wait_for(
                    it.user.display_avatar.with_size(256).with_static_format("png").read(), timeout=8,
                )
                if len(avatar) > 2_000_000:
                    avatar = None
            except (discord.Forbidden, discord.NotFound, discord.HTTPException, asyncio.TimeoutError):
                log.info("profile_avatar_fallback request_id=%s", request_id)
            from ..profile_renderer import render_profile
            png = await asyncio.to_thread(render_profile, profile, avatar)
            content = None
            if not profile["data_available"]:
                content = "Alguns dados estão indisponíveis agora. Tente novamente mais tarde para atualizar suas estatísticas."
            elif not profile.get("persistence_available", True):
                content = "Cartão atualizado; não consegui salvar novos desbloqueios agora. Consulte novamente mais tarde."
            await it.edit_original_response(
                content=content, attachments=[discord.File(io.BytesIO(png), filename="perfil-animes-cafe.png")],
                view=ProfileView(cog, it.user.id, it.guild.id, profile),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            log.info("profile_rendered request_id=%s elapsed_ms=%s data_available=%s",
                     request_id, round((time.monotonic() - started) * 1000), profile["data_available"])
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            log.warning("profile_delivery_failed request_id=%s error_type=%s", request_id, type(error).__name__)
            try:
                await it.followup.send("Não consegui enviar o cartão. Verifique se posso anexar arquivos e tente novamente.",
                                       ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
        except Exception as error:
            log.error("profile_failed request_id=%s error_type=%s", request_id, type(error).__name__)
            await it.edit_original_response(content="Não consegui preparar seu perfil agora. Tente novamente mais tarde.",
                                            allowed_mentions=discord.AllowedMentions.none())
