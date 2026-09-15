import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timezone, timedelta
import logging
import traceback

log = logging.getLogger(__name__)

try:
    from database import vip_col, msg_col, voice_col, event_col
except ImportError as e:
    log.error(f"Erro crítico ao carregar banco de dados no módulo engagement: {e}")

try:
    from config import REVIVER_ROLE_ID, REVIVER_PERM_ROLE_ID
except ImportError:
    log.warning("Arquivo config não encontrou variáveis do Reviver. Usando IDs padrão de fallback.")
    REVIVER_ROLE_ID = 0
    REVIVER_PERM_ROLE_ID = 1413646810316279990

from utils import check_owner_or_perm, ensure_db_online, ensure_guild_interaction, has_full_access

FUSO_BRT = timezone(timedelta(hours=-3))
REVIVER_COOLDOWN_MINUTES = 30
JOGAR_ROLE_ID = 1097480994065490000
JOGAR_CHANNEL_ID = 1530739368078213220
JOGAR_COOLDOWN_SECONDS = 60 * 60
APOIADOR_ROLE_ID = 1512225314502086746
SUPPORTER_TAG_CHECK_INTERVAL_HOURS = 6
SUPPORTER_TAG_REMOVAL_DELAY_SECONDS = 0.5
APOIADOR_BENEFITS = [
    "Permissão para enviar **mídias** no chat de conversa;",
    "Permissão para gravar **áudio** no chat de conversa;",
    "Permissão para usar sons externos do **Soundboard**;",
    "Permissão para alterar seu **apelido** no servidor.",
]

def member_has_server_tag(member: discord.Member) -> bool:
    primary_guild = getattr(member, "primary_guild", None)
    return bool(primary_guild and getattr(primary_guild, "id", None) == member.guild.id)

DEFAULT_STAFF_MAP = {
    "1011692684068520016": "👑 **Liderança**",
    "999723105033396235":  "⚙️ **Gear**",
    "999723108887953518":  "🎖️ **Comandante**",
    "999723110808961105":  "💼 **Gerente**",
    "1275960135310774282": "📋 **Sub-Gerente**",
    "1117570040204628028": "🛡️ **Moderador Sênior**",
    "1117569899691253832": "🛡️ **Moderador**",
    "1118911825300435094": "👮 **Moderador Novato**",
    "1333224231479279667": "📰 **Jornalismo**",
    "1275958325665599571": "🎉 **Equipe de Eventos**",
    "1424072450148270100": "📊 **Equipe de Enquetes**",
    "1413646810316279990": "🗣️ **Movimentador de Chat**"
}

