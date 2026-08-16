from __future__ import annotations
from ..cog import *


async def execute_highlight(self, it, cor_primaria: str = None, cor_secundaria: str = None):
    await it.response.defer(ephemeral=True)
    if not await ensure_db_online(it, "a opção Cargo destaque do /vip"):
        return

    if not self.is_monarch(it.user):
        return await it.followup.send("🚫 Exclusivo para Monarch (Cargo Destaque).", ephemeral=True)

    async with self._get_vip_lock(it.user.id, it.guild.id):
        data = await self._get_vip_doc(it.guild, it.user.id)
        hid = data.get("highlight_id") if data else None
        role = it.guild.get_role(int(hid)) if hid else None

        if not role:
            try:
                role = await it.guild.create_role(name=f"✦ {it.user.display_name}", mentionable=False)
                positioned = await self._position_monarch_highlight_role(it.guild, role)
                position_note = None
                if not positioned:
                    position_note = "⚠️ Não consegui posicionar seu destaque na faixa configurada (âncora ausente ou sem permissão)."

                await self._update_vip_role_with_snapshot(
                    it.user.id,
                    {
                        "$set": {
                            "highlight_id": str(role.id),
                            "highlight_active": True,
                            "highlight_review_required": False,
                            "highlight_missing_role": False,
                            "last_seen_at": datetime.now(timezone.utc),
                        },
                        "$unset": {
                            "highlight_cleanup_reason": "",
                            "highlight_cleanup_source": "",
                            "highlight_cleanup_checked_at": "",
                            "highlight_disabled_reason": "",
                            "highlight_disabled_at": "",
                        },
                    },
                    "command:/vip:highlight",
                    actor_id=it.user.id,
                    guild_id=it.guild.id,
                    upsert=True
                )
                await it.followup.send("✨ **Destaque Criado!** Configure abaixo.", ephemeral=True)
                if position_note:
                    await it.followup.send(position_note, ephemeral=True)
            except Exception as e:
                return await it.followup.send(f"❌ Erro ao criar: {e}", ephemeral=True)

        await self._update_vip_role_with_snapshot(
            it.user.id,
            {
                "$set": {
                    "highlight_id": str(role.id),
                    "highlight_active": True,
                    "highlight_review_required": False,
                    "highlight_missing_role": False,
                    "last_seen_at": datetime.now(timezone.utc),
                },
                "$unset": {
                    "highlight_cleanup_reason": "",
                    "highlight_cleanup_source": "",
                    "highlight_cleanup_checked_at": "",
                    "highlight_disabled_reason": "",
                    "highlight_disabled_at": "",
                },
            },
            "command:/vip:highlight:refresh",
            actor_id=it.user.id,
            guild_id=it.guild.id,
            upsert=True
        )

        if role and role not in it.user.roles:
            try:
                await it.user.add_roles(role)
            except (discord.Forbidden, discord.HTTPException):
                pass

        positioned_existing = await self._position_monarch_highlight_role(it.guild, role)
        if not positioned_existing:
            await it.followup.send("⚠️ Não consegui reposicionar seu destaque na faixa configurada (âncora ausente ou sem permissão).", ephemeral=True)

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
                log.error(f"Erro ao editar cores do destaque {role.id}: {e}")
                return await it.followup.send("❌ Não foi possível aplicar as cores agora.", ephemeral=True)

        await it.followup.send(
            embed=discord.Embed(
                title=f"✨ Destaque Solo: {role.name}",
                description="Este cargo não possui membros, apenas visual.",
                color=role.color,
            ),
            view=VipHighlightView(self, role),
            ephemeral=True
        )
