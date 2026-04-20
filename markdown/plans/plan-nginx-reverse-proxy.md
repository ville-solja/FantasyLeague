# Plan: Fix Traefik Reverse Proxy for External Access

## Context

The app is hosted at `fantasyleague.lehtipuu.lan` (LAN machine running Docker + Traefik). The public domain `fantasyleague.makkis.life` points to the router's external IP, which port-forwards to that machine. The site works locally but is inaccessible from outside the LAN.

**Root cause — two compounding issues:**

1. **Traefik version mismatch.** The static config (`traefik.toml`) is written in **v1 format** (`[backends]`, `[frontends]`). The docker-compose labels use **v2 format** (`traefik.http.routers`, `traefik.http.services`). Whichever Traefik version is actually running, one half of the config is silently ignored.

2. **Wrong backend port in the v1 static config.** The v1 backend URL is `http://fantasyleague.lehtipuu.lan` (port 80), but the container listens on port **8000**.

The fix standardises on **Traefik v2** (matching the docker-compose label format already in use) and adds the external HTTPS router via labels only — no static backend/frontend config needed.

The app itself requires no changes:
- Uvicorn already runs with `--proxy-headers --forwarded-allow-ips "*"`
- `HTTPS_ONLY` env var controls the `Secure` cookie flag (set to `true` once HTTPS works)

---

## Original Configuration

### `docker-compose.yml` (on host)
```yaml
services:
  fantasyleague:
    image: ghcr.io/ville-solja/fantasyleague:b06e0c4
    container_name: fantasyleague

    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.fantasy.rule=Host(`fantasyleague.lehtipuu.lan`)"
      - "traefik.http.routers.fantasy.entrypoints=web"
      - "traefik.http.services.fantasy.loadbalancer.server.port=8000"

    restart: unless-stopped
    networks:
      - proxy

networks:
  proxy:
    external: true
```

**Problems:** only routes the internal `.lan` hostname; only HTTP (`web` entrypoint); no HTTPS or external domain.

### `traefik.toml` (static config — v1 format, conflicts with v2 labels)
```toml
debug = false
checkNewVersion = true
logLevel = "ERROR"
defaultEntryPoints = ["https", "http"]

[traefikLog]
  filePath = "/var/log/traefik.log"

[entryPoints]
  [entryPoints.http]
  address = ":80"
    [entryPoints.http.redirect]
    entryPoint = "https"
  [entryPoints.https]
  address = ":443"
    [entryPoints.https.tls]

[backends]
  [backend.fantasyleague]
    [backends.fantasyleague.servers.server0]
      url="http://fantasyleague.lehtipuu.lan"   # ← wrong: port 80, not 8000

[frontends]
  [frontends.fantasyleague]
    entryPoints = ["http", "https"]
    backend = "fantasyleague"
    passHostHeader = true

    [frontends.fantasyleague.routes.fantasyleague1]
    rule = "Host:fantasyleague.makkis.life"
```

**Problems:** v1 format is ignored by a v2 Traefik instance; backend URL uses wrong port.

---

## Diff — `docker-compose.yml`

```diff
 services:
   fantasyleague:
     image: ghcr.io/ville-solja/fantasyleague:b06e0c4
     container_name: fantasyleague

     labels:
       - "traefik.enable=true"
-      - "traefik.http.routers.fantasy.rule=Host(`fantasyleague.lehtipuu.lan`)"
-      - "traefik.http.routers.fantasy.entrypoints=web"
-      - "traefik.http.services.fantasy.loadbalancer.server.port=8000"
+      # Local LAN access (HTTP)
+      - "traefik.http.routers.fantasy-lan.rule=Host(`fantasyleague.lehtipuu.lan`)"
+      - "traefik.http.routers.fantasy-lan.entrypoints=web"
+      - "traefik.http.routers.fantasy-lan.service=fantasy"
+      # External access — HTTP → HTTPS redirect
+      - "traefik.http.routers.fantasy-http.rule=Host(`fantasyleague.makkis.life`)"
+      - "traefik.http.routers.fantasy-http.entrypoints=web"
+      - "traefik.http.routers.fantasy-http.middlewares=https-redirect"
+      # External access — HTTPS with Let's Encrypt
+      - "traefik.http.routers.fantasy-https.rule=Host(`fantasyleague.makkis.life`)"
+      - "traefik.http.routers.fantasy-https.entrypoints=websecure"
+      - "traefik.http.routers.fantasy-https.tls=true"
+      - "traefik.http.routers.fantasy-https.tls.certresolver=letsencrypt"
+      - "traefik.http.routers.fantasy-https.service=fantasy"
+      # Shared service definition
+      - "traefik.http.services.fantasy.loadbalancer.server.port=8000"
+      # Redirect middleware
+      - "traefik.http.middlewares.https-redirect.redirectscheme.scheme=https"
+      - "traefik.http.middlewares.https-redirect.redirectscheme.permanent=true"

     restart: unless-stopped
+    environment:
+      - HTTPS_ONLY=true
     networks:
       - proxy

 networks:
   proxy:
     external: true
```