HELP_DATA = {
    "geral": {
        "label": "Geral e Rankings",
        "emoji": "<a:Trofeu1:1512192550088212481>",
        "description": "Perfil, conquistas e rankings do servidor.",
        "color": discord.Color.blurple(),
        "commands": [
            ("❔", "ajuda", "Abre esta central interativa de comandos.", "Público"),
            ("👤", "userinfo", "Mostra perfil, conquistas, cargos e dados do membro.", "Público"),
            ("🤖", "verificarbot", "Verifica se um bot possui a flag oficial do Discord.", "Público"),
            ("🎮", "jogar", "Chama pessoas para jogar com cooldown individual.", "Público"),
            ("<a:Trofeu1:1512192550088212481>", "rank", "Ranking de mensagens por período.", "Público"),
            ("🎙️", "voice_rank", "Ranking de tempo em call por período.", "Público"),
            ("🎉", "topevento", "Ranking do evento atual ou anterior.", "Público"),
            ("🎊", "topevento2", "Ranking do evento 2.", "Público"),
        ]
    },
    "economia": {
        "label": "Economia",
        "emoji": "<a:Dinheiro_voador:1512192543117545781>",
        "description": "Moedas, lootboxes, loja, inventário e bônus 2x.",
        "color": discord.Color.gold(),
        "commands": [
            ("<:aguaviva:1512208133177741433>", "eco ajuda", "Explica moedas, ganhos, lootboxes, chances e VIPs.", "Público"),
            ("<:gota:1512208257396248666>", "eco saldo", "Mostra seu saldo e progresso na economia.", "Público"),
            ("<:borboleta:1512208174306824332>", "eco inventario", "Mostra moedas, caixas e VIPs guardados.", "Público"),
            ("<:palmolive:1512208558622638281>", "eco loja", "Abre a loja de lootboxes e VIPs.", "Público"),
            ("<:controle:1512208193760268419>", "eco abrir_comum", "Abre Lootbox Comum do inventário.", "Público"),
            ("<:controle:1512208193760268419>", "eco abrir_premium", "Abre Lootbox Premium do inventário.", "Público"),
            ("<a:Dinheiro_voador:1512192543117545781>", "duplicar", "Ativa ou desativa ganho 2x por tempo limitado.", "Admin"),
        ]
    },
    "vip": {
        "label": "Área VIP",
        "emoji": "<:Vip_Requiem:1512192545172492449>",
        "description": "Painéis e ações para cargos VIP comuns e destaques.",
        "color": discord.Color.purple(),
        "commands": [
            ("<:Vip_Berserk:1351063519684202549>", "vip", "Abre o painel para cargo comum e cargo destaque.", "VIP"),
            ("📢", "notificar", "Envia uma notificação para o cargo do seu VIP.", "VIP"),
        ]
    },
    "guilda": {
        "label": "Sistema de Guildas",
        "emoji": "<:sword:1512194684045496380>",
        "description": "Criação, painel, convites e ranking de guildas.",
        "color": discord.Color.dark_teal(),
        "commands": [
            ("<:sword:1512194684045496380>", "guilda criar", "Cria uma nova guilda.", "Público"),
            ("📋", "guilda painel", "Mostra status e membros da guilda.", "Público"),
            ("✉️", "guilda convidar", "Convida alguém para sua guilda.", "Líder"),
            ("🚪", "guilda sair", "Sai da guilda atual.", "Público"),
            ("🗑️", "guilda deletar", "Exclui a guilda permanentemente.", "Líder"),
            ("✏️", "guilda editar_nome", "Altera o nome da guilda.", "Líder"),
            ("✨", "guilda editar_emoji", "Altera o ícone da guilda.", "Líder"),
            ("<a:Trofeu1:1512192550088212481>", "guilda ranking", "Mostra o top 10 guildas por geral, semanal, mensal, mensagens ou call.", "Público"),
            ("👢", "guilda kick", "Remove um membro da guilda.", "Líder"),
        ]
    },
    "clash": {
        "label": "Clash Royale",
        "emoji": "<:Clash:1529860295630258357>",
        "description": "Perfis, decks, baús, clãs, guerra, rankings e eventos do Clash Royale.",
        "color": discord.Color.blue(),
        "commands": [
            (
                "<:Clash:1529860295630258357>",
                "royale conta",
                "`vincular`, `desvincular`, `perfil`, `atualizar` e `status` para gerenciar sua conta Clash vinculada.",
                "Público",
            ),
            (
                "👤",
                "royale jogador",
                "`batalhas`, `bau`, `deck`, `cartas`, `comparar` e `historico` para consultar jogadores por tag ou vínculo.",
                "Público",
            ),
            (
                "🛡️",
                "royale clan",
                "`info`, `membros`, `buscar`, `guerra`, `guerra_log` e `comparar` para acompanhar clãs e River Race.",
                "Público",
            ),
            (
                "🏆",
                "royale ranking",
                "`jogadores`, `clans`, `servidor`, `top_trofeus`, `top_vitorias` e `top_clans`.",
                "Público",
            ),
            (
                "🃏",
                "royale cartas",
                "`info`, `lista`, `deck_analisar` e `meta_servidor` para cartas, decks e leitura do meta.",
                "Público",
            ),
            (
                "📅",
                "royale eventos",
                "`atuais`, `desafios`, `torneio_buscar`, `torneio` e `torneios_globais`.",
                "Público",
            ),
            (
                "🔔",
                "royale alerta",
                "`bau` para alerta pessoal de baús importantes e `guerra` para alerta de clã em canal.",
                "Público/Staff",
            ),
            (
                "📊",
                "royale resumo",
                "`semanal` mostra um resumo dos perfis Clash vinculados no servidor.",
                "Público",
            ),
            (
                "⚙️",
                "royale admin",
                "`config`, `clan_principal`, `sync`, `vinculos`, `cache_limpar` e `logs` para administrar a integração.",
                "Admin",
            ),
        ]
    },
    "mod": {
        "label": "Staff",
        "emoji": "<a:a6_staff:1512192546732900543>",
        "description": "Ferramentas de moderação e manutenção.",
        "color": discord.Color.orange(),
        "commands": [
            ("📣", "reviver", "Abre o painel para movimentar o chat.", "Staff"),
            ("🧹", "limpar", "Limpa mensagens do canal.", "Staff"),
            ("🔒", "lock", "Tranca o canal atual.", "Staff"),
            ("🔓", "unlock", "Destranca o canal atual.", "Staff"),
            ("➕", "addcargo", "Adiciona um cargo a um usuário.", "Staff"),
            ("🖼️", "cargopng", "Cria um cargo com ícone e adiciona membros.", "Staff"),
            ("🖌️", "seticon", "Altera o ícone de um cargo existente.", "Staff"),
            ("⏳", "temprole", "Define um cargo temporário.", "Staff"),
            ("⌛", "temprole_remover", "Abre painel para reduzir ou remover tempo.", "Staff"),
            ("<:Vip_Requiem:1512192545172492449>", "vervips", "Lista membros com cargos temporários ativos.", "Staff"),
        ]
    },
    "admin": {
        "label": "Administração",
        "emoji": "<:ALRTD_staff_administrador:1512192548033138792>",
        "description": "Configurações sensíveis do bot.",
        "color": discord.Color.red(),
        "commands": [
            ("📊", "admin_stats", "Painel administrativo de ranks e sistema.", "Admin"),
            ("<:Vip_Requiem:1512192545172492449>", "admin_vip", "Lista e audita VIPs pessoais.", "Admin"),
            ("✨", "admin_emoji", "Força a troca do emoji de uma guilda.", "Admin"),
            ("<:sword:1512194684045496380>", "admin_guildas", "Painel administrativo de guildas.", "Admin"),
            ("🗑️", "admin_force_delete", "Força a exclusão de uma guilda.", "Admin"),
            ("🏅", "config_badge", "Configura badges por cargo.", "Admin"),
            ("🚫", "remover_badge", "Remove uma badge configurada.", "Admin"),
            ("<:gota:1512208257396248666>", "eco_admin set_saldo", "Define saldo de uma moeda.", "Admin"),
            ("<:planta:1512208216295997500>", "eco_admin add_saldo", "Adiciona saldo para um usuário.", "Admin"),
            ("📦", "eco_admin restock", "Repõe estoque da loja.", "Admin"),
            ("<a:Trofeu1:1512192550088212481>", "eco_admin leaderboard", "Leaderboard administrativo da economia.", "Admin"),
            ("🧾", "eco_admin transacoes", "Lista compras de VIP realizadas.", "Admin"),
            ("♻️", "admin_reset", "Reset administrativo da economia.", "Admin"),
            ("📢", "anunciar", "Envia atualização por DM para inscritos.", "Admin"),
        ]
    }
}

