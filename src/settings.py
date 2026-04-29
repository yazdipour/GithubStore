import os
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from re import sub
from typing import Any

from ruamel.yaml import YAML


SOURCE_ICON_URL = ""
SOURCE_TINT_COLOR = "#24292F"
APP_PORT = 8080
CONFIG_PATH = Path(os.getenv("CONFIG_FILE", "config.yml")).expanduser()
yaml = YAML()
yaml.preserve_quotes = True


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"Missing configuration file: {CONFIG_PATH}")

    data = yaml.load(CONFIG_PATH.read_text()) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Configuration file must contain a YAML object: {CONFIG_PATH}")
    return data


CONFIG = _load_config()


def reload_config() -> None:
    global CONFIG
    CONFIG = _load_config()


def _get_config(path: str) -> Any:
    value: Any = CONFIG
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _setting(path: str, default: Any = None) -> Any:
    value = _get_config(path)
    return default if value is None else value


def _required(path: str) -> str:
    value = str(_setting(path, "")).strip()
    if not value:
        raise RuntimeError(f"Missing required setting: {path}")
    return value


def _base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


@dataclass(frozen=True)
class RepositoryConfig:
    url: str
    slug: str
    name: str
    tint_color: str
    icon: str
    config_index: int
    config_key: str


@dataclass(frozen=True)
class Settings:
    source_slug: str
    source_name: str
    source_subtitle: str
    source_description: str
    source_tint_color: str
    source_icon: str
    repositories: tuple[RepositoryConfig, ...]
    base_url: str
    source_icon_url: str
    source_cache_seconds: int
    github_token: str
    host: str
    server_ui_config: bool


def _slug(value: str) -> str:
    slug = sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or "source"


def _dedupe_slug(slug: str, used: set[str]) -> str:
    candidate = slug
    index = 2
    while candidate in used:
        candidate = f"{slug}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def _value(data: dict, key: str) -> str:
    return str(data.get(key) or "").strip()


def _bool_setting(path: str, default: bool = False) -> bool:
    value = _setting(path, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def repository_config_key(raw_repo: Any) -> str:
    normalized = json.dumps(raw_repo, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _load_repositories(default_tint_color: str) -> tuple[RepositoryConfig, ...]:
    repositories = _get_config("repositories")
    if repositories is None:
        return ()
    if not isinstance(repositories, list):
        raise RuntimeError("repositories must be a YAML list")

    repo_configs: list[RepositoryConfig] = []
    used_slugs: set[str] = set()
    for config_index, raw_repo in enumerate(repositories):
        if isinstance(raw_repo, dict):
            repo_data = raw_repo
            raw_url = repo_data.get("url", "")
        else:
            repo_data = {}
            raw_url = raw_repo

        url = str(raw_url).strip()
        if not url:
            continue

        name = _value(repo_data, "name") or url.rstrip("/").split("/")[-1]
        slug = _dedupe_slug(_slug(_value(repo_data, "slug") or name), used_slugs)
        tint_color = _value(repo_data, "tint_color") or default_tint_color
        icon = _value(repo_data, "icon")

        repo_configs.append(
            RepositoryConfig(
                url=url,
                slug=slug,
                name=name,
                tint_color=tint_color,
                icon=icon,
                config_index=config_index,
                config_key=repository_config_key(raw_repo),
            )
        )

    return tuple(repo_configs)


def load_settings() -> Settings:
    source_name = str(_setting("source.name", "GithubStore")).strip()
    source_tint_color = str(_setting("source.tint_color", SOURCE_TINT_COLOR)).strip()
    return Settings(
        source_slug=_slug(str(_setting("source.slug", "source"))),
        source_name=source_name,
        source_subtitle=str(_setting("source.subtitle", "GitHub release IPA source")).strip(),
        source_description=str(
            _setting(
                "source.description",
                "Self-hosted AltStore source generated from GitHub release IPA assets.",
            )
        ).strip(),
        source_tint_color=source_tint_color,
        source_icon=str(_setting("source.icon", "")).strip(),
        repositories=_load_repositories(source_tint_color),
        base_url=_base_url(str(_setting("server.base_url", "http://localhost:8080"))),
        source_icon_url=str(_setting("source.icon_url", SOURCE_ICON_URL)).strip(),
        source_cache_seconds=int(_setting("source.cache_seconds", "600")),
        github_token=str(_setting("github.token") or os.getenv("GITHUB_TOKEN", "")).strip(),
        host=str(_setting("server.host", "0.0.0.0")).strip(),
        server_ui_config=_bool_setting("server.ui_config", False),
    )
