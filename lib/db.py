"""Shared MySQL connection helper.

Replaces ~13 duplicate `mysql.connector.connect(...)` blocks across scripts.
Reads db_config.json once and exposes:

    get_config()  -> dict   (raw db_config.json)
    get_conn()    -> mysql.connector connection
    github_token() -> str
    github_repo()  -> str

All scripts SHOULD use these instead of opening their own connection.
"""
from __future__ import annotations

import json
import os
from typing import Any

_FOLDER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_FILE = os.path.join(_FOLDER, 'db_config.json')

_cached_config: dict[str, Any] | None = None


def get_config(path: str | None = None) -> dict[str, Any]:
    """Return db_config.json as dict (cached)."""
    global _cached_config
    if _cached_config is not None and path is None:
        return _cached_config
    target = path or _CONFIG_FILE
    with open(target, encoding='utf-8') as f:
        cfg = json.load(f)
    if path is None:
        _cached_config = cfg
    return cfg


def get_conn(timeout: int = 30, **overrides):
    """Open MySQL connection from db_config.json.

    Args:
        timeout: connection_timeout seconds (default 30)
        **overrides: any kwarg to override config (host, port, user, ...)

    Returns:
        mysql.connector connection object.

    Raises:
        ImportError if mysql.connector not installed.
        FileNotFoundError if db_config.json missing.
    """
    import mysql.connector
    cfg = get_config()
    params = dict(
        host=cfg['host'],
        port=int(cfg.get('port', 3306)),
        user=cfg['user'],
        password=cfg['password'],
        database=cfg['database'],
        connection_timeout=timeout,
        charset='utf8mb4',
    )
    params.update(overrides)
    return mysql.connector.connect(**params)


def github_token() -> str:
    """Return GitHub PAT from db_config.json (empty string if missing)."""
    try:
        return get_config().get('github_token', '') or ''
    except Exception:
        return ''


def github_repo() -> str:
    """Return GitHub repo slug from db_config.json (default tumsbux/daily-report)."""
    try:
        return get_config().get('github_repo', 'tumsbux/daily-report')
    except Exception:
        return 'tumsbux/daily-report'