def build_help_embed(category_key: str | None = None) -> discord.Embed:
    if category_key and category_key in HELP_DATA:
        data = HELP_DATA[category_key]
        embed = discord.Embed(
            title=f"{data['emoji']} {data['label']}",
            description=data["description"],
            color=data["color"],
        )
        for command_emoji, command_name, command_desc, access in data["commands"]:
            embed.add_field(
                name=f"{command_emoji} `/{command_name}`  •  {access}",
                value=command_desc,
                inline=False,
            )
        embed.set_footer(text=f"{len(data['commands'])} comandos nesta categoria")
        return embed

    overview = discord.Embed(
        title="🤖 Central de Ajuda",
        description=(
            "Escolha uma categoria no menu abaixo para ver os comandos disponíveis.\n"
            "Os selos indicam se o comando é público, VIP, de líder, staff ou admin."
        ),
        color=discord.Color.gold(),
    )
    for data in HELP_DATA.values():
        overview.add_field(
            name=f"{data['emoji']} {data['label']}",
            value=f"{data['description']}\n`{len(data['commands'])}` comandos",
            inline=True,
        )
    overview.set_footer(text="Use os comandos com /")
    return overview


class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Início",
                description="Voltar para a visão geral.",
                emoji="🏠",
                value="home",
            )
        ]
        for key, data in HELP_DATA.items():
            options.append(discord.SelectOption(
                label=data["label"],
                description=data["description"],
                emoji=data["emoji"],
                value=key
            ))
        super().__init__(placeholder="Escolha uma categoria...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            categoria = self.values[0]
            embed = build_help_embed(None if categoria == "home" else categoria)
            await interaction.response.edit_message(embed=embed, view=self.view)
        except Exception as e:
            log.error(f"Bug detectado no HelpSelect: {e}")
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ocorreu um erro ao carregar a categoria.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ocorreu um erro ao carregar a categoria.", ephemeral=True)

class HelpView(discord.ui.View):
    def __init__(self, author_id: int | None = None):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.add_item(HelpSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id and interaction.user.id != self.author_id:
            await interaction.response.send_message("Somente quem abriu o painel pode usar este menu.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True





def build_supporter_embed(guild: discord.Guild) -> discord.Embed:
    role = guild.get_role(APOIADOR_ROLE_ID)
    role_text = role.mention if role else f"<@&{APOIADOR_ROLE_ID}>"
    role_color = role.color if role and role.color.value else discord.Color.from_rgb(43, 228, 172)
    benefits = "\n".join(f"- {benefit}" for benefit in APOIADOR_BENEFITS)

    embed = discord.Embed(
        description=(
            "# Resgate o cargo Apoiador\n"
            f"> Use a tag do servidor Café no seu perfil e clique no botão abaixo para receber {role_text}.\n"
            "### Benefícios:\n"
            f"{benefits}"
        ),
        color=role_color,
    )
    return embed


class SupporterClaimView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Resgatar Apoiador",
        style=discord.ButtonStyle.success,
        emoji="<a:Dinheiro_voador:1512192543117545781>",
        custom_id="supporter_claim_button",
    )
    async def claim_supporter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use este botão dentro do servidor.", ephemeral=True)

        role = interaction.guild.get_role(APOIADOR_ROLE_ID)
        if role is None:
            return await interaction.response.send_message("Cargo Apoiador não encontrado. Avise a staff.", ephemeral=True)

        if role in interaction.user.roles:
            return await interaction.response.send_message("Você já possui o cargo Apoiador.", ephemeral=True)

        if not member_has_server_tag(interaction.user):
            return await interaction.response.send_message(
                "Não encontrei a tag do servidor Café no seu perfil.",
                ephemeral=True,
            )

        me = interaction.guild.me
        if me is None or role.managed or role >= me.top_role:
            return await interaction.response.send_message(
                "Não consigo entregar esse cargo por causa da hierarquia de cargos. Avise a staff.",
                ephemeral=True,
            )

        try:
            await interaction.user.add_roles(role, reason="Resgate de Apoiador com tag do servidor")
        except discord.HTTPException:
            log.exception("Falha ao entregar cargo Apoiador para %s", interaction.user.id)
            return await interaction.response.send_message("Falha ao entregar o cargo. Avise a staff.", ephemeral=True)

        await interaction.response.send_message(f"Cargo {role.mention} entregue com sucesso.", ephemeral=True)


class EditMessageModal(discord.ui.Modal, title='Criar Notificação'):
    mensagem = discord.ui.TextInput(
        label='Digite a mensagem para o chat',
        style=discord.TextStyle.paragraph,
        placeholder='Ex: Pessoal, venham pro chat principal conversar!',
        required=True,
        max_length=2000
    )

    def __init__(self, view: discord.ui.View):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.view.msg_content = self.mensagem.value
            embed = interaction.message.embeds[0]

            for i, field in enumerate(embed.fields):
                if "Pré-visualização" in field.name:
                    embed.set_field_at(
                        i,
                        name="📝 Pré-visualização da mensagem",
                        value=f"```\n@Reviver {self.mensagem.value}\n```",
                        inline=False
                    )
                    break

            await interaction.response.edit_message(embed=embed, view=self.view)
        except Exception as e:
            log.error(f"Erro ao processar EditMessageModal: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Erro ao processar o texto inserido.", ephemeral=True)

class ReviverView(discord.ui.View):
    def __init__(self, cog, role_id: int, attachment: discord.Attachment = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.role_id = role_id
        self.attachment = attachment
        self.msg_content = None

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        log.error(f"Erro na ReviverView para o usuário {interaction.user.id}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Ocorreu um erro de comunicação com o Discord ao processar este botão.", ephemeral=True)

    def disable_all_buttons(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Enviar Notificação", style=discord.ButtonStyle.green, emoji="📢", custom_id="rev_trigger", row=0)
    async def trigger_reviver(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.msg_content:
            return await interaction.response.send_message("❌ Clique em `✏️ Editar Mensagem` e defina um texto antes de enviar.", ephemeral=True)

        if not interaction.user.guild_permissions.manage_messages and not has_full_access(interaction.user):
            user_roles = [r.id for r in interaction.user.roles]
            if REVIVER_PERM_ROLE_ID not in user_roles:
                return await interaction.response.send_message("❌ Você não tem permissão para usar este painel.", ephemeral=True)

        try:
            history = await self.cog.get_reviver_history()
            if history:
                dt_utc = history[0]['timestamp']
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)

                diff = datetime.now(timezone.utc) - dt_utc
                if diff.total_seconds() < (REVIVER_COOLDOWN_MINUTES * 60):
                    remaining = int((dt_utc.timestamp()) + (REVIVER_COOLDOWN_MINUTES * 60))
                    return await interaction.response.send_message(
                        f"⏳ **Cooldown ativo.**\n"
                        f"Você poderá enviar novamente <t:{remaining}:R>.",
                        ephemeral=True
                    )
        except Exception as e:
            log.error(f"Erro ao verificar cooldown do reviver: {e}")

        try:
            kwargs = {
                "content": f"<@&{self.role_id}> {self.msg_content}",
                "allowed_mentions": discord.AllowedMentions(roles=True)
            }

            if self.attachment:
                file = await self.attachment.to_file()
                kwargs["file"] = file

            await interaction.channel.send(**kwargs)

        except discord.Forbidden:
            return await interaction.response.send_message("❌ Não tenho permissão para mencionar cargos ou anexar arquivos neste canal.", ephemeral=True)
        except discord.HTTPException as e:
            log.error(f"Falha HTTP ao disparar reviver: {e}")
            return await interaction.response.send_message("❌ Não consegui enviar a mensagem agora. Tente novamente.", ephemeral=True)

        await self.cog.add_reviver_log(interaction.user.id)
        self.disable_all_buttons()

        embed = discord.Embed(
            title="✨ Mensagem enviada",
            description=f"A chamada foi enviada por {interaction.user.mention}.",
            color=discord.Color.green()
        )
        if self.attachment:
            embed.set_image(url=self.attachment.url)

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Editar Mensagem", style=discord.ButtonStyle.blurple, emoji="✏️", custom_id="rev_edit", row=0)
    async def edit_msg(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditMessageModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Ver Histórico", style=discord.ButtonStyle.gray, emoji="📋", custom_id="rev_stats", row=1)
    async def show_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        history = await self.cog.get_reviver_history()

        if not history:
            return await interaction.response.send_message("📭 Nenhum envio recente encontrado.", ephemeral=True)

        desc = ""
        for i, entry in enumerate(history, 1):
            dt_utc = entry['timestamp']
            if dt_utc.tzinfo is None: dt_utc = dt_utc.replace(tzinfo=timezone.utc)

            dt_brt = dt_utc.astimezone(FUSO_BRT)
            data_escrita = dt_brt.strftime("%d/%m às %H:%M")
            timestamp_unix = int(dt_utc.timestamp())

            desc += f"`#{i:02d}` | 👤 <@{entry['user_id']}> | 🕒 {data_escrita} (<t:{timestamp_unix}:R>)\n"

        embed = discord.Embed(title="📋 Histórico de Engajamento", description=desc, color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.red, emoji="✖️", custom_id="rev_cancel", row=1)
    async def cancel_reviver(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.disable_all_buttons()
        await interaction.response.edit_message(content="❌ Envio cancelado.", embed=None, view=self)


class Engagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.badges_cache = {}
        self.load_badges_from_db()
        self.supporter_tag_check_loop.start()

    def cog_unload(self):
        self.supporter_tag_check_loop.cancel()

    def load_badges_from_db(self):
        try:
            data = event_col.find_one({"_id": "badges_config"})
            if data and "roles" in data:
                self.badges_cache = data["roles"]
            else:
                self.badges_cache = DEFAULT_STAFF_MAP.copy()
                event_col.update_one(
                    {"_id": "badges_config"},
                    {"$set": {"roles": self.badges_cache}},
                    upsert=True
                )
        except Exception as e:
            log.error(f"Falha estrutural ao carregar badges do MongoDB: {e}")
            self.badges_cache = DEFAULT_STAFF_MAP.copy()

    async def get_vip_role_id(self, uid, guild_id):
        try:
            data = await asyncio.to_thread(vip_col.find_one, {"_id": f"{guild_id}:{uid}"})
            if not data:
                data = await asyncio.to_thread(
                    vip_col.find_one,
                    {
                        "_id": str(uid),
                        "$or": [{"guild_id": str(guild_id)}, {"guild_id": {"$exists": False}}],
                    },
                )
            return data.get("role_id") if data else None
        except Exception as e:
            log.error(f"Falha ao consultar VIP de {uid}: {e}")
            return None

    async def get_badges(self, member: discord.Member):
        badges = []
        found_roles = []
        try:
            for role in member.roles:
                str_id = str(role.id)
                if str_id in self.badges_cache:
                    found_roles.append((role.position, self.badges_cache[str_id]))
            found_roles.sort(key=lambda x: x[0], reverse=True)
            for _, text in found_roles:
                badges.append(text)

            top_chat = await asyncio.to_thread(msg_col.find_one, {}, sort=[("count", -1)])
            if top_chat and str(top_chat["_id"]) == str(member.id):
                badges.append("💬 **Top #1 Chat Global**")

            top_voice = await asyncio.to_thread(voice_col.find_one, {}, sort=[("time", -1)])
            if top_voice and str(top_voice["_id"]) == str(member.id):
                badges.append("🎙️ **Top #1 Voz Global**")

            if member.joined_at:
                delta = datetime.now(timezone.utc) - member.joined_at
                days = delta.days
                if days >= 365: badges.append("🥇 **Lenda (1+ Ano)**")
                elif days >= 180: badges.append("🥈 **Veterano (6+ Meses)**")
                elif days >= 90: badges.append("🥉 **Membro Fiel (3+ Meses)**")
                else: badges.append("🌱 **Novato**")

            if member.premium_since:
                badges.append("🚀 **Booster**")

        except Exception as e:
            log.error(f"Bug detectado ao processar badges para o usuário {member.id}: {e}")

        return "\n".join(badges) if badges else "Nenhuma conquista visível."

    async def send_help_panel(self, ctx: commands.Context):
        embed = build_help_embed()
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        kwargs = {"embed": embed, "view": HelpView(ctx.author.id if ctx.author else None)}
        if ctx.interaction:
            kwargs["ephemeral"] = True
        await ctx.send(**kwargs)

    async def send_userinfo_panel(self, ctx: commands.Context, usuario: discord.Member = None):
        u = usuario or ctx.author
        e = discord.Embed(color=discord.Color.blurple())
        e.set_author(name=f"Perfil de {u.name}", icon_url=u.display_avatar.url)
        e.set_thumbnail(url=u.display_avatar.url)
        e.add_field(name="🆔 Identificação", value=f"`{u.id}`", inline=True)
        e.add_field(name="📅 Criação", value=f"<t:{int(u.created_at.timestamp())}:d>", inline=True)

        member = ctx.guild.get_member(u.id) if ctx.guild else None
        if member:
            e.add_field(name="📥 Ingresso", value=f"<t:{int(member.joined_at.timestamp())}:d>" if member.joined_at else "N/A", inline=True)
            badges_str = await self.get_badges(member)
            e.add_field(name="🏅 Conquistas", value=badges_str, inline=False)

            roles = sorted(member.roles, key=lambda r: r.position, reverse=True)
            roles_mentions = [r.mention for r in roles if r.name != "@everyone"]
            roles_str = ", ".join(roles_mentions) if roles_mentions else "Nenhum"

            if len(roles_str) > 1000:
                roles_str = roles_str[:1000] + "..."
            e.add_field(name=f"🎭 Cargos ({len(roles_mentions)})", value=roles_str, inline=False)
        else:
            e.description = "⚠️ Este usuário não está neste servidor."

        await ctx.send(embed=e)

    @tasks.loop(hours=SUPPORTER_TAG_CHECK_INTERVAL_HOURS)
    async def supporter_tag_check_loop(self):
        total_checked = 0
        total_removed = 0

        for guild in self.bot.guilds:
            role = guild.get_role(APOIADOR_ROLE_ID)
            if role is None:
                continue

            me = guild.me
            if me is None or role.managed or role >= me.top_role:
                log.warning("Nao foi possivel verificar Apoiador em %s: hierarquia/cargo invalido.", guild.id)
                continue

            for member in list(role.members):
                total_checked += 1
                if member_has_server_tag(member):
                    continue

                try:
                    await member.remove_roles(role, reason="Apoiador removido: tag do servidor nao encontrada")
                    total_removed += 1
                    await asyncio.sleep(SUPPORTER_TAG_REMOVAL_DELAY_SECONDS)
                except discord.HTTPException:
                    log.exception("Falha ao remover Apoiador de %s na guild %s", member.id, guild.id)

        if total_checked or total_removed:
            log.info("Verificacao de Apoiador concluida: %s checados, %s removidos.", total_checked, total_removed)

    @supporter_tag_check_loop.before_loop
    async def before_supporter_tag_check_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="config_badge", description="Adiciona/Atualiza uma badge para um cargo.")
    @check_owner_or_perm(administrator=True)
    async def config_badge(self, it, cargo: discord.Role, emoji: str, nome_da_funcao: str):
        from .commands.config_badge_command import execute

        await execute(self, it, cargo, emoji, nome_da_funcao)

    @app_commands.command(name="remover_badge", description="Remove uma badge configurada de um cargo.")
    @check_owner_or_perm(administrator=True)
    async def remover_badge(self, it, cargo: discord.Role):
        from .commands.remover_badge_command import execute

        await execute(self, it, cargo)

    @app_commands.command(name="apoiador_painel", description="Envia o painel para resgatar o cargo Apoiador.")
    @check_owner_or_perm(administrator=True)
    @app_commands.describe(canal="Canal onde o painel será enviado. Se vazio, usa o canal atual.")
    async def apoiador_painel(self, it: discord.Interaction, canal: discord.TextChannel = None):
        if not it.guild:
            return await it.response.send_message("Use este comando dentro de um servidor.", ephemeral=True)

        target_channel = canal or it.channel
        if not isinstance(target_channel, discord.TextChannel):
            return await it.response.send_message("Escolha um canal de texto válido.", ephemeral=True)

        role = it.guild.get_role(APOIADOR_ROLE_ID)
        if role is None:
            return await it.response.send_message("Cargo Apoiador não encontrado neste servidor.", ephemeral=True)

        me = it.guild.me
        if me is None or role.managed or role >= me.top_role:
            return await it.response.send_message(
                "Não consigo gerenciar o cargo Apoiador por causa da hierarquia de cargos.",
                ephemeral=True,
            )

        await target_channel.send(embed=build_supporter_embed(it.guild), view=SupporterClaimView())
        await it.response.send_message(f"Painel de Apoiador enviado em {target_channel.mention}.", ephemeral=True)

    async def add_reviver_log(self, user_id):
        try:
            await asyncio.to_thread(
                event_col.update_one,
                {"_id": "reviver_stats"},
                {"$push": {
                    "history": {
                        "$each": [{"user_id": user_id, "timestamp": datetime.now(timezone.utc)}],
                        "$position": 0,
                        "$slice": 10
                    }
                }},
                upsert=True
            )
        except Exception as e:
            log.error(f"Falha ao registrar log de engajamento no DB: {e}")

    async def get_reviver_history(self):
        try:
            data = await asyncio.to_thread(event_col.find_one, {"_id": "reviver_stats"})
            return data.get("history", []) if data else []
        except Exception as e:
            log.error(f"Falha ao recuperar histórico de engajamento: {e}")
            return []

    async def get_jogar_last_used(self, user_id: int):
        try:
            data = await asyncio.to_thread(event_col.find_one, {"_id": "jogar_cooldowns"})
            users = data.get("users", {}) if data else {}
            return users.get(str(user_id))
        except Exception as e:
            log.error(f"Falha ao recuperar cooldown do /jogar para {user_id}: {e}")
            return None

    async def set_jogar_last_used(self, user_id: int):
        try:
            await asyncio.to_thread(
                event_col.update_one,
                {"_id": "jogar_cooldowns"},
                {
                    "$set": {
                        f"users.{user_id}": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
            return True
        except Exception as e:
            log.error(f"Falha ao registrar cooldown do /jogar para {user_id}: {e}")
            return False

    @app_commands.command(name="reviver", description="Abre o painel interativo para movimentar o chat.")
    @app_commands.describe(imagem="Selecione uma imagem para enviar junto com a notificação (opcional)")
    @check_owner_or_perm(manage_messages=True, allowed_role_id=REVIVER_PERM_ROLE_ID)
    async def reviver(self, it: discord.Interaction, imagem: discord.Attachment = None):
        from .commands.reviver_command import execute

        await execute(self, it, imagem)

    @app_commands.command(name="jogar", description="Chama pessoas para jogar com cooldown individual de 1h.")
    @app_commands.describe(
        jogo="Nome do jogo ou atividade",
        mensagem="Mensagem do chamado"
    )
    async def jogar(self, it: discord.Interaction, jogo: str, mensagem: str):
        from .commands.jogar_command import execute

        try:
            await execute(self, it, jogo, mensagem)
        except Exception:
            log.exception(
                "jogar_command_unhandled_error guild_id=%s channel_id=%s user_id=%s",
                getattr(it.guild, "id", None),
                getattr(it.channel, "id", None),
                getattr(it.user, "id", None),
            )
            message = "❌ O /jogar encontrou um erro interno. O erro foi registrado."
            if it.response.is_done():
                await it.followup.send(message, ephemeral=True)
            else:
                await it.response.send_message(message, ephemeral=True)

    @commands.hybrid_command(name="ajuda", description="Exibe o menu interativo de comandos do bot.")
    async def ajuda(self, ctx: commands.Context):
        await self.send_help_panel(ctx)

    @commands.hybrid_command(name="userinfo", description="Info do usuário e Conquistas.")
    async def userinfo(self, ctx: commands.Context, usuario: discord.Member = None):
        try:
            await self.send_userinfo_panel(ctx, usuario)
        except Exception as e:
            log.error(f"Erro ao compilar userinfo: {e}")
            if ctx.interaction:
                await ctx.send("❌ Não consegui carregar as informações do usuário.", ephemeral=True)
            else:
                await ctx.send("❌ Não consegui carregar as informações do usuário.")

    @app_commands.command(name="verificarbot", description="Verifica se um bot possui a flag oficial de verificado.")
    @app_commands.describe(id="ID do usuário ou bot que será verificado")
    async def verificarbot(self, it: discord.Interaction, id: str):
        from .commands.verificarbot_command import execute

        await execute(self, it, id)

    @app_commands.command(name="notificar", description="Notifica seu cargo VIP.")
    async def notificar(self, it, mensagem: str):
        from .commands.notificar_command import execute

        await execute(self, it, mensagem)

async def setup(bot):
    bot.add_view(SupporterClaimView())
    await bot.add_cog(Engagement(bot))
    log.info("Módulo de Engagement inicializado e injetado no processo.")
