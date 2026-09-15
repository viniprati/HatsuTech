from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import aiohttp
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path.home() / ".env", override=False)


class ClashRoyaleApiError(Exception):
    def __init__(self, status: int, reason: str = "", message: str = ""):
        self.status = int(status)
        self.reason = reason or "api_error"
        self.message = message or "Erro ao consultar a API do Clash Royale."
        super().__init__(f"{self.status} {self.reason}: {self.message}")


class ClashRoyaleClient:
    BASE_URL = "https://api.clashroyale.com/v1"
    TAG_RE = re.compile(r"^#[0289PYLQGRJCUV]{3,20}$")

    def __init__(self, token: str | None = None, ttl_seconds: int = 300):
        self.token = (token or os.getenv("CLASH_ROYALE_API_TOKEN") or "").strip()
        self.ttl_seconds = int(ttl_seconds)
        self._session: aiohttp.ClientSession | None = None
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = asyncio.Lock()
        self._public_ip_cache: tuple[float, str] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self.configured:
            raise ClashRoyaleApiError(0, "missing_token", "CLASH_ROYALE_API_TOKEN nao configurado.")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                    "User-Agent": "HatsuTech-Discord-Bot/1.0",
                },
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    def clear_cache(self) -> int:
        size = len(self._cache)
        self._cache.clear()
        return size

    async def get_public_ip(self) -> str | None:
        now = time.time()
        if self._public_ip_cache and self._public_ip_cache[0] > now:
            return self._public_ip_cache[1]
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://api.ipify.org") as resp:
                    if resp.status != 200:
                        return None
                    ip = (await resp.text()).strip()
                    if ip:
                        self._public_ip_cache = (time.time() + 300, ip)
                        return ip
        except Exception:
            return None
        return None

    @staticmethod
    def normalize_tag(tag: str) -> str:
        value = str(tag or "").strip().upper().replace(" ", "")
        if not value:
            raise ValueError("Informe uma tag valida.")
        if not value.startswith("#"):
            value = f"#{value}"
        if not ClashRoyaleClient.TAG_RE.fullmatch(value):
            raise ValueError(
                "Tag invalida. Use a tag do Clash Royale com `#` e apenas caracteres validos, exemplo: `#P90UU9JCQ`."
            )
        return value

    @classmethod
    def encode_tag(cls, tag: str) -> str:
        return quote(cls.normalize_tag(tag), safe="")

    async def request(self, path: str, params: dict | None = None, ttl: int | None = None):
        params = {key: value for key, value in (params or {}).items() if value is not None}
        cache_key = f"{path}?{tuple(sorted(params.items()))}"
        ttl = self.ttl_seconds if ttl is None else int(ttl)
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

        async with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > time.time():
                return cached[1]

            session = await self._get_session()
            url = f"{self.BASE_URL}{path}"
            for _attempt in range(4):
                async with session.get(url, params=params) as resp:
                    if resp.status == 429:
                        try:
                            data = await resp.json(content_type=None)
                            retry_after = float(data.get("retryAfter") or data.get("retry_after") or 1)
                        except Exception:
                            retry_after = 1
                        await asyncio.sleep(retry_after + 0.25)
                        continue

                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {"reason": "bad_response", "message": await resp.text()}

                    if 200 <= resp.status < 300:
                        self._cache[cache_key] = (time.time() + ttl, data)
                        return data

                    message = str(data.get("message") or data)[:300]
                    if resp.status == 403:
                        public_ip = await self.get_public_ip()
                        if public_ip:
                            message = f"{message} IP publico da host: {public_ip}"
                    raise ClashRoyaleApiError(
                        resp.status,
                        str(data.get("reason") or "api_error"),
                        message,
                    )

            raise ClashRoyaleApiError(429, "rate_limited", "A API limitou as requisicoes.")

    async def get_player(self, tag: str):
        return await self.request(f"/players/{self.encode_tag(tag)}")

    async def get_player_battlelog(self, tag: str):
        return await self.request(f"/players/{self.encode_tag(tag)}/battlelog", ttl=120)

    async def get_player_chests(self, tag: str):
        return await self.request(f"/players/{self.encode_tag(tag)}/upcomingchests", ttl=600)

    async def get_clan(self, tag: str):
        return await self.request(f"/clans/{self.encode_tag(tag)}")

    async def search_clans(self, name: str, limit: int = 10):
        return await self.request("/clans", {"name": name, "limit": max(1, min(limit, 25))})

    async def get_clan_members(self, tag: str, limit: int = 50):
        return await self.request(f"/clans/{self.encode_tag(tag)}/members", {"limit": max(1, min(limit, 100))})

    async def get_clan_warlog(self, tag: str):
        return await self.request(f"/clans/{self.encode_tag(tag)}/warlog")

    async def get_clan_current_river_race(self, tag: str):
        return await self.request(f"/clans/{self.encode_tag(tag)}/currentriverrace")

    async def get_clan_river_race_log(self, tag: str):
        return await self.request(f"/clans/{self.encode_tag(tag)}/riverracelog")

    async def get_cards(self):
        return await self.request("/cards", ttl=3600)

    async def get_locations(self):
        return await self.request("/locations", {"limit": 250}, ttl=86400)

    async def get_location_ranking(self, location_id: str | int, kind: str, limit: int = 10):
        kind = "clans" if kind == "clans" else "players"
        return await self.request(
            f"/locations/{location_id}/rankings/{kind}",
            {"limit": max(1, min(limit, 25))},
            ttl=900,
        )

    async def get_events(self):
        return await self.request("/events", ttl=900)

    async def get_global_tournaments(self):
        return await self.request("/globaltournaments", ttl=900)

    async def search_tournaments(self, name: str, limit: int = 10):
        return await self.request("/tournaments", {"name": name, "limit": max(1, min(limit, 25))})

    async def get_tournament(self, tag: str):
        return await self.request(f"/tournaments/{self.encode_tag(tag)}")

    async def get_leaderboards(self):
        return await self.request("/leaderboards", ttl=3600)
