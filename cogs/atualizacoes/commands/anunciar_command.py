from __future__ import annotations
from ..cog import *

DM_BROADCAST_DELAY_SECONDS = 1.25


async def execute(self, interaction: discord.Interaction, titulo: str, mensagem: str, imagem: discord.Attachment = None):

    await interaction.response.defer(ephemeral=True)

    if not await ensure_db_online(interaction, "o comando /anunciar"):
        return

    total_users = updates_col.count_documents({})

    if total_users == 0:
        return await interaction.followup.send("⚠️ Ninguém ativou as notificações ainda.")


    embed = discord.Embed(
        title=f"📢 {titulo}",
        description=mensagem,
        color=discord.Color.blue(),
        timestamp=datetime.datetime.now()
    )
    if imagem:
        embed.set_image(url=imagem.url)

    embed.set_footer(text=f"Enviado por {interaction.user.name} • Use /notificacao para cancelar")


    sucessos = 0
    falhas = 0
    bloqueados = 0

    await interaction.followup.send(f"🚀 Iniciando envio para **{total_users}** usuários...")

    for data in updates_col.find({}):
        user_id = data["user_id"]
        try:

            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)

            if user:
                await user.send(embed=embed)
                sucessos += 1
            else:
                falhas += 1

        except discord.Forbidden:

            bloqueados += 1

            updates_col.delete_one({"user_id": user_id})

        except discord.HTTPException as e:
            falhas += 1
            err_text = str(e)
            if e.status == 429 and "1015" in err_text:
                print("Broadcast interrompido: Cloudflare 1015 em discord.com.")
                falhas += max(0, total_users - (sucessos + bloqueados + falhas))
                break
            retry_after = float(getattr(e, "retry_after", 0) or 0)
            if retry_after > 0:
                await asyncio.sleep(min(retry_after + 1, 60))

        except Exception as e:
            print(f"Erro ao enviar para {user_id}: {e}")
            falhas += 1


        await asyncio.sleep(DM_BROADCAST_DELAY_SECONDS)


    embed_report = discord.Embed(title="📊 Relatório de Envio", color=discord.Color.green())
    embed_report.add_field(name="✅ Enviados", value=sucessos, inline=True)
    embed_report.add_field(name="🔒 DM Fechada/Bloqueado", value=bloqueados, inline=True)
    embed_report.add_field(name="⚠️ Falhas Gerais", value=falhas, inline=True)
    embed_report.add_field(name="👥 Total Tentado", value=total_users, inline=True)

    try:
        await interaction.followup.send(embed=embed_report)
    except discord.HTTPException as e:
        print(f"Nao foi possivel enviar relatorio do broadcast: status={e.status}")
