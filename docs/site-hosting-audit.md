# Project Site Hosting & Domain Audit

Audited from live config only. No configuration changes were made.

Scope
- Included: paceforge, paceforge-users, pepdose, kinklink, wandertold, adventures.
- Excluded: InvestmentPlatform per project constraints.
- Noted only: lingoforge is the known Cloudflare site, but excluded from this inventory.

## Inventory

### 1. WanderTold
- Project: /home/azureuser/projects/wandertold
- Active hosting provider: VM static files + reverse_proxy
- URL type: Custom subpath on Azure hostname
- Current URL: https://claude-dev-vperrod.westeurope.cloudapp.azure.com/wandertold/
- Path structure:
  - /wandertold/ -> static SPA from /srv/wandertold
  - /wandertold/api/* -> 127.0.0.1:8131
  - /wandertold/admin -> forward_auth SSO + strip_prefix /admin -> 127.0.0.1:8132
  - /wandertold/tour-data* -> /srv/wandertold-tours file_server
  - Historical /citywhisper* 301 -> /wandertold*
- Domain permanence risk: LOW. No GitHub Pages dependency; no custom domain registered.
- Misc: wandertold.com is registered but does not point here.

### 2. Koala & Bear Adventures
- Project: /srv/koala-bear (Caddy route /adventures*)
- Active hosting provider: VM static files + reverse_proxy
- URL type: Custom subpath on Azure hostname
- Current URL: https://claude-dev-vperrod.westeurope.cloudapp.azure.com/adventures/
- Path structure:
  - /adventures/api/* -> 127.0.0.1:8130
  - fallback -> /srv/koala-bear file_server with SPA fallback
- Legacy redirects:
  - /media/amsterdam-* -> /adventures/trips/amsterdam-2026-07/*
- Domain permanence risk: LOW. No Pages.

### 3. PaceForge
- Project: /home/azureuser/projects/paceforge
- Active hosting provider: VM runner + Caddy reverse_proxy
- URL type: Custom subpath on Azure hostname
- Current URL: https://claude-dev-vperrod.westeurope.cloudapp.azure.com/paceforge/
- Path structure:
  - /paceforge/* -> 127.0.0.1:8123 (runner.py)
  - health/admin behind same runner
- URL permanence risk: LOW. GitHub account is flagged (ticket 4583559), but Pages/Actions are not needed; /paceforge/ path is custom and remains valid regardless.
- Static docs site: docs-static-vperrod.westeurope.cloudapp.azure.com serves /home/azureuser/projects/paceforge/_site
- Caddyfile snippet detected for docs static host: /home/azureuser/projects/paceforge/ops/Caddyfile.paceforge-static

### 4. PaceForge users (multi-user)
- Project root: /home/azureuser/projects/paceforge-users/<name>
- Active hosting provider: VM runner + Caddy reverse_proxy
- URL type: Custom subpath on Azure hostname
- Current URL: https://claude-dev-vperrod.westeurope.cloudapp.azure.com/pf/nunoduarte/
- Path structure:
  - /pf/nunoduarte/* -> 127.0.0.1:8124
- URL permanence risk: LOW. Instance-per-user model; no Pages dependency.

### 5. Pepdose
- Project: /home/azureuser/projects/pepdose
- Active hosting provider: VM static file_server (under /srv/pepdose) via Caddy
- URL type: Custom subpath on Azure hostname; retains GB-era base path
- Current URL: https://claude-dev-vperrod.westeurope.cloudapp.azure.com/pepdose/
- Path structure:
  - /pepdose/* -> root /srv/pepdose + SPA fallback + cache rules
  - /assets/* Cache-Control: public, max-age=31536000, immutable
  - non-assets: no-cache
- URL permanence risk: MEDIUM. Custom path persists after Pages, but this is not a custom domain or subdomain.

### 6. KinkLink
- Projects/repos observed:
  - /home/azureuser/projects/kinklink-real
  - /home/azureuser/projects/lingoforge/KinkLink_Frontend
  - /home/azureuser/projects/lingoforge/KinkLink_Admin
  - /home/azureuser/projects/kinklink-video-kit
  - /home/azureuser/projects/kinklink-audit-report
- Active hosting provider: VM static file_server + reverse_proxy
- URL type: Custom subpaths on Azure hostname; replaces GitHub Pages
- Current URLs:
  - FE: /kl* -> /srv/kl-portals/fe-dist
  - admin: /kl-admin* -> /srv/kl-portals/admin-dist
  - design: /kl-design* -> /srv/kl-portals/design
  - API/WebSocket: /kl-api/*, /socket.io* -> 127.0.0.1:8086 (Origin rewritten to https://vperrod.github.io)
  - audit report: /audit* -> /srv/kinklink-audit with forward_auth; exempts manifest/icons for installability
- Path structure notes:
  - Portal rebuilds use matching --base flags so Pages-equivalent paths remain exact.
  - audit console uses client-side encryption replaced by server-side forward_auth.
- Domain permanence risk: MEDIUM. Web deployments now run from VM; admin/FE bundles rely on Caddy paths, not a custom domain.
- Backup/origin: GitHub origin remains; audit repo is private and Pages was deconfigured, so it would not recreate itself automatically.

## Migration flags

Flagged GitHub Pages-era dependencies still present as rollback/compat surfaces:
- paceforge README lists Pages as the rollback path for /paceforge/ on runner failure.
- KinkLink API Origin rewrite assumes https://vperrod.github.io, meaning CORS/socket allowlists still reference GitHub Pages.

## Permanence summary

- LOW risk: wandertold, adventures, paceforge, paceforge-users
- MEDIUM risk: pepdose, kinklink
- EXCLUDED: lingoforge (Cloudflare), InvestmentPlatform
