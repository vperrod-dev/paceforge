# Decision: Custom Domain vs *.pages.dev for Project Sites

Status: Proposed  
Date: 2026-07-30  
Members: Hermes Agent (auto-decomposer / t_a8618198)  
Related: [site-hosting-audit](./site-hosting-audit.md), [gh-pages-migration-options](../lingoforge/docs/gh-pages-migration-options.md)

## Goal

Align project hosting with a permanent, branded URL strategy that does not rely on
`*.pages.dev` as a canonical hostname. This supports the broader migration off
GitHub Pages/Actions, respects the constraint that public URLs must live on the
Azure cloud hostname, and keeps deployment ownership inside the existing VM/Caddy
infrastructure.

## Constraint summary

- No configuration changes or deployments from this task; this decision only.
- Cost-sensitive: prefer reusing existing infra; no new paid subscriptions.
- Azure cloud hostname is the authoritative public surface.
- Wildcard DNS is not used.
- InvestmentPlatform is explicitly out of scope.

## Current posture (from live audit)

| Site / Surface | Current URL type | Pages / Actions presence | Permanence risk |
|---|---|---|---|
| wandertold | Azure subpath `/wandertold/` | None | LOW |
| adventures | Azure subpath `/adventures/` | None | LOW |
| paceforge | Azure subpath `/paceforge/` | None (runner + Caddy) | LOW |
| paceforge-users | Azure subpath `/pf/<user>/` | None | LOW |
| pepdose | Azure subpath `/pepdose/` | None (Caddy static) | MEDIUM |
| kinklink FE/admin | Azure subpath `/kl*`, `/kl-admin*` | None live; Pages-era URLs still bookmarked | MEDIUM |
| lingoforge | GitHub Pages active | Active deploy workflow | HIGH |
| KinkLink production | kinklink.ie | None | LOW |

All sites except lingoforge are already served from the VM through Caddy under
paths on the Azure cloud hostname.

## Options

### Option A — Retain `*.pages.dev` canonical links

Pros:
- Zero additional cost; no deploy pipeline changes for the few remaining sites.
- Quickest path for lingoforge if time is constrained.

Cons:
- Exposes an unofficial GitHub-owned domain in bookmarks, screenshots, and SEO.
- Vendor dependency: the subdomain disappears if Pages is decommissioned or the
  account loses access.
- Does not match project guidance that public URLs should live on the Azure cloud
  hostname.
- Shareability and brand trust suffer; search engines may split signals between
  `.pages.dev` and custom domains.
- Harder to issue permanent 301s from `*.pages.dev` back to the canonical Azure
  subpath; GitHub does not surface redirect controls for the `.pages.dev` URL.

### Option B — Custom domain under the Azure cloud hostname (preferred)

Pros:
- Canonical user-facing URL is fully inside the Azure hostname:
  `claude-dev-vperrod.westeurope.cloudapp.azure.com/<site>/`.
- No new vendor contract or cloud spend; Caddy already terminates TLS and serves
  all existing routes.
- Permanent redirects from any public `*.pages.dev` reference are achievable at the
  reverse-proxy layer.
- Branding and SEO are clean: one canonical origin with no duplicate surfaces.
- Operational model is unchanged for sites already deployed under Caddy.

Cons:
- lingoforge must be re-homed from GitHub Pages; requires a deploy-path change
  plus build artifact delivery to `/srv/lingoforge` (or an equivalent static root).
- Preview/branch deploys require a separate routing convention if those are needed.

### Option C — Custom domain via a separate registrar/CDN (Cloudflare Pages)

Pros:
- Custom domain is possible; `pages.dev` URLs can be hidden behind it.
- Native branch isolation and preview URLs.

Cons:
- Public path still relies on Pages hostname underneath if Caddy is not the
  TLS terminator.
- Adds a second vendor layer in front of a low-traffic static site whose entire
  existing infra is already on this VM.
- Wildcard DNS constraints still apply, but introduces additional DNS records
  for a domain Caddy already serves.

## Per-site recommendations

### lingoforge — Migrate to self-hosted Caddy *(Option B)*
- Build locally or in GitHub Actions; publish `dist/` to `/srv/lingoforge` on the VM.
- Add a Caddy route for `/lingoforge*` (or return to a `/lingoforge` path if one
  existed historically).
- Issue 301 redirects from any `*.pages.dev` reference to the Azure subpath.
- Deactivate the GitHub Pages workflow to prevent accidental republishing.

### kinklink FE / Admin — Keep Azure `/kl*` and `/kl-admin*` canonical *(Option B)*
- Production already runs on `kinklink.ie`; the `/kl*` paths are dev/preview
  surfaces and can remain as Azure subpaths.
- Do not re-publish to Pages. If the Pages workflow still exists in a deploy repo,
  gate it behind removal or manual `workflow_dispatch` only, to remove accidental
  publishes.

### pepdose — Retain current setup *(Option B, already in place)*
- Served from `/srv/pepdose` under `/pepdose/` on the Azure hostname.
- No Pages dependency; no change required.

### wandertold, adventures, paceforge, paceforge-users — No change *(Option B, already in place)*
- All already live under Azure subpaths with no Pages/Actions dependency.
- No change required.

### KinkLink production — Already resolved
- `kinklink.ie` is a registered custom domain. Canonical production is independent
  of this decision.

## Implementation steps (approval required)

1. lingoforge: reverse the Pages workflow; add a `deploy.sh` (or equivalent) that
   copies the Vite build output to `/srv/lingoforge` on the VM.
2. lingoforge: add a Caddy subpath route ensuring TLS + SPA fallback for `/lingoforge*`.
3. lingoforge: add a permanent redirect `redir /lingoforge* https://<azure host>/lingoforge* permanent`
   before `file_server` to absorb stale `*.pages.dev` links once found.
4. lingoforge: confirm `vite.config.{js,ts}` `base` is `/lingoforge/` so relative
   asset paths resolve when hosted under a subpath.
5. kinklink FE/admin deploy repos: remove or disable the GitHub Pages deploy
   workflow; confirm the `/srv/kl-portals/*` static roots remain authoritative.
6. All impacted README/CLAUDE.md files: update "Canonical URL" / "Deploy URL"
   lines to point at the Azure subpath.

## Decision

**Approve Option B (custom domain / Azure cloud hostname).**

Rationale:
- It is the only option that satisfies the memory/project rule that public URLs
  must live on the Azure cloud hostname.
- It introduces no new vendor or recurring cost.
- It provides full control over redirects, TLS, and canonical tags.
- It closes `*.pages.dev` leakage in user-facing links and SEO metadata.
