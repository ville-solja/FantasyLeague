# 16. Version Visibility

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
