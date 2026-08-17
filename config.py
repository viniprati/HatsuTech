import os
import logging
from pathlib import Path
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().with_name(".env"))
load_dotenv(Path.home() / ".env", override=False)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SecurityBot")


CHAT_COUNT_CHANNEL_ID = 1117559464363573358
ECONOMY_LOBBY_CHANNEL_IDS = {CHAT_COUNT_CHANNEL_ID}




DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()


try:
    LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
    VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID", "0"))
    MAIN_GUILD_ID = int(os.getenv("MAIN_GUILD_ID", "609159041499004982"))
    TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "1442105700246491189"))
    _allowed_raw = os.getenv("ALLOWED_GUILD_IDS", "609159041499004982,1442105700246491189")
    ALLOWED_GUILD_IDS = tuple(int(x.strip()) for x in _allowed_raw.split(",") if x.strip())
    ECONOMY_LOBBY_CHANNEL_IDS = {CHAT_COUNT_CHANNEL_ID}
    ECONOMY_LOBBY_CHANNEL_ID = CHAT_COUNT_CHANNEL_ID
    ECONOMY_LOG_CHANNEL_ID = int(os.getenv("ECONOMY_LOG_CHANNEL_ID", "0"))
except ValueError:
    logger.warning("Atenção: Algum ID numérico no .env está inválido. Usando padrões.")
    LOG_CHANNEL_ID = 0
    VERIFIED_ROLE_ID = 0
    MAIN_GUILD_ID = 609159041499004982
    TEST_GUILD_ID = 0
    ALLOWED_GUILD_IDS = (MAIN_GUILD_ID,)
    ECONOMY_LOBBY_CHANNEL_IDS = {CHAT_COUNT_CHANNEL_ID}
    ECONOMY_LOBBY_CHANNEL_ID = CHAT_COUNT_CHANNEL_ID
    ECONOMY_LOG_CHANNEL_ID = 0



REVIVER_ROLE_ID = int(os.getenv("REVIVER_ROLE_ID", "999723236193480785"))


REVIVER_PERM_ROLE_ID = int(os.getenv("REVIVER_PERM_ROLE_ID", "1413646810316279990"))



LOG_CARGOS_ID = int(os.getenv("LOG_CARGOS_ID", "1444675225743528087"))

def validate_required_config() -> bool:
    """Valida configuracoes obrigatorias sem encerrar o processo durante import."""
    if not DISCORD_TOKEN:
        logger.critical("ERRO FATAL: Token do Discord faltando! Verifique seu arquivo .env")
        return False
    return True
