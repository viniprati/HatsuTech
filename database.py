import os
import time
import threading
import logging
from types import SimpleNamespace

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

load_dotenv()

MONGO_DB_NAME = "DiscordBotDB"
RECONNECT_COOLDOWN_SECONDS = 15
log = logging.getLogger(__name__)

uri = os.getenv("MONGO_URI")
client = None
db = None

_db_online = False
_last_reconnect_try = 0.0
_reconnect_lock = threading.Lock()
_index_lock = threading.Lock()
_index_initialization_started = False
_indexes_initialized = False


class _NullCursor:
    def sort(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def skip(self, *args, **kwargs):
        return self

    def max_time_ms(self, *args, **kwargs):
        return self

    def __iter__(self):
        return iter(())

    def __next__(self):
        raise StopIteration


class _SafeCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def _mark_failed(self, error):
        global db, client
        db = None
        client = None
        _set_online_status(False, str(error))
        self._cursor = None

    def sort(self, *args, **kwargs):
        if self._cursor is None:
            return self
        try:
            self._cursor = self._cursor.sort(*args, **kwargs)
        except (PyMongoError, OSError) as e:
            self._mark_failed(e)
        return self

    def limit(self, *args, **kwargs):
        if self._cursor is None:
            return self
        try:
            self._cursor = self._cursor.limit(*args, **kwargs)
        except (PyMongoError, OSError) as e:
            self._mark_failed(e)
        return self

    def skip(self, *args, **kwargs):
        if self._cursor is None:
            return self
        try:
            self._cursor = self._cursor.skip(*args, **kwargs)
        except (PyMongoError, OSError) as e:
            self._mark_failed(e)
        return self

    def max_time_ms(self, *args, **kwargs):
        if self._cursor is None:
            return self
        try:
            self._cursor = self._cursor.max_time_ms(*args, **kwargs)
        except (PyMongoError, OSError) as e:
            self._mark_failed(e)
        return self

    def __iter__(self):
        if self._cursor is None:
            return iter(())

        def safe_iter():
            try:
                for item in self._cursor:
                    yield item
            except (PyMongoError, OSError) as e:
                self._mark_failed(e)

        return safe_iter()

    def __next__(self):
        if self._cursor is None:
            raise StopIteration
        try:
            return next(self._cursor)
        except StopIteration:
            raise
        except (PyMongoError, OSError) as e:
            self._mark_failed(e)
            raise StopIteration


def _result_stub(**kwargs):
    base = {"acknowledged": False}
    base.update(kwargs)
    return SimpleNamespace(**base)


def _default_for_method(method_name: str):
    if method_name == "find":
        return _NullCursor()
    if method_name in {"aggregate", "distinct"}:
        return []
    if method_name in {"find_one", "find_one_and_update", "find_one_and_delete", "find_one_and_replace"}:
        return None
    if method_name == "count_documents":
        return 0
    if method_name.startswith("insert"):
        return _result_stub(inserted_id=None, inserted_ids=[])
    if method_name.startswith("update") or method_name.startswith("replace"):
        return _result_stub(matched_count=0, modified_count=0, upserted_id=None)
    if method_name.startswith("delete"):
        return _result_stub(deleted_count=0)
    return None


def _set_online_status(is_online: bool, reason: str | None = None):
    global _db_online
    if _db_online == is_online:
        return
    _db_online = is_online
    if is_online:
        print("MongoDB reconectado com sucesso.")
    else:
        msg = "MongoDB indisponivel. Entrando em modo degradado."
        if reason:
            msg += f" Motivo: {reason}"
        print(msg)


def is_db_online() -> bool:
    return _db_online


def _build_client() -> MongoClient | None:
    if not uri:
        return None
    return MongoClient(
        uri,
        tlsCAFile=certifi.where(),
        connectTimeoutMS=15000,
        socketTimeoutMS=30000,
        serverSelectionTimeoutMS=8000,
        retryReads=True,
        retryWrites=True,
    )


def _connect_once() -> bool:
    global client, db
    if not uri:
        print("ERRO: MONGO_URI nao encontrada.")
        _set_online_status(False, "MONGO_URI ausente")
        return False

    try:
        new_client = _build_client()
        if new_client is None:
            _set_online_status(False, "cliente nao criado")
            return False
        new_client.admin.command("ping")
        client = new_client
        db = client.get_database(MONGO_DB_NAME)
        _set_online_status(True)
        initializer = globals().get("initialize_indexes_safely")
        if initializer:
            initializer()
        return True
    except Exception as e:
        client = None
        db = None
        _set_online_status(False, str(e))
        return False


def _ensure_connection() -> bool:
    global _last_reconnect_try
    if db is not None:
        return True
    if not uri:
        return False

    now = time.time()
    if now - _last_reconnect_try < RECONNECT_COOLDOWN_SECONDS:
        return False

    with _reconnect_lock:
        now = time.time()
        if db is not None:
            return True
        if now - _last_reconnect_try < RECONNECT_COOLDOWN_SECONDS:
            return False
        _last_reconnect_try = now
        return _connect_once()


class ResilientCollection:
    def __init__(self, collection_name: str):
        self.collection_name = collection_name

    def _get_collection(self):
        if db is None and not _ensure_connection():
            return None
        if db is None:
            return None
        return db[self.collection_name]

    def __getattr__(self, method_name):
        def safe_method(*args, **kwargs):
            col = self._get_collection()
            if col is None:
                return _default_for_method(method_name)
            try:
                method = getattr(col, method_name)
                result = method(*args, **kwargs)
                _set_online_status(True)
                if method_name in {"find", "aggregate"}:
                    return _SafeCursor(result)
                return result
            except (PyMongoError, OSError) as e:

                global db, client
                db = None
                client = None
                _set_online_status(False, str(e))
                return _default_for_method(method_name)

        return safe_method


print("Conectando ao MongoDB...")
if _connect_once():
    print("SUCESSO! Conectado ao banco.")
else:
    print("Inicializacao em modo degradado (sem MongoDB).")


msg_col = ResilientCollection("contador")
event_col = ResilientCollection("evento_data")
vip_col = ResilientCollection("vip_roles")
vip_recovery_logs_col = ResilientCollection("vip_recovery_logs")
vip_role_presets_col = ResilientCollection("vip_role_presets")
temp_col = ResilientCollection("temproles")
voice_col = ResilientCollection("voice_data")
guilds_col = ResilientCollection("guilds")
updates_col = ResilientCollection("updates")
eco_users_col = ResilientCollection("eco_users")
eco_settings_col = ResilientCollection("eco_settings")
eco_shop_col = ResilientCollection("eco_shop")
eco_limits_col = ResilientCollection("eco_limits")
eco_logs_col = ResilientCollection("eco_logs")
eco_admin_logs_col = ResilientCollection("eco_admin_logs")
eco_vip_transactions_col = ResilientCollection("eco_vip_transactions")


def _initialize_indexes():
    global _indexes_initialized, _index_initialization_started
    try:
        if db is None and not _ensure_connection():
            return
        specs = {
            "vip_roles": [
                ([("guild_id", 1)], "vip_roles_guild_id"),
                ([("user_id", 1)], "vip_roles_user_id"),
                ([("status", 1)], "vip_roles_status"),
            ],
            "vip_role_presets": [
                ([("guild_id", 1)], "vip_presets_guild_id"),
                ([("user_id", 1)], "vip_presets_user_id"),
            ],
            "temproles": [
                ([("guild_id", 1)], "temproles_guild_id"),
                ([("guild_id", 1), ("end_time", 1)], "temproles_guild_end_time"),
            ],
            "vip_recovery_logs": [
                ([("source", 1)], "vip_logs_source"),
                ([("created_at", -1)], "vip_logs_created_at"),
                ([("user_id", 1)], "vip_logs_user_id"),
            ],
            "eco_vip_transactions": [
                ([("guild_id", 1), ("created_at", -1)], "eco_vip_transactions_guild_created"),
                ([("buyer_id", 1), ("created_at", -1)], "eco_vip_transactions_buyer_created"),
                ([("sku", 1)], "eco_vip_transactions_sku"),
            ],
            "guilds": [
                ([("members.user_id", 1)], "guilds_members_user_id"),
                ([("leader_id", 1)], "guilds_leader_id"),
                ([("name", 1)], "guilds_name"),
            ],
        }
        for collection_name, indexes in specs.items():
            for keys, name in indexes:
                db[collection_name].create_index(keys, name=name)
        _indexes_initialized = True
        log.info("Indices VIP/temproles/transacoes verificados com sucesso.")
    except Exception as e:
        log.warning("Nao foi possivel inicializar indices VIP agora: %s", e)
    finally:
        with _index_lock:
            _index_initialization_started = False


def initialize_indexes_safely():
    global _index_initialization_started
    with _index_lock:
        if _indexes_initialized or _index_initialization_started:
            return
        _index_initialization_started = True
    threading.Thread(target=_initialize_indexes, name="mongodb-index-init", daemon=True).start()


initialize_indexes_safely()
