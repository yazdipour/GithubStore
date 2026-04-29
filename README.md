# GithubStore

<img src="./imgs/ShaFace.png" alt="GithubStore icon" height="270" />

Self-hosted AltStore / SideStore / LiveContainer source generated from GitHub repositories.

GithubStore reads each configured repository's latest GitHub release and adds the first suitable `.ipa` release asset to one combined source.

> [!NOTE]
> If you are looking to have an IPA repository from Telegram channels, check out [TeleStore](https://github.com/yazdipour/TeleStore).

## Quick Setup

1. Create `docker-compose.yml`:

```yaml
services:
  app:
    image: ghcr.io/yazdipour/githubstore:latest
    ports:
      - "8080:8080" # if port 8080 is already in use, change the left side to an available port, e.g. "8081:8080" and do not forget to update the base_url in config.yml accordingly.
    volumes:
      - ./config.yml:/app/config.yml
    restart: unless-stopped
```

2. Create `config.yml` (or copy from `config.example.yml`).
3. Edit `config.yml` and add one or more GitHub repository URLs:


```yaml
server:
  base_url: http://localhost:8080 # set to the reachable URL if accessing from another device
  ui_config: false # set to true to enable the web UI for adding/deleting repositories

github:
  token: "" # optional, or set GITHUB_TOKEN. Used to increase GitHub API rate limits from 60 to 5000 requests per hour.

source:
  name: GithubStore
  slug: source
  subtitle: GitHub release IPA source
  description: Self-hosted AltStore source generated from GitHub release IPA assets.
  tint_color: "#24292F"
  cache_seconds: 600

repositories: []
```

4. Add repository:

Adding through UI:

By setting `server.ui_config: true` in `config.yml`, you can access the web UI at `http://localhost:8080/` to add and delete repositories.

> [!CAUTION]
> The UI is very basic and does not have any authentication, so only enable it in a secure environment.
> 
> We recommend after adding repositories via the UI, to disable it again by setting `ui_config: false` and restarting the server.

Or Add URLs under `repositories` inside `config.yml`:

```yaml
repositories:
  - url: https://github.com/example/example-ios-app # Address of GitHub repository with releases containing .ipa assets
    name: Example App
    slug: example-app
    tint_color: "#24292F"
    icon: imgs/ShaFace-small.png

  - url: https://github.com/example/another-ios-app
    name: Another App
    slug: another-app
    tint_color: "#f50d0d"
    icon: https://img.icons8.com/dusk/1200/youtube-play.jpg
```

5. Start the server:

```bash
docker compose up -d
```

6. Add the source URL in AltStore, SideStore, or LiveContainer:

```text
http://localhost:8080/source.json
```

On an iPhone on the same Wi-Fi, set `server.base_url` to the reachable LAN URL. For example, if your computer LAN IP is `192.168.1.50` and Docker maps host port `8080`, use `http://192.168.1.50:8080/source.json`.

## How IPA Selection Works

Each repository contributes at most one app. GithubStore calls GitHub's latest release API for each repository and chooses one `.ipa` asset from that release. If a release contains multiple `.ipa` files, debug or symbol-looking files are deprioritized and the largest remaining IPA is used.

If a repository has no latest release or no `.ipa` asset on that release, the source includes a placeholder entry describing the error and no installable versions for that app.

## Developer Setup

Use the local build when changing source:

```bash
cp config.example.yml config.yml
docker compose -f docker-compose.local.yml up --build
```

The generated source is also available at `/source.json`; if you change `source.slug`, it is additionally available at `/{source.slug}.json`.

## License

MIT License. See [LICENSE](./LICENSE) for details.
