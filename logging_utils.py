import logging
import os
import sys
from typing import Any, Dict, Mapping, Optional


VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
NOISY_DEPENDENCY_LOGGERS = {
    "asyncio": logging.INFO,
    "urllib3": logging.INFO,
    "urllib3.connectionpool": logging.INFO,
    "websockets": logging.INFO,
    "websockets.client": logging.INFO,
}


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_log_settings(
    config: Dict[str, Any], env: Optional[Mapping[str, str]] = None
) -> Dict[str, Any]:
    env_map = env if env is not None else os.environ
    settings = config.get("settings", {}) if isinstance(config, dict) else {}

    config_level = str(settings.get("log_level") or "INFO").strip().upper()
    config_debug = _parse_bool(settings.get("debug_logging"), default=False)

    env_level = str(env_map.get("FLYPRINT_LOG_LEVEL") or "").strip().upper()
    env_debug_raw = env_map.get("FLYPRINT_DEBUG_LOGGING")

    level_name = env_level or config_level or "INFO"
    if level_name not in VALID_LOG_LEVELS:
        level_name = "INFO"

    debug_logging = _parse_bool(env_debug_raw, default=config_debug)
    if debug_logging:
        level_name = "DEBUG"

    return {
        "level_name": level_name,
        "level": getattr(logging, level_name, logging.INFO),
        "debug_logging": debug_logging,
        "access_log": debug_logging,
    }


def configure_logging(
    config: Dict[str, Any], env: Optional[Mapping[str, str]] = None
) -> Dict[str, Any]:
    resolved = resolve_log_settings(config, env=env)
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    handlers = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    # Always write to a log file in the app directory for diagnostics
    try:
        if getattr(sys, 'frozen', False):
            _app_dir = os.path.dirname(sys.executable)
        else:
            _app_dir = os.path.dirname(os.path.abspath(__file__))
        _log_dir = os.path.join(_app_dir, "logs")
        os.makedirs(_log_dir, exist_ok=True)
        _log_path = os.path.join(_log_dir, "edge.log")
        handlers.append(logging.FileHandler(_log_path, encoding="utf-8"))
    except Exception:
        pass  # never let logging setup crash the server
    if not handlers:
        handlers.append(logging.NullHandler())
    logging.basicConfig(
        level=resolved["level"],
        format=fmt,
        handlers=handlers,
        force=True,
    )
    for logger_name, logger_level in NOISY_DEPENDENCY_LOGGERS.items():
        logging.getLogger(logger_name).setLevel(logger_level)
    return resolved
