# Plan: Version Visibility

## Context

When debugging issues in test or production it is useful to know exactly which build is running. This feature adds a faint version string to every page so that bug reports can be tied to a specific image or release without requiring server access. In the test environment the Docker image SHA is sufficient; in production the release tag is also shown. Both values are injected as environment variables at deploy time — no code change is needed to update the displayed version.

## User Stories

### 16.1 View Build Version on Every Page
**User story**
As a user reporting a bug, I want to see a faint version identifier on every page so that I can include the exact build in my report without needing to know anything about the server.

**Acceptance criteria**
- A version string is visible on every page in a small, low-contrast style that does not compete with the UI
- The string is present regardless of login state
- If `APP_VERSION` is not set the badge shows the literal text `APP_VERSION` as a fallback so that the element is always visible and it is immediately clear which variable to configure

---

### 16.2 Environment-Aware Version Display
**User story**
As an operator, I want the version display to show the image SHA in test and both the image SHA and release tag in production, so that the right level of detail is available in each environment.

**Acceptance criteria**
- Setting only `APP_VERSION` (image SHA) displays that value alone
- Setting both `APP_VERSION` and `APP_RELEASE` displays both values (e.g. `v1.2.0 · b06e0c4`)
- Values are served from the existing `/config` endpoint so no additional HTTP request is needed
- `.env.example` documents both variables
- The value of `APP_VERSION` is injected by CI as a Docker build argument (`--build-arg APP_VERSION=<git-sha>`) and passed through to the container via `ENV APP_VERSION` in the Dockerfile, so no manual step is required after a build

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/main.py` | Add `APP_VERSION` and `APP_RELEASE` env var reads; include them in the `/config` response |
| `frontend/app.js` | Read version fields from `/config` response; render faint version string |
| `frontend/index.html` | Add a `<div id="version-badge">` element in the page footer area |
| `frontend/style.css` | Add `.version-badge` styles (small, low-contrast, fixed position) |
| `.env.example` | Document `APP_VERSION` and `APP_RELEASE` |

### Step 1 — Expose version in `/config`

Locate the `GET /config` endpoint in `backend/main.py`. Read two new env vars at module level. `APP_VERSION` defaults to its own name so the badge is always visible and self-documenting when the variable has not been configured:

```python
_APP_VERSION = os.getenv("APP_VERSION", "APP_VERSION")
_APP_RELEASE = os.getenv("APP_RELEASE", "")
```

Add them to the dict returned by the `/config` handler:

```python
"app_version": _APP_VERSION,
"app_release": _APP_RELEASE,
```

### Step 2 — Render the version badge in the frontend

In `frontend/app.js`, after the `/config` fetch resolves, build the version string and populate the badge. Because `app_version` is always non-empty (the backend defaults it to `"APP_VERSION"`), the badge is always shown; the hide branch is only a safety net:

```js
const parts = [];
if (cfg.app_release) parts.push(cfg.app_release);
if (cfg.app_version) parts.push(cfg.app_version);
const versionEl = document.getElementById("version-badge");
if (versionEl) {
  if (parts.length) {
    versionEl.textContent = parts.join(" · ");
    versionEl.style.display = "";
  } else {
    versionEl.style.display = "none";
  }
}
```

### Step 3 — Add the badge element to the HTML

In `frontend/index.html`, add before `</body>`:

```html
<div id="version-badge" class="version-badge" style="display:none"></div>
```

### Step 4 — Style the badge

In `frontend/style.css`, add:

```css
.version-badge {
  position: fixed;
  bottom: 6px;
  right: 10px;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.25);
  pointer-events: none;
  user-select: none;
  z-index: 9999;
}
```

### Step 5 — Wire the value from CI build to the running container

The injection chain is:

```
GitHub Actions → docker build --build-arg APP_VERSION=$(git rev-parse --short HEAD)
                 ↓
Dockerfile      ENV APP_VERSION=${APP_VERSION}
                 ↓
backend/main.py  os.getenv("APP_VERSION", "APP_VERSION")
                 ↓
GET /config      { "app_version": "abc1234", ... }
                 ↓
frontend/app.js  versionEl.textContent = "abc1234"
```

In the **Dockerfile** add (before the `CMD` line):

```dockerfile
ARG APP_VERSION
ENV APP_VERSION=${APP_VERSION}
```

In the **GitHub Actions** workflow (`docker build` step) pass the arg:

```yaml
- name: Build image
  run: |
    docker build \
      --build-arg APP_VERSION=$(git rev-parse --short HEAD) \
      -t ghcr.io/${{ github.repository }}:latest .
```

For `APP_RELEASE` in production, set it as a deploy-time env var (e.g. in `docker-compose.yml` or the hosting platform) rather than a build arg, since it is a property of the release, not the image.

### Step 6 — Document env vars in `.env.example`

Add two commented lines near the bottom of `.env.example`:

```env
# Build version displayed faintly on every page (set by CI to the image SHA)
# APP_VERSION=
# Release tag displayed alongside APP_VERSION in production (e.g. v1.2.0)
# APP_RELEASE=
```

---

## Verification

- Set `APP_VERSION=test-sha` in `.env`, restart the app, open any page — version string `test-sha` appears faintly in the bottom-right corner
- Set both `APP_VERSION=abc1234` and `APP_RELEASE=v1.0.0`, restart — string reads `v1.0.0 · abc1234`
- Remove both vars (or leave empty), restart — badge shows the literal text `APP_VERSION` as a fallback; no empty string or "undefined" visible
- Verify the badge is present on every tab (My Team, Leaderboard, Schedule, etc.) without reloading
- Verify the badge does not overlap interactive UI elements at common screen widths (1280px, 375px mobile)
