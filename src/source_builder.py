import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from src.settings import RepositoryConfig, Settings


class GithubReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class GithubRepo:
    owner: str
    name: str


def _repo_from_url(value: str) -> GithubRepo:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower()
    if host != "github.com":
        raise GithubReleaseError(f"Only github.com repository URLs are supported: {value}")

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise GithubReleaseError(f"Invalid GitHub repository URL: {value}")
    return GithubRepo(owner=parts[0], name=parts[1].removesuffix(".git"))


def _request_json(url: str, settings: Settings) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "GithubStore",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            data = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GithubReleaseError(f"GitHub API error {exc.code} for {url}: {detail}") from exc
    except URLError as exc:
        raise GithubReleaseError(f"Could not reach GitHub API for {url}: {exc.reason}") from exc

    value = json.loads(data)
    if not isinstance(value, dict):
        raise GithubReleaseError(f"Unexpected GitHub API response for {url}")
    return value


def _latest_release(settings: Settings, repo: GithubRepo) -> dict:
    return _request_json(
        f"https://api.github.com/repos/{repo.owner}/{repo.name}/releases/latest",
        settings,
    )


def _ipa_assets(release: dict) -> list[dict]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return []
    return [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and str(asset.get("name") or "").lower().endswith(".ipa")
        and str(asset.get("browser_download_url") or "")
    ]


def _asset_sort_key(asset: dict) -> tuple[int, int]:
    name = str(asset.get("name") or "").lower()
    penalty = 1 if any(part in name for part in ("debug", "symbols", "dsyms")) else 0
    size = int(asset.get("size") or 0)
    return penalty, -size


def _release_ipa_assets(release: dict, repo: GithubRepo) -> list[dict]:
    assets = sorted(_ipa_assets(release), key=_asset_sort_key)
    if not assets:
        raise GithubReleaseError(f"No .ipa asset found on latest release for {repo.owner}/{repo.name}")
    return assets


def _clean_name(value: str) -> str:
    name = Path(value).name
    if name.lower().endswith(".ipa"):
        name = name[:-4]
    name = re.sub(r"[_\-.]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "GitHub App"


def _identifier_component(value: str) -> str:
    component = re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")
    return component or "app"


def _release_version(release: dict) -> str:
    tag = str(release.get("tag_name") or release.get("name") or "").strip()
    return tag.lstrip("v") or "1.0"


def _release_date(release: dict) -> str:
    value = str(release.get("published_at") or release.get("created_at") or "").strip()
    if value:
        return value
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _description(release: dict, repo: GithubRepo) -> str:
    body = str(release.get("body") or "").strip()
    if body:
        return body
    name = str(release.get("name") or release.get("tag_name") or "").strip()
    if name:
        return name
    return f"Latest GitHub release for {repo.owner}/{repo.name}."


def _is_http_url(value: str) -> bool:
    return urlparse(value).scheme in ("http", "https")


def _repo_icon_url(settings: Settings, repo_config: RepositoryConfig) -> str:
    if repo_config.icon:
        if _is_http_url(repo_config.icon):
            return repo_config.icon
        return f"{settings.base_url}/icon/{repo_config.slug}.png"
    return settings.source_icon_url or f"{settings.base_url}/source-icon.png"


def _app_from_release(
    settings: Settings,
    repo_config: RepositoryConfig,
    repo: GithubRepo,
    release: dict,
    asset: dict,
    include_asset_identity: bool,
) -> dict:
    filename = str(asset.get("name") or f"{repo.name}.ipa")
    version = _release_version(release)
    description = _description(release, repo)
    download_url = str(asset["browser_download_url"])
    name = _clean_name(filename) if include_asset_identity else repo_config.name
    bundle_identifier = f"github.{repo.owner.lower()}.{repo.name.lower()}"
    if include_asset_identity:
        bundle_identifier = f"{bundle_identifier}.{_identifier_component(Path(filename).stem)}"

    return {
        "name": name,
        "bundleIdentifier": bundle_identifier,
        "developerName": repo.owner,
        "subtitle": f"{repo.owner}/{repo.name}",
        "localizedDescription": description,
        "iconURL": _repo_icon_url(settings, repo_config),
        "tintColor": repo_config.tint_color,
        "versions": [
            {
                "version": version,
                "buildVersion": version,
                "date": _release_date(release),
                "downloadURL": download_url,
                "localizedDescription": description,
                "size": int(asset.get("size") or 0),
            }
        ],
    }


def _build_apps(settings: Settings, repo_config: RepositoryConfig) -> list[dict]:
    repo = _repo_from_url(repo_config.url)
    release = _latest_release(settings, repo)
    assets = _release_ipa_assets(release, repo)
    include_asset_identity = len(assets) > 1
    return [
        _app_from_release(settings, repo_config, repo, release, asset, include_asset_identity)
        for asset in assets
    ]


async def build_source(settings: Settings) -> dict:
    source: dict = {
        "name": settings.source_name,
        "subtitle": settings.source_subtitle,
        "description": settings.source_description,
        "iconURL": settings.source_icon_url or f"{settings.base_url}/source-icon.png",
        "tintColor": settings.source_tint_color,
        "apps": [],
    }
    errors: list[dict[str, str]] = []

    results = await asyncio.gather(
        *[asyncio.to_thread(_build_apps, settings, repo) for repo in settings.repositories],
        return_exceptions=True,
    )
    for repo_config, result in zip(settings.repositories, results, strict=True):
        if isinstance(result, Exception):
            errors.append(
                {
                    "name": repo_config.name,
                    "url": repo_config.url,
                    "error": str(result),
                }
            )
            continue
        source["apps"].extend(result)

    if errors:
        source["errors"] = errors
    return source
