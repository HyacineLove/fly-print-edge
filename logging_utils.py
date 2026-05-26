import logging
import os
from typing import Any, Dict, Mapping, Optional


VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
NOISY_DEPENDENCY_LOGGERS = {
    "asyncio": logging.INFO,
    "urllib3": logging.INFO,
    "urllib3.connectionpool": logging.INFO,
    "websockets": logging.INFO,
    "websockets.client": logging.INFO,
    # This warning is a known benign side effect of sync zeroconf cleanup.
    "zeroconf": logging.ERROR,
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
    logging.basicConfig(
        level=resolved["level"],
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )
    for logger_name, logger_level in NOISY_DEPENDENCY_LOGGERS.items():
        logging.getLogger(logger_name).setLevel(logger_level)
    return resolved
