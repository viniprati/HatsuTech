from __future__ import annotations
from ..cog import *


async def execute(self, it, nome: str, imagem: discord.Attachment, cor_hex: str=None, cor_secundaria: str=None, membros: str=None):
    await it.response.defer(ephemeral=True)
    if not nome or len(nome.strip()) > 100:
        return await it.followup.send("❌ Nome do cargo inválido (1 a 100 caracteres).", ephemeral=True)
    if imagem.content_type and not imagem.content_type.startswith("image/"):
        return await it.followup.send("❌ O anexo precisa ser uma imagem.", ephemeral=True)


    try:
        color_kwargs = self._build_role_color_kwargs(it.guild, cor_hex, cor_secundaria)
        img_data = await imagem.read()

        processed_icon = process_icon(img_data)

        r = await it.guild.create_role(name=nome.strip(), display_icon=processed_icon, **color_kwargs)


        count = await self.add_members_bulk(it.guild, r, membros)
        await it.followup.send(f"✅ **Cargo Criado:** {r.mention}\n👥 **Membros Adicionados:** {count}", ephemeral=True)
    except ValueError as e:
        await it.followup.send(f"❌ {e}", ephemeral=True)
    except Exception as e:
        await it.followup.send(f"❌ Erro ao criar cargo: {e}", ephemeral=True)
