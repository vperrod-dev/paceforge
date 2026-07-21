
## 2026-07-21 — portal Garmin login saga
- Victor cannot/won't use a terminal: every operator flow must live in the portal (login page, Garmin connect, MFA). Build UI mechanisms, don't prescribe CLI commands.
- No basic-auth prompts, ever — they also silently break same-origin fetch() flows. Cookie-session login page instead.
- "Wait N hours and retry" is not a fix for Victor — find the mechanism (per-IP 429 → different egress via WARP proxy) and kill the root cause.
- Never restart a stateful service while a user flow may be in flight — the runner restart destroyed his in-memory MFA session mid-login. Deploy hot paths between flows, or announce first.
- Browser autofill puts the SITE password into any password field on the page (sent the portal password to Garmin → 401). autocomplete=new-password + delayed blanking + explicit warning.
