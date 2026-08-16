from __future__ import annotations
from ..cog import *


SOURCE_LABELS = {
    "temprole": "Temprole manual",
    "loja": "Loja Kaguya",
}


def _build_source_filter(origem: str) -> dict:
    if origem == "temprole":
        return {"source": "temprole"}
    if origem == "loja":
        return {"source": "loja"}
    if origem == "legado":
        return {"$or": [{"source": {"$exists": False}}, {"source": None}, {"source": ""}]}
    return {}


def _source_text(data: dict) -> str:
    source = str(data.get("source") or "")
    if not source:
        return "Legado/sem origem"
    return str(data.get("source_label") or SOURCE_LABELS.get(source, source))


async def execute(self, it: discord.Interaction, origem: str = "todos"):
    await it.response.defer(ephemeral=True)
    if not await ensure_db_online(it, "o comando /vervips"):
        return

    query = {"guild_id": str(it.guild.id)}
    query.update(_build_source_filter(origem))

    temproles_list = await asyncio.to_thread(
        lambda: list(temp_col.find(query).sort("end_time", 1))
    )

    if not temproles_list:
        origem_text = "dessa origem" if origem != "todos" else "ativo"
        return await it.followup.send(f"📂 **Não há nenhum cargo temporário {origem_text}.**", ephemeral=True)

    lines = []
    now = time.time()

    for data in temproles_list:
        user_id = data.get("user_id")
        role_id = data.get("role_id")
        end_time = int(data.get("end_time", 0))
        source_text = _source_text(data)


        status = "🟢" if end_time > now else "🔴"

        line = (
            f"{status} <@{user_id}> \n"
            f"├─ Cargo: <@&{role_id}>\n"
            f"├─ Origem: `{source_text}`\n"
            f"└─ Expira: <t:{end_time}:f> (<t:{end_time}:R>)"
        )
        lines.append(line)

    origem_title = {
        "todos": "Todos",
        "temprole": "Temprole manual",
        "loja": "Loja Kaguya",
        "legado": "Legado/sem origem",
    }.get(origem, "Todos")
    view = VipAdminView(lines, f"⏳ Temproles Ativos - {origem_title} ({len(lines)})", it.user.id)
    await it.followup.send(embed=view.get_embed(), view=view, ephemeral=True)
