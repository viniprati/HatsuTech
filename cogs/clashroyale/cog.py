from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import ResilientCollection
from utils import check_owner_or_perm

from .client import ClashRoyaleClient
from .commands import account as account_commands
from .commands import admin as admin_commands
from .commands import alerts as alert_commands
from .commands import cards as card_commands
from .commands import clans as clan_commands
from .commands import events as event_commands
from .commands import player as player_commands
from .commands import rankings as ranking_commands
from .commands import summary as summary_commands
from .commands.alerts import IMPORTANT_CHESTS
from .commands.common import CR_COLOR, card_line, cr_embed, fmt_int, fmt_tag, truncate

log = logging.getLogger(__name__)


class ClashRoyale(commands.GroupCog, name="royale", description="Comandos de Clash Royale."):
    conta = app_commands.Group(name="conta", description="Vinculo e perfil do Clash Royale.")
    jogador = app_commands.Group(name="jogador", description="Consultas de jogador.")
    clan = app_commands.Group(name="clan", description="Consultas de clas.")
    ranking = app_commands.Group(name="ranking", description="Rankings globais e do servidor.")
    cartas = app_commands.Group(name="cartas", description="Cartas, decks e meta.")
    eventos = app_commands.Group(name="eventos", description="Eventos e torneios.")
    admin = app_commands.Group(name="admin", description="Administracao da integracao Clash Royale.")
    alerta = app_commands.Group(name="alerta", description="Alertas pessoais e de cla.")
    resumo = app_commands.Group(name="resumo", description="Resumos periodicos.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = ClashRoyaleClient()
        self.accounts_col = ResilientCollection("clash_royale_accounts")
        self.settings_col = ResilientCollection("clash_royale_settings")
        self.logs_col = ResilientCollection("clash_royale_logs")
        if not self.royale_alert_loop.is_running():
            self.royale_alert_loop.start()

    async def cog_unload(self):
        if self.royale_alert_loop.is_running():
            self.royale_alert_loop.cancel()
        await self.api.close()

    async def log_event(self, guild_id: int | str | None, event: str, detail: str):
        await asyncio.to_thread(
            self.logs_col.insert_one,
            {
                "guild_id": str(guild_id) if guild_id else None,
                "event": event,
                "detail": truncate(detail, 500),
                "created_at": datetime.now(timezone.utc),
            },
        )

    async def get_account(self, user_id: int | str):
        return await asyncio.to_thread(self.accounts_col.find_one, {"_id": str(user_id)})

    async def get_linked_accounts(self, guild_id: int | str | None) -> list[dict]:
        return await asyncio.to_thread(
            lambda: list(
                self.accounts_col.find({"guild_id": str(guild_id)})
                .sort("updated_at", -1)
                .limit(500)
            )
        )

    async def get_settings(self, guild_id: int | str | None) -> dict:
        return await asyncio.to_thread(self.settings_col.find_one, {"_id": str(guild_id)}) or {}

    async def get_main_clan_tag(self, guild_id: int | str | None) -> str | None:
        settings = await self.get_settings(guild_id)
        return settings.get("main_clan_tag")

    async def resolve_player_tag(
        self,
        interaction: discord.Interaction,
        usuario: discord.abc.User | None = None,
        tag: str | None = None,
    ) -> str:
        if tag:
            return self.api.normalize_tag(tag)

        target = usuario or interaction.user
        account = await self.get_account(target.id)
        if not account or not account.get("player_tag"):
            if target.id == interaction.user.id:
                raise ValueError("Voce ainda nao vinculou sua conta. Use `/royale conta vincular`.")
            raise ValueError("Esse usuario ainda nao vinculou uma conta Clash Royale.")
        return self.api.normalize_tag(account["player_tag"])

    async def save_profile_cache(self, player: dict, user: discord.abc.User):
        await self.save_profile_cache_by_id(player, str(user.id), None)

    async def save_profile_cache_by_id(self, player: dict, user_id: str, guild_id: int | str | None):
        update = {
            "player_tag": player.get("tag"),
            "player_name": player.get("name"),
            "last_profile": player,
            "updated_at": datetime.now(timezone.utc),
        }
        if guild_id is not None:
            update["guild_id"] = str(guild_id)
        await asyncio.to_thread(self.accounts_col.update_one, {"_id": str(user_id)}, {"$set": update})

    async def resolve_location_id(self, value: str | int) -> str | int:
        raw = str(value or "global").strip()
        if raw.lower() in {"global", "mundial", "mundo"}:
            return "global"
        if raw.isdigit():
            return int(raw)
        locations = (await self.api.get_locations()).get("items") or []
        lowered = raw.lower()
        exact = next((loc for loc in locations if str(loc.get("name", "")).lower() == lowered), None)
        if exact:
            return exact["id"]
        partial = next((loc for loc in locations if lowered in str(loc.get("name", "")).lower()), None)
        if partial:
            return partial["id"]
        raise ValueError("Localizacao nao encontrada. Tente `Brazil`, `global` ou o ID da localizacao.")

    @staticmethod
    def find_card(cards: list[dict], name: str) -> dict | None:
        lowered = str(name or "").lower().strip()
        if not lowered:
            return None
        exact = next((card for card in cards if str(card.get("name", "")).lower() == lowered), None)
        if exact:
            return exact
        return next((card for card in cards if lowered in str(card.get("name", "")).lower()), None)

    def build_player_embed(self, player: dict) -> discord.Embed:
        clan = player.get("clan") or {}
        arena = player.get("arena") or {}
        wins = int(player.get("wins", 0) or 0)
        losses = int(player.get("losses", 0) or 0)
        total = wins + losses
        winrate = (wins / total * 100) if total else 0
        embed = cr_embed(f"{player.get('name', 'Jogador')} {player.get('tag', '')}")
        embed.add_field(name="Trofeus", value=fmt_int(player.get("trophies")), inline=True)
        embed.add_field(name="Max trofeus", value=fmt_int(player.get("bestTrophies")), inline=True)
        embed.add_field(name="Nivel", value=fmt_int(player.get("expLevel")), inline=True)
        embed.add_field(name="Arena", value=arena.get("name", "-"), inline=True)
        embed.add_field(name="Cla", value=f"{clan.get('name', 'Sem cla')} {fmt_tag(clan.get('tag')) if clan.get('tag') else ''}", inline=True)
        embed.add_field(name="Vitorias", value=f"{fmt_int(wins)} (`{winrate:.1f}%`)", inline=True)
        embed.add_field(name="Cartas", value=fmt_int(len(player.get("cards") or [])), inline=True)
        embed.add_field(name="Deck atual", value=truncate("\n".join(card_line(c) for c in player.get("currentDeck", [])[:8])), inline=False)
        return embed

    def build_deck_embed(self, player: dict) -> discord.Embed:
        deck = player.get("currentDeck") or []
        avg_elixir = sum(float(card.get("elixirCost") or 0) for card in deck) / len(deck) if deck else 0
        embed = cr_embed(f"Deck atual - {player.get('name', 'Jogador')}")
        embed.description = truncate("\n".join(card_line(card) for card in deck), 3900) or "Deck nao encontrado."
        embed.add_field(name="Custo medio", value=f"`{avg_elixir:.2f}`", inline=True)
        if deck and (deck[0].get("iconUrls") or {}).get("medium"):
            embed.set_thumbnail(url=deck[0]["iconUrls"]["medium"])
        return embed

    @tasks.loop(minutes=30)
    async def royale_alert_loop(self):
        await self._run_chest_alerts()
        await self._run_war_alerts()

    @royale_alert_loop.before_loop
    async def before_royale_alert_loop(self):
        await self.bot.wait_until_ready()

    @royale_alert_loop.error
    async def royale_alert_loop_error(self, error):
        log.exception("royale_alert_loop_failed error=%s", error)

    async def _run_chest_alerts(self):
        docs = await asyncio.to_thread(
            lambda: list(
                self.accounts_col.find({"alerts.chests": True, "player_tag": {"$exists": True}})
                .limit(200)
            )
        )
        for doc in docs:
            user_id = str(doc.get("_id"))
            try:
                data = await self.api.get_player_chests(doc["player_tag"])
                chest = next(
                    (
                        item for item in data.get("items", [])
                        if item.get("name") in IMPORTANT_CHESTS and int(item.get("index", 999) or 999) <= 8
                    ),
                    None,
                )
                if not chest:
                    continue

                alert_key = f"{chest.get('name')}:{chest.get('index')}"
                if doc.get("alerts", {}).get("last_chest_key") == alert_key:
                    continue

                user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
                embed = cr_embed(
                    "Bau importante chegando",
                    f"Seu **{chest.get('name')}** esta a `+{chest.get('index')}` batalhas.",
                )
                await user.send(embed=embed)
                await asyncio.to_thread(
                    self.accounts_col.update_one,
                    {"_id": user_id},
                    {"$set": {"alerts.last_chest_key": alert_key, "alerts.last_chest_alert_at": datetime.now(timezone.utc)}},
                )
                await asyncio.sleep(1)
            except Exception as exc:
                await self.log_event(doc.get("guild_id"), "chest_alert_failed", f"{user_id}: {exc}")

    async def _run_war_alerts(self):
        settings_docs = await asyncio.to_thread(
            lambda: list(
                self.settings_col.find({
                    "alerts.war": True,
                    "main_clan_tag": {"$exists": True},
                    "alert_channel_id": {"$exists": True},
                }).limit(25)
            )
        )
        for settings in settings_docs:
            try:
                race = await self.api.get_clan_current_river_race(settings["main_clan_tag"])
                clan = race.get("clan") or {}
                key = f"{race.get('state')}:{race.get('sectionIndex')}:{clan.get('fame')}:{clan.get('rank')}"
                if settings.get("alerts", {}).get("last_war_key") == key:
                    continue

                channel = self.bot.get_channel(int(settings["alert_channel_id"]))
                if not channel:
                    continue

                embed = cr_embed("Atualizacao de guerra", f"Cla: **{clan.get('name', settings.get('main_clan_name', 'Principal'))}**")
                embed.add_field(name="Estado", value=str(race.get("state") or "-"), inline=True)
                embed.add_field(name="Fama", value=fmt_int(clan.get("fame")), inline=True)
                embed.add_field(name="Rank", value=fmt_int(clan.get("rank"), "-"), inline=True)
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                await asyncio.to_thread(
                    self.settings_col.update_one,
                    {"_id": settings["_id"]},
                    {"$set": {"alerts.last_war_key": key, "alerts.last_war_alert_at": datetime.now(timezone.utc)}},
                )
                await asyncio.sleep(1)
            except Exception as exc:
                await self.log_event(settings.get("guild_id"), "war_alert_failed", str(exc))


    @conta.command(name="vincular", description="Vincula sua tag do Clash Royale ao Discord.")
    @app_commands.describe(tag="Tag do jogador, com ou sem #.")
    async def conta_vincular(self, interaction: discord.Interaction, tag: str):
        await account_commands.vincular(self, interaction, tag)

    @conta.command(name="desvincular", description="Remove seu vinculo com Clash Royale.")
    async def conta_desvincular(self, interaction: discord.Interaction):
        await account_commands.desvincular(self, interaction)

    @conta.command(name="perfil", description="Mostra perfil por usuario vinculado ou tag.")
    async def conta_perfil(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
        await account_commands.perfil(self, interaction, usuario, tag)

    @conta.command(name="atualizar", description="Atualiza seu perfil vinculado.")
    async def conta_atualizar(self, interaction: discord.Interaction):
        await account_commands.atualizar(self, interaction)

    @conta.command(name="status", description="Mostra status da API Clash Royale.")
    async def conta_status(self, interaction: discord.Interaction):
        await account_commands.status(self, interaction)


    @jogador.command(name="batalhas", description="Mostra as ultimas batalhas.")
    async def jogador_batalhas(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
        await player_commands.batalhas(self, interaction, usuario, tag)

    @jogador.command(name="bau", description="Mostra os proximos baus.")
    async def jogador_bau(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
        await player_commands.bau(self, interaction, usuario, tag)

    @jogador.command(name="deck", description="Mostra o deck atual.")
    async def jogador_deck(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
        await player_commands.deck(self, interaction, usuario, tag)

    @jogador.command(name="cartas", description="Mostra progresso das cartas do jogador.")
    async def jogador_cartas(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
        await player_commands.cartas(self, interaction, usuario, tag)

    @jogador.command(name="comparar", description="Compara dois jogadores por tag.")
    async def jogador_comparar(self, interaction: discord.Interaction, jogador1: str, jogador2: str):
        await player_commands.comparar(self, interaction, jogador1, jogador2)

    @jogador.command(name="historico", description="Resumo das batalhas recentes.")
    async def jogador_historico(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
        await player_commands.historico(self, interaction, usuario, tag)


    @clan.command(name="info", description="Mostra informacoes de um cla.")
    async def clan_info(self, interaction: discord.Interaction, tag_ou_nome: str):
        await clan_commands.info(self, interaction, tag_ou_nome)

    @clan.command(name="membros", description="Lista membros de um cla.")
    async def clan_membros(self, interaction: discord.Interaction, tag: str, limite: int = 25):
        await clan_commands.membros(self, interaction, tag, limite)

    @clan.command(name="buscar", description="Busca clas por nome.")
    async def clan_buscar(self, interaction: discord.Interaction, nome: str):
        await clan_commands.buscar(self, interaction, nome)

    @clan.command(name="guerra", description="Mostra a River Race atual do cla.")
    async def clan_guerra(self, interaction: discord.Interaction, tag: str | None = None):
        await clan_commands.guerra(self, interaction, tag)

    @clan.command(name="guerra_log", description="Mostra historico de River Race.")
    async def clan_guerra_log(self, interaction: discord.Interaction, tag: str | None = None):
        await clan_commands.guerra_log(self, interaction, tag)

    @clan.command(name="comparar", description="Compara dois clas por tag.")
    async def clan_comparar(self, interaction: discord.Interaction, clan1: str, clan2: str):
        await clan_commands.comparar(self, interaction, clan1, clan2)


    @ranking.command(name="jogadores", description="Ranking de jogadores por localizacao.")
    async def ranking_jogadores(self, interaction: discord.Interaction, localizacao: str = "global", limite: int = 10):
        await ranking_commands.jogadores(self, interaction, localizacao, limite)

    @ranking.command(name="clans", description="Ranking de clas por localizacao.")
    async def ranking_clans(self, interaction: discord.Interaction, localizacao: str = "global", limite: int = 10):
        await ranking_commands.clans(self, interaction, localizacao, limite)

    @ranking.command(name="servidor", description="Ranking dos perfis vinculados no servidor.")
    async def ranking_servidor(self, interaction: discord.Interaction):
        await ranking_commands.servidor(self, interaction)

    @ranking.command(name="top_trofeus", description="Top trofeus dos vinculados.")
    async def ranking_top_trofeus(self, interaction: discord.Interaction):
        await ranking_commands.top_trofeus(self, interaction)

    @ranking.command(name="top_vitorias", description="Top vitorias dos vinculados.")
    async def ranking_top_vitorias(self, interaction: discord.Interaction):
        await ranking_commands.top_vitorias(self, interaction)

    @ranking.command(name="top_clans", description="Clas mais comuns entre vinculados.")
    async def ranking_top_clans(self, interaction: discord.Interaction):
        await ranking_commands.top_clans(self, interaction)


    @cartas.command(name="info", description="Mostra informacoes de uma carta.")
    async def cartas_info(self, interaction: discord.Interaction, nome: str):
        await card_commands.info(self, interaction, nome)

    @cartas.command(name="lista", description="Lista cartas do jogo.")
    async def cartas_lista(self, interaction: discord.Interaction, raridade: str | None = None):
        await card_commands.lista(self, interaction, raridade)

    @cartas.command(name="deck_analisar", description="Analisa o deck atual.")
    async def cartas_deck_analisar(self, interaction: discord.Interaction, usuario: discord.Member | None = None, tag: str | None = None):
        await card_commands.deck_analisar(self, interaction, usuario, tag)

    @cartas.command(name="meta_servidor", description="Mostra cartas mais usadas pelos vinculados.")
    async def cartas_meta_servidor(self, interaction: discord.Interaction):
        await card_commands.meta_servidor(self, interaction)


    @eventos.command(name="atuais", description="Mostra eventos atuais.")
    async def eventos_atuais(self, interaction: discord.Interaction):
        await event_commands.atuais(self, interaction)

    @eventos.command(name="desafios", description="Mostra desafios atuais.")
    async def eventos_desafios(self, interaction: discord.Interaction):
        await event_commands.desafios(self, interaction)

    @eventos.command(name="torneio_buscar", description="Busca torneios por nome.")
    async def eventos_torneio_buscar(self, interaction: discord.Interaction, nome: str):
        await event_commands.torneio_buscar(self, interaction, nome)

    @eventos.command(name="torneio", description="Mostra um torneio por tag.")
    async def eventos_torneio(self, interaction: discord.Interaction, tag: str):
        await event_commands.torneio(self, interaction, tag)

    @eventos.command(name="torneios_globais", description="Mostra torneios globais.")
    async def eventos_torneios_globais(self, interaction: discord.Interaction):
        await event_commands.torneios_globais(self, interaction)


    @admin.command(name="config", description="Mostra configuracao da integracao.")
    @check_owner_or_perm(administrator=True)
    async def admin_config(self, interaction: discord.Interaction):
        await admin_commands.config(self, interaction)

    @admin.command(name="clan_principal", description="Define o cla principal do servidor.")
    @check_owner_or_perm(administrator=True)
    async def admin_clan_principal(self, interaction: discord.Interaction, tag: str):
        await admin_commands.clan_principal(self, interaction, tag)

    @admin.command(name="sync", description="Atualiza perfis vinculados.")
    @check_owner_or_perm(administrator=True)
    async def admin_sync(self, interaction: discord.Interaction, limite: int = 50):
        await admin_commands.sync(self, interaction, limite)

    @admin.command(name="vinculos", description="Mostra contas vinculadas.")
    @check_owner_or_perm(administrator=True)
    async def admin_vinculos(self, interaction: discord.Interaction):
        await admin_commands.vinculos(self, interaction)

    @admin.command(name="cache_limpar", description="Limpa cache local da API.")
    @check_owner_or_perm(administrator=True)
    async def admin_cache_limpar(self, interaction: discord.Interaction):
        await admin_commands.cache_limpar(self, interaction)

    @admin.command(name="logs", description="Mostra logs recentes da integracao.")
    @check_owner_or_perm(administrator=True)
    async def admin_logs(self, interaction: discord.Interaction):
        await admin_commands.logs(self, interaction)


    @alerta.command(name="bau", description="Ativa ou desativa alerta de baus importantes.")
    async def alerta_bau(self, interaction: discord.Interaction, ativo: bool = True):
        await alert_commands.bau(self, interaction, ativo)

    @alerta.command(name="guerra", description="Configura alerta de guerra em um canal.")
    @check_owner_or_perm(manage_guild=True)
    async def alerta_guerra(self, interaction: discord.Interaction, canal: discord.TextChannel | None = None, ativo: bool = True):
        await alert_commands.guerra(self, interaction, canal, ativo)


    @resumo.command(name="semanal", description="Resumo semanal dos vinculados.")
    async def resumo_semanal(self, interaction: discord.Interaction):
        await summary_commands.semanal(self, interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(ClashRoyale(bot))
