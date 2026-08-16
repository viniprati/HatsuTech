from __future__ import annotations
from ..cog import *


async def execute(self, it):
    await it.response.defer(ephemeral=True)




    await it.followup.send("✅ **Migração:** Função pronta (verifique o código se precisar inserir dados).", ephemeral=True)
