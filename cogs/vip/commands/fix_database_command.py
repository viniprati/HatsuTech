from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction):
    await it.response.defer(ephemeral=True)
    if not await ensure_db_online(it, "o comando /fix_database"):
        return


    all_temps = await asyncio.to_thread(lambda: list(temp_col.find({"guild_id": str(it.guild.id)})))
    if not all_temps:
        return await it.followup.send("Banco de dados vazio.", ephemeral=True)


    groups = {}
    for doc in all_temps:
        key = f"{doc['user_id']}-{doc['role_id']}"
        if key not in groups:
            groups[key] = []
        groups[key].append(doc)

    fixed_count = 0
    now = time.time()


    for key, docs in groups.items():
        if len(docs) > 1:

            total_remaining_seconds = 0
            user_id = docs[0]['user_id']
            role_id = docs[0]['role_id']

            for doc in docs:
                end_time = doc.get("end_time", 0)
                if end_time > now:
                    remaining = end_time - now
                    total_remaining_seconds += remaining


                await asyncio.to_thread(temp_col.delete_one, {"_id": doc["_id"]})


            if total_remaining_seconds > 0:
                new_end = now + total_remaining_seconds
                await asyncio.to_thread(
                    temp_col.insert_one,
                    {
                        "user_id": user_id,
                        "guild_id": str(it.guild.id),
                        "role_id": role_id,
                        "end_time": new_end
                    }
                )
                fixed_count += 1

    await it.followup.send(f"✅ **Manutenção concluída!**\n🔧 Usuários unificados/corrigidos: {fixed_count}", ephemeral=True)