---

## Diff — `traefik.toml` (static config)

Remove the v1 `[backends]` and `[frontends]` blocks entirely. They are ignored by Traefik v2 and conflict conceptually with label-based routing. The entrypoints and Let's Encrypt resolver must be declared in the static config:

```diff
 debug = false
 checkNewVersion = true
 logLevel = "ERROR"
-defaultEntryPoints = ["https", "http"]

 [traefikLog]
   filePath = "/var/log/traefik.log"

 [entryPoints]
   [entryPoints.http]
   address = ":80"
-    [entryPoints.http.redirect]
-    entryPoint = "https"
   [entryPoints.https]
   address = ":443"
-    [entryPoints.https.tls]

-[backends]
-  [backend.fantasyleague]
-    [backends.fantasyleague.servers.server0]
-      url="http://fantasyleague.lehtipuu.lan"
-
-[frontends]
-  [frontends.fantasyleague]
-    entryPoints = ["http", "https"]
-    backend = "fantasyleague"
-    passHostHeader = true
-
-    [frontends.fantasyleague.routes.fantasyleague1]
-    rule = "Host:fantasyleague.makkis.life"

+[certificatesResolvers]
+  [certificatesResolvers.letsencrypt.acme]
+    email = "your-email@example.com"
+    storage = "/letsencrypt/acme.json"
+    [certificatesResolvers.letsencrypt.acme.httpChallenge]
+      entryPoint = "http"

 [providers]
   [providers.docker]
     network = "proxy"
     exposedByDefault = false
```

> **Note:** The `[providers.docker]` block must exist in `traefik.toml` for Traefik v2 to read container labels at all. If it is missing, add it. The `letsencrypt/acme.json` path must be a bind-mounted volume on the Traefik container.

---

## Recommended `docker-compose.yml` (full, after changes)

```yaml
services:
  fantasyleague:
    image: ghcr.io/ville-solja/fantasyleague:b06e0c4
    container_name: fantasyleague

    labels:
      - "traefik.enable=true"
      # Local LAN access (HTTP)
      - "traefik.http.routers.fantasy-lan.rule=Host(`fantasyleague.lehtipuu.lan`)"
      - "traefik.http.routers.fantasy-lan.entrypoints=web"
      - "traefik.http.routers.fantasy-lan.service=fantasy"
      # External HTTP → HTTPS redirect
      - "traefik.http.routers.fantasy-http.rule=Host(`fantasyleague.makkis.life`)"
      - "traefik.http.routers.fantasy-http.entrypoints=web"
      - "traefik.http.routers.fantasy-http.middlewares=https-redirect"
      # External HTTPS with Let's Encrypt
      - "traefik.http.routers.fantasy-https.rule=Host(`fantasyleague.makkis.life`)"
      - "traefik.http.routers.fantasy-https.entrypoints=websecure"
      - "traefik.http.routers.fantasy-https.tls=true"
      - "traefik.http.routers.fantasy-https.tls.certresolver=letsencrypt"
      - "traefik.http.routers.fantasy-https.service=fantasy"
      # Service
      - "traefik.http.services.fantasy.loadbalancer.server.port=8000"
      # Middleware
      - "traefik.http.middlewares.https-redirect.redirectscheme.scheme=https"
      - "traefik.http.middlewares.https-redirect.redirectscheme.permanent=true"

    environment:
      - HTTPS_ONLY=true

    restart: unless-stopped
    networks:
      - proxy

networks:
  proxy:
    external: true
```

---

## Checklist

| Step | Where | Action |
|---|---|---|
| 1 | Router | Confirm ports 80 and 443 are forwarded to the LAN IP of `fantasyleague.lehtipuu.lan` |
| 2 | DNS | Confirm `fantasyleague.makkis.life` A record points to the router's external IP |
| 3 | Traefik static config | Remove `[backends]` / `[frontends]` blocks; add `[certificatesResolvers]` and `[providers.docker]` |
| 4 | Traefik container | Ensure `/letsencrypt/acme.json` is a bind-mounted volume; port 443 is exposed |
| 5 | Host machine | Apply updated `docker-compose.yml` labels |
| 6 | Host machine | `docker compose up -d --force-recreate` |

---

## Verification

1. From an external network (phone on mobile data): open `https://fantasyleague.makkis.life` — site loads with valid HTTPS cert
2. `curl -I http://fantasyleague.makkis.life` returns `301` redirect to `https://`
3. `curl -I https://fantasyleague.makkis.life` returns `200 OK`
4. Log in and verify session persists (cookie has `Secure; SameSite=Lax`)
5. Local access via `http://fantasyleague.lehtipuu.lan` still works
