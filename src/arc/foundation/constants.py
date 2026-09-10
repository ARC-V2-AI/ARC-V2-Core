import os
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv

T = TypeVar("T")


def path(p: str | Path) -> Path:
    """Return a Path with '~' expanded reliably."""
    p = Path(p)

    if not str(p).startswith("~/"):
        return p

    home = os.environ.get("HOME")

    if not home:
        raise RuntimeError(
            "Could not determine 'HOME' directory. Please add 'HOME' to env!"
        )

    return Path(home) / Path(*p.parts[1:])


ENV_PATH = path("~/arc/.env")


def load_dot_env() -> bool:
    """Load ARC's .env file.

    Returns:
        True if the .env file was loaded.
        False if the file does not exist.
    """
    if not ENV_PATH.is_file():
        return False

    return load_dotenv(
        ENV_PATH,
        override=False,
    )


# IMPORTANT: load before evaluating configuration constants
ENV_LOADED = load_dot_env()


def get_env(key: str, default: T) -> str | T:
    """
    Return an environment variable or a default value.
    """
    return os.getenv(key, default)


def get_env_str(key: str, default: str) -> str:
    return os.getenv(key, default)


def get_env_bool(key: str, default: str = "false") -> bool:
    value = os.getenv(key)
    if value is None:
        value = default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_env_int(key: str, default: str) -> int:
    value = os.getenv(key)
    if value is None:
        value = default
    return int(value)


def get_env_float(key: str, default: str) -> float:
    value = os.getenv(key)
    if value is None:
        value = default
    return float(value)


def set_env(key: str, value: T):  # pyright: ignore[reportInvalidTypeVarUse]
    _path = ENV_PATH
    _path.parent.mkdir(parents=True, exist_ok=True)

    if _path.is_file():
        lines = _path.read_text("utf-8").splitlines()
    else:
        lines = []

    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")

    _ = _path.write_text("\n".join(lines) + "\n", encoding="utf-8")


DEFAULT_DOT_ENV = {
    "TERMINAL_NO_COLOR": "0",
    "PYTHONUNBUFFERED": "1",
    "STRICT_ERRORS": "1",
    # ---
    "WAIT_ON_DEPENDENCIES": "1",
    "MAX_UNHEALTHY_SERVICE_CHECKS": "3",
    # ---
    "ARC_DIR": "~/arc",
    "SERVICE_RUNTIME_DIR": "~/arc/runtime",
    "SERVICE_LOCK": "~/arc/arc.lock",
    "SERVICE_CONFIG": "~/arc/services.arc.yaml",
    # ---
    "LOG_LEVEL": "INFO",
    "LOG_FILE": "~/arc/arc.log",
    "LOG_CONSOLE": "1",
    "LOG_JSON": "0",
    "LOG_ROTATE": "1",
    "LOG_MAX_BYTES": "10485760",
    "LOG_BACKUP_COUNT": "2",
    # ---
}

_DEV = DEFAULT_DOT_ENV

# System
TERMINAL_NO_COLOR = get_env_bool("TERMINAL_NO_COLOR", _DEV["TERMINAL_NO_COLOR"])
STRICT_ERRORS = get_env_bool("STRICT_ERRORS", _DEV["STRICT_ERRORS"])

WAIT_ON_DEPENDENCIES = get_env_bool(
    "WAIT_ON_DEPENDENCIES", _DEV["WAIT_ON_DEPENDENCIES"]
)
MAX_UNHEALTHY_SERVICE_CHECKS = get_env_int(
    "MAX_UNHEALTHY_SERVICE_CHECKS", _DEV["MAX_UNHEALTHY_SERVICE_CHECKS"]
)

# Project Directories and file locations
ARC_DIR = path(get_env("ARC_DIR", _DEV["ARC_DIR"]))
SERVICE_LOCK = path(get_env_str("SERVICE_LOCK", _DEV["SERVICE_LOCK"]))
SERVICE_CONFIG = path(get_env_str("SERVICE_CONFIG", _DEV["SERVICE_CONFIG"]))
SERVICE_RUNTIME_DIR = path(
    get_env_str("SERVICE_RUNTIME_DIR", _DEV["SERVICE_RUNTIME_DIR"])
)

# Logging
LOG_LEVEL = get_env_str("LOG_LEVEL", _DEV["LOG_LEVEL"])
LOG_FILE = path(get_env_str("LOG_FILE", _DEV["LOG_FILE"]))
LOG_CONSOLE = get_env_bool("LOG_CONSOLE", _DEV["LOG_CONSOLE"])
LOG_JSON = get_env_bool("LOG_JSON", _DEV["LOG_JSON"])
LOG_ROTATE = get_env_bool("LOG_ROTATE", _DEV["LOG_ROTATE"])
LOG_MAX_BYTES = get_env_int("LOG_MAX_BYTES", _DEV["LOG_MAX_BYTES"])
LOG_BACKUP_COUNT = get_env_int("LOG_BACKUP_COUNT", _DEV["LOG_BACKUP_COUNT"])

CONTROL_SOCKET = ARC_DIR / "arc.sock"


def make_default_env() -> Path | None:
    path = ENV_PATH

    if path.exists():
        return None

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    content = "\n".join(f"{key}={value}" for key, value in _DEV.items()) + "\n"

    _ = path.write_text(
        content,
        encoding="utf-8",
    )

    return path
