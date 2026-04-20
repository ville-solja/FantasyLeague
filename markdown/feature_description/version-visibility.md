# Version Visibility

Every page shows a faint version string in the bottom-right corner so that bug reports can be tied to a specific build without server access.

---

## How it works

Two environment variables control the displayed version. Their values are served through the existing `/config` endpoint and rendered by the frontend after the initial config fetch. `APP_VERSION` always has a value — if the env var is not set the backend defaults it to the literal string `"APP_VERSION"`, so the badge is always visible and immediately identifies which variable to configure.

| Env var | Purpose |
|---|---|
| `APP_VERSION` | Docker image SHA or short commit hash — set by CI on every build |
| `APP_RELEASE` | Human-readable release tag (e.g. `v1.2.0`) — set only in production |

When only `APP_VERSION` is set the badge shows the SHA alone. When both are set it shows `v1.2.0 · abc1234`.

## Endpoints

### `GET /config`
Returns `app_version` and `app_release` fields alongside existing config (`token_name`, `initial_tokens`). `app_version` is always non-empty (defaults to `"APP_VERSION"` when the env var is unset). `app_release` is an empty string when not set and is omitted from the displayed string.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `APP_VERSION` | `"APP_VERSION"` | Image SHA injected by CI — shown in test and prod; falls back to its own name when unset |
| `APP_RELEASE` | *(empty)* | Release tag — shown in prod alongside `APP_VERSION` |

## Build pipeline

`APP_VERSION` is baked in at image build time:

```
GitHub Actions  →  docker build --build-arg APP_VERSION=$(git rev-parse --short HEAD)
Dockerfile      →  ARG APP_VERSION / ENV APP_VERSION=${APP_VERSION}
backend         →  os.getenv("APP_VERSION", "APP_VERSION")
GET /config     →  { "app_version": "abc1234" }
frontend        →  badge textContent = "abc1234"
```

`APP_RELEASE` is set as a deploy-time env var (e.g. in `docker-compose.yml`) rather than a build arg, since it identifies a release rather than an image.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
