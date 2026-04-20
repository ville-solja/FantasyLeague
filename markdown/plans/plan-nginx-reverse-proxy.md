# Plan: Fix Nginx Reverse Proxy for External Access

## Context

The app is hosted at `fantasyleague.lehtipuu.lan` (LAN machine running Docker + Nginx). The public domain `fantasyleague.makkis.life` points to the router's external IP, which port-forwards to that machine. The site works locally but is inaccessible from outside the LAN.

**Root cause:** Nginx is issuing an HTTP redirect to `http://fantasyleague.lehtipuu.lan/...` instead of transparently proxying the request. External browsers follow the redirect but cannot resolve the `.lan` hostname, so the page never loads. The fix is entirely in the Nginx config on the host machine — no code changes to the app are needed.

The app is already correctly configured for reverse proxy use:
- Uvicorn runs with `--proxy-headers --forwarded-allow-ips "*"` (Dockerfile CMD)
- `HTTPS_ONLY` env var controls the `Secure` cookie flag (defaults `false`, should be `true` once HTTPS works)

---

## The Fix — Nginx Config on `fantasyleague.lehtipuu.lan`

Replace the current Nginx site config (typically `/etc/nginx/sites-available/fantasyleague`) with:

```nginx
# Redirect plain HTTP → HTTPS
server {
    listen 80;
    server_name fantasyleague.makkis.life;
    return 301 https://$host$request_uri;
}

# HTTPS — proxy to the Docker container
server {
    listen 443 ssl;
    server_name fantasyleague.makkis.life;

    ssl_certificate     /etc/letsencrypt/live/fantasyleague.makkis.life/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/fantasyleague.makkis.life/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

Key points:
- `proxy_pass http://127.0.0.1:8000` — forwards to the Docker container, never redirects to the `.lan` hostname
- `proxy_set_header Host $host` — passes `fantasyleague.makkis.life` as the Host header so the app sees the real domain
- `X-Forwarded-Proto $scheme` — tells the app it's receiving HTTPS so session cookies get the Secure flag

If no SSL cert exists yet, obtain one first:
```bash
sudo certbot --nginx -d fantasyleague.makkis.life
```

---

## App-side change — set `HTTPS_ONLY=true` in `.env`

Once HTTPS is working, uncomment this line in the `.env` file on the host:

```env
HTTPS_ONLY=true
```

Then restart the container:
```bash
docker compose restart
```

This enables the `Secure` flag on session cookies so they are never sent over plain HTTP.

---

## Checklist

| Step | Where | Action |
|---|---|---|
| 1 | Router | Confirm ports 80 and 443 are forwarded to the LAN IP of `fantasyleague.lehtipuu.lan` |
| 2 | DNS | Confirm `fantasyleague.makkis.life` A record points to the router's external IP |
| 3 | Host machine | Obtain/verify SSL cert with `certbot` |
| 4 | Host machine | Replace Nginx site config with the config above |
| 5 | Host machine | `sudo nginx -t && sudo systemctl reload nginx` |
| 6 | Host machine | Set `HTTPS_ONLY=true` in `.env`, then `docker compose restart` |

---

## Verification

1. From an external network (phone on mobile data): open `https://fantasyleague.makkis.life` — site loads
2. `curl -I https://fantasyleague.makkis.life` returns `200 OK` (not a 3xx to a `.lan` address)
3. Log in and verify session persists (cookie is set with `Secure; SameSite=Lax`)
4. Local access via `http://fantasyleague.lehtipuu.lan:8000` still works for development
