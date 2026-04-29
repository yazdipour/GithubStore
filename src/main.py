from html import escape
import json
import logging
from pathlib import Path
import secrets
from time import monotonic
from urllib.parse import parse_qs, urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from ruamel.yaml import YAML

from src.assets import DEFAULT_ICON_PNG
from src.settings import APP_PORT, CONFIG_PATH, load_settings, reload_config, repository_config_key
from src.source_builder import build_source


settings = load_settings()
source_cache: dict[str, object] = {"expires_at": 0.0, "value": None}
repositories_by_slug = {repo.slug: repo for repo in settings.repositories}
SOURCE_ICON_PATHS = (
    Path("/app/imgs/ICON-120-blue.png"),
    Path("imgs/ICON-120-blue.png"),
)
logger = logging.getLogger("uvicorn.error")
csrf_token = secrets.token_urlsafe(32)
yaml = YAML()
yaml.preserve_quotes = True


def _html_page(body: str, status_code: int = 200) -> Response:
    return Response(
        f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GithubStore</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #202124;
      --muted: #626a73;
      --line: #d8dde3;
      --soft: #f5f7f9;
      --panel: #ffffff;
      --accent: #0969da;
      --danger: #b42318;
      --danger-bg: #fff1ef;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #eef1f4;
      color: var(--ink);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    main {{
      width: min(1080px, calc(100% - 32px));
      margin: 36px auto;
      display: grid;
      gap: 22px;
    }}
    header {{
      display: grid;
      gap: 10px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 22px;
    }}
    h1, h2 {{ margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: clamp(2rem, 4vw, 3.2rem); line-height: 1; }}
    h2 {{ font-size: 1.05rem; }}
    p {{ margin: 0; color: var(--muted); }}
    code {{ background: #dde3ea; border-radius: 6px; padding: 3px 6px; overflow-wrap: anywhere; }}
    button, input {{
      font: inherit;
      border-radius: 7px;
    }}
    button {{
      border: 1px solid #1f2328;
      background: #1f2328;
      color: #fff;
      cursor: pointer;
      min-height: 38px;
      padding: 8px 12px;
    }}
    button:hover {{ background: #343941; }}
    input {{
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      background: #fff;
      padding: 8px 10px;
    }}
    label {{ display: grid; gap: 6px; color: var(--muted); font-size: .86rem; }}
    label span {{ color: var(--ink); font-weight: 650; }}
    .source-bar {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 14px;
      border-radius: 8px;
    }}
    .source-url {{ flex: 1 1 320px; min-width: 0; }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(300px, .7fr);
      gap: 22px;
      align-items: start;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }}
    .panel-head {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .repo-list {{
      display: grid;
      gap: 10px;
      padding: 0;
      margin: 0;
      list-style: none;
    }}
    .repo-card {{
      display: grid;
      grid-template-columns: 44px minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: var(--soft);
    }}
    .repo-icon {{
      width: 44px;
      height: 44px;
      border-radius: 8px;
      object-fit: cover;
      background: #dfe5eb;
      border: 1px solid var(--line);
    }}
    .repo-name {{ font-weight: 750; }}
    .repo-meta {{ color: var(--muted); overflow-wrap: anywhere; font-size: .9rem; }}
    .repo-delete button {{
      color: var(--danger);
      background: var(--danger-bg);
      border-color: #f2b8b5;
    }}
    .repo-delete button:hover {{ background: #ffe3df; }}
    .form-grid {{ display: grid; gap: 12px; }}
    .form-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }}
    .empty {{
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
      padding: 22px;
      text-align: center;
    }}
    @media (max-width: 760px) {{
      main {{ width: min(100% - 24px, 1080px); margin: 22px auto; }}
      .grid, .form-row {{ grid-template-columns: 1fr; }}
      .repo-card {{ grid-template-columns: 40px minmax(0, 1fr); }}
      .repo-delete {{ grid-column: 1 / -1; }}
      .repo-delete button {{ width: 100%; }}
    }}
  </style>
  <script>
    async function copySourceUrl(button, url) {{
      try {{
        await navigator.clipboard.writeText(url);
        button.textContent = "Copied";
      }} catch (error) {{
        const input = document.createElement("input");
        input.value = url;
        document.body.appendChild(input);
        input.select();
        document.execCommand("copy");
        input.remove();
        button.textContent = "Copied";
      }}
      setTimeout(() => button.textContent = "Copy", 1400);
    }}
  </script>
</head>
<body>{body}</body>
</html>""",
        status_code=status_code,
        media_type="text/html",
    )


def _image_media_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _configured_icon_path(icon: str) -> Path | None:
    if not icon:
        return None
    path = Path(icon)
    candidates = [path] if path.is_absolute() else [Path("/app") / path, path]
    return next((candidate for candidate in candidates if candidate.exists()), None)


def _icon_response(icon: bytes, request: Request) -> Response:
    media_type = _image_media_type(icon)
    headers = {
        "Cache-Control": "public, max-age=86400",
        "Content-Length": str(len(icon)),
    }
    if request.method == "HEAD":
        return Response(media_type=media_type, headers=headers)
    return Response(content=icon, media_type=media_type, headers=headers)


def _source_url() -> str:
    return f"{settings.base_url}/{settings.source_slug}.json"


def _source_link() -> str:
    url = _source_url()
    return (
        f'<a class="source-url" href="{escape(url)}"><code>{escape(url)}</code></a>'
        f'<button type="button" onclick="copySourceUrl(this, {escape(json.dumps(url))})">Copy</button>'
    )


def _icon_url_for_repo(repo) -> str:
    if repo.icon.startswith(("http://", "https://")):
        return repo.icon
    return f"{settings.base_url}/icon/{repo.slug}.png"


def _repo_list() -> str:
    if not settings.repositories:
        return '<div class="empty">No repositories configured.</div>'

    rows = []
    for repo in settings.repositories:
        delete_form = ""
        if settings.server_ui_config:
            delete_form = (
                f'<form class="repo-delete" method="post" action="/repositories/{repo.config_index}/delete">'
                f'<input name="csrf_token" type="hidden" value="{escape(csrf_token)}">'
                f'<input name="repo_key" type="hidden" value="{escape(repo.config_key)}">'
                '<button type="submit">Delete</button>'
                "</form>"
            )
        rows.append(
            '<li class="repo-card">'
            f'<img class="repo-icon" src="{escape(_icon_url_for_repo(repo))}" alt="">'
            "<div>"
            f'<div class="repo-name">{escape(repo.name)}</div>'
            f'<div class="repo-meta">{escape(repo.url)}</div>'
            f'<div class="repo-meta">slug: {escape(repo.slug)}</div>'
            "</div>"
            f"{delete_form}"
            "</li>"
        )
    return f'<ul class="repo-list">{"".join(rows)}</ul>'


def _add_repo_form() -> str:
    tint_color = escape(settings.source_tint_color)
    icon = escape(settings.source_icon)
    return f"""
<form class="form-grid" method="post" action="/repositories">
  <input name="csrf_token" type="hidden" value="{escape(csrf_token)}">
  <label><span>GitHub repository URL</span><input name="url" type="url" placeholder="https://github.com/owner/repo" required></label>
  <div class="form-row">
    <label><span>Tint color</span><input name="tint_color" value="{tint_color}" pattern="#[0-9A-Fa-f]{{6}}"></label>
    <label><span>Icon URL or path</span><input name="icon" value="{icon}" placeholder="https://example.com/icon.png"></label>
  </div>
  <button type="submit">Add repository</button>
</form>"""


def _read_config_file() -> dict:
    data = yaml.load(CONFIG_PATH.read_text()) or {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="config.yml must contain a YAML object")
    return data


def _write_config_file(data: dict) -> None:
    try:
        with CONFIG_PATH.open("w", encoding="utf-8") as file:
            yaml.dump(data, file)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write {CONFIG_PATH}: {exc}") from exc


def _reload_runtime() -> None:
    global settings, repositories_by_slug
    reload_config()
    settings = load_settings()
    repositories_by_slug = {repo.slug: repo for repo in settings.repositories}
    source_cache["value"] = None
    source_cache["expires_at"] = 0.0


async def _form_data(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8")
    return {key: values[-1].strip() for key, values in parse_qs(raw).items() if values}


def _redirect_home() -> RedirectResponse:
    return RedirectResponse("/", status_code=303)


def _require_ui_config() -> None:
    if not settings.server_ui_config:
        raise HTTPException(status_code=404, detail="Web UI configuration is disabled")


def _require_csrf(form: dict[str, str]) -> None:
    if not secrets.compare_digest(form.get("csrf_token", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


app = FastAPI(title="GithubStore")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Length"],
)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "source": {
            "name": settings.source_name,
            "slug": settings.source_slug,
            "url": _source_url(),
        },
        "uiConfig": settings.server_ui_config,
        "repositories": [
            {
                "name": repo.name,
                "slug": repo.slug,
                "url": repo.url,
            }
            for repo in settings.repositories
        ],
    }


@app.api_route("/icon.png", methods=["GET", "HEAD"])
async def icon_png(request: Request):
    headers = {
        "Cache-Control": "public, max-age=86400",
        "Content-Length": str(len(DEFAULT_ICON_PNG)),
    }
    if request.method == "HEAD":
        return Response(media_type="image/png", headers=headers)
    return Response(
        content=DEFAULT_ICON_PNG,
        media_type="image/png",
        headers=headers,
    )


@app.api_route("/source-icon.png", methods=["GET", "HEAD"])
async def source_icon_png(request: Request):
    icon_path = _configured_icon_path(settings.source_icon) or next(
        (path for path in SOURCE_ICON_PATHS if path.exists()),
        None,
    )
    if icon_path is None:
        return await icon_png(request)

    return _icon_response(icon_path.read_bytes(), request)


@app.api_route("/icon/{repo_slug}.png", methods=["GET", "HEAD"])
async def repo_icon_png(repo_slug: str, request: Request):
    repo = repositories_by_slug.get(repo_slug)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"Unknown repository: {repo_slug}")
    icon_path = _configured_icon_path(repo.icon)
    if icon_path is None:
        return await source_icon_png(request)
    return _icon_response(icon_path.read_bytes(), request)


@app.get("/")
async def home():
    repo_panel = (
        '<div class="panel">'
        '<div class="panel-head"><h2>Repositories</h2></div>'
        f"{_repo_list()}"
        "</div>"
    )
    config_panel = ""
    if settings.server_ui_config:
        config_panel = (
            '<div class="panel">'
            '<div class="panel-head"><h2>Add Repository</h2></div>'
            f"{_add_repo_form()}"
            "</div>"
        )
    return _html_page(
        "<main>"
        "<header>"
        "<h1>GithubStore</h1>"
        "<p>AltStore source generated from GitHub release IPA assets.</p>"
        f'<div class="source-bar">{_source_link()}</div>'
        "</header>"
        '<section class="grid">'
        f"{repo_panel}"
        f"{config_panel}"
        "</section>"
        "</main>"
    )


@app.post("/repositories")
async def add_repository(request: Request):
    _require_ui_config()
    form = await _form_data(request)
    _require_csrf(form)
    url = form.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="Repository URL is required")

    parsed = urlparse(url if "://" in url else f"https://{url}")
    if parsed.netloc.lower() != "github.com":
        raise HTTPException(status_code=400, detail="Only github.com repository URLs are supported")

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Repository URL must include owner and repo")

    new_repo = {
        "url": parsed.geturl(),
        "tint_color": form.get("tint_color") or settings.source_tint_color,
        "icon": form.get("icon") or settings.source_icon,
    }

    data = _read_config_file()
    repositories = data.setdefault("repositories", [])
    if not isinstance(repositories, list):
        raise HTTPException(status_code=500, detail="repositories must be a YAML list")
    repositories.append(new_repo)
    _write_config_file(data)
    _reload_runtime()
    return _redirect_home()


@app.post("/repositories/{repo_index}/delete")
async def delete_repository(repo_index: int, request: Request):
    _require_ui_config()
    form = await _form_data(request)
    _require_csrf(form)
    data = _read_config_file()
    repositories = data.get("repositories", [])
    if not isinstance(repositories, list):
        raise HTTPException(status_code=500, detail="repositories must be a YAML list")
    if repo_index < 0 or repo_index >= len(repositories):
        raise HTTPException(status_code=404, detail=f"Unknown repository index: {repo_index}")
    if not secrets.compare_digest(form.get("repo_key", ""), repository_config_key(repositories[repo_index])):
        raise HTTPException(status_code=409, detail="Repository changed; refresh and try again")

    repositories.pop(repo_index)
    data["repositories"] = repositories
    _write_config_file(data)
    _reload_runtime()
    return _redirect_home()


@app.get("/source.json")
async def source_json():
    return await named_source_json(settings.source_slug)


@app.get("/{source_slug}.json")
async def named_source_json(source_slug: str):
    if source_slug != settings.source_slug:
        raise HTTPException(status_code=404, detail=f"Unknown source: {source_slug}")

    now = monotonic()
    cached_source = source_cache["value"]
    if cached_source is not None and now < float(source_cache["expires_at"]):
        return JSONResponse(cached_source)

    source = await build_source(settings)
    source_cache["value"] = source
    source_cache["expires_at"] = now + max(settings.source_cache_seconds, 0)
    return JSONResponse(source)


if __name__ == "__main__":
    logger.info("GithubStore source link: %s", _source_url())
    uvicorn.run(app, host=settings.host, port=APP_PORT)
