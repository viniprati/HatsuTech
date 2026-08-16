from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, alvo: discord.Member, emoji: str):
    guild_data = self.get_user_guild(alvo.id)
    if not guild_data:
        return await it.response.send_message(f"❌ O usuário **{alvo.display_name}** não está em nenhuma guilda.", ephemeral=True)

    custom_emoji_match = re.match(r'<a?:.+:(\d+)>', emoji)

    if custom_emoji_match:
        emoji_id = int(custom_emoji_match.group(1))
        emoji_obj = self.bot.get_emoji(emoji_id)
        if not emoji_obj:
            return await it.response.send_message(
                "⚠️ **Atenção:** Esse emoji é de um servidor onde eu não estou.\n"
                "Ele foi salvo, mas pode aparecer como texto para os usuários.",
                ephemeral=True
            )
    else:
        if len(emoji) > 4 and not discord.PartialEmoji.from_str(emoji).is_unicode_emoji():
             return await it.response.send_message("❌ Isso não parece ser um emoji válido.", ephemeral=True)

    old_emoji = guild_data.get('emoji', '❓')
    guilds_col.update_one(
        {"_id": guild_data["_id"]},
        {"$set": {"emoji": emoji}}
    )

    embed = discord.Embed(
        title="👮 Alteração Administrativa",
        description=f"O emoji da guilda **{guild_data['name']}** foi alterado.",
        color=discord.Color.orange()
    )
    embed.add_field(name="Antes", value=old_emoji, inline=True)
    embed.add_field(name="Depois", value=emoji, inline=True)
    embed.add_field(name="Admin", value=it.user.mention, inline=False)

    await it.response.send_message(embed=embed)
