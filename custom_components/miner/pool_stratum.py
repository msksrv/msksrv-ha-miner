"""Apply stratum pool settings to a miner via pyasic config."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from pyasic.config.pools import Pool
from pyasic.config.pools import PoolGroup

_LOGGER = logging.getLogger(__name__)

MAX_POOLS_PER_GROUP = 3


def build_pool_url(host: str, port: int, use_ssl: bool) -> str:
    scheme = "stratum+ssl" if use_ssl else "stratum+tcp"
    return f"{scheme}://{host}:{port}"


def ensure_first_pool_group(cfg: Any) -> PoolGroup:
    if not cfg.pools.groups:
        cfg.pools.groups = [PoolGroup(pools=[])]
    return cfg.pools.groups[0]


async def async_apply_primary_stratum(
    miner: Any,
    host: str,
    port: int,
    use_ssl_override: bool | None,
    username: str | None,
    password: str | None,
    *,
    force_user_password: bool = False,
) -> bool:
    """Replace or create the first pool slot (primary).

    If force_user_password is True, always set worker user/password from arguments
    (including empty strings), e.g. when applying from the options form.
    """
    host = str(host).strip()
    if not host:
        return False
    try:
        port_int = int(port)
        if port_int <= 0 or port_int > 65535:
            return False
    except (TypeError, ValueError):
        return False

    cfg = await miner.get_config()
    group = ensure_first_pool_group(cfg)

    if not group.pools:
        group.pools.append(
            Pool(
                url=build_pool_url(host, port_int, bool(use_ssl_override)),
                user=str(username or ""),
                password=str(password or ""),
            )
        )
    else:
        pool = group.pools[0]
        parsed = urlparse(str(pool.url or ""))
        current_use_ssl = parsed.scheme == "stratum+ssl"
        use_ssl = (
            bool(use_ssl_override)
            if use_ssl_override is not None
            else current_use_ssl
        )
        pool.url = build_pool_url(host, port_int, use_ssl)
        if force_user_password:
            pool.user = str(username or "")
            pool.password = str(password or "")
        else:
            if username is not None:
                pool.user = str(username)
            if password is not None:
                pool.password = str(password)

    await miner.send_config(cfg)
    return True


async def async_append_stratum_pool(
    miner: Any,
    host: str,
    port: int,
    use_ssl: bool,
    username: str | None,
    password: str | None,
) -> bool:
    """Append a backup pool if under the slot limit."""
    host = str(host).strip()
    if not host:
        return False
    try:
        port_int = int(port)
        if port_int <= 0 or port_int > 65535:
            return False
    except (TypeError, ValueError):
        return False

    cfg = await miner.get_config()
    group = ensure_first_pool_group(cfg)

    if len(group.pools) >= MAX_POOLS_PER_GROUP:
        _LOGGER.error(
            "Cannot append pool: at most %s pools in the primary group",
            MAX_POOLS_PER_GROUP,
        )
        return False

    group.pools.append(
        Pool(
            url=build_pool_url(host, port_int, use_ssl),
            user=str(username or ""),
            password=str(password or ""),
        )
    )
    await miner.send_config(cfg)
    return True
