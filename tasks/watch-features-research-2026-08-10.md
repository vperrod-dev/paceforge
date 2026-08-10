# Feature opportunities research — 2026-08-10

Sweep of HN, GitHub (awesome-garmin, topic:connect-iq), Runalyze/Runna/intervals.icu
feature-envy threads. Reddit unreachable from VM (403) — signal came via HN/web.
Firecrawl account out of credits (every firecrawl call errored).

## Key insight
The "AI coach on Garmin data" space is crowded but shallow: dozens of repos do
sync → LLM → text report (what PaceForge already surpasses). Almost NOBODY
pushes workouts back to the watch, and working CIQ fields are rare (SDK/auth
pain is the moat). The differentiated frontier = closed-loop watch push +
on-watch surfaces — exactly where we already sit.

## Ranked opportunities (deduped vs what we have)

1. **Same-day workout rewrite** (M) — "not feeling 100% / only have 45 min" →
   engine compresses/downgrades today's session preserving stimulus intent →
   pushes revised workout to watch within the 15-min sync window. Most-repeated
   wish everywhere (PacePartner Show HN exists just to ADVISE this; Runna just
   shipped "Not Feeling 100%" to press coverage). Nobody does the push-back.
2. **Proactive coach** (S) — morning readiness verdict + exception alerts
   (HRV baseline deviation, resting-HR creep, recovery-HR trend break) pushed
   via Telegram instead of portal-pull. AthleteData Show HN pattern; we have
   the bot + analyses already.
3. **Independent race prognosis** (M) — Runalyze-style per-activity effective
   VO2max + "shape" correction (weekly km + long-run distribution) → defensible
   HM target for Sept 20; feeds the planned race-day projection field.
   (Garmin forum consensus: Runalyze forecast beats Garmin's.)
4. **Virtual partner / ghost field** (M) — race your previous attempt or the
   coach's target splits, ahead/behind live; engine serves the ghost over the
   existing HTTP-fetch pattern. Proven demand (VirtualPartner, 4caster, HMFields).
5. **"Stimulus achieved" field** (S/M) — live TRIMP-so-far vs the session's
   intended load ("82% of planned stimulus") — objective early-stop permission.
6. **Plan-diff approval queue** (M) — chat coach proposes per-day plan diffs,
   nothing changes until tapped Accept (steal idaten's ADR-0006 UX).
7. **MCP server over the engine** (S) — get_activities/get_plan/propose_workout/
   push_workout → any Claude session becomes a coach console. Cheapest path to #6.
8. **Aerobic-decoupling alert field** (M) — live HR-drift vs first-half EF
   ("drifting +6% — back off"); computed on-watch, no product has it live.
9. **HYROX per-station trends** (S) — extend the planned station screen with
   engine-side week-over-week station analytics (multisports.creatness.studio
   validation).
10. **Shoe mileage + retirement alerts** (S) — Telegram at ~700 km.
11. **Consistency heatmap** (S) — GitHub-style 52-week load grid (git-sweaty:
    258★ for a trivial viz — people love it).
12. **Plan .ics feed + ZWO export** (S) — phone calendar shows today's session;
    Zwift-format export for Bike.
13. **Long-term health panels** (S) — steal garmin-grafana's (3391★) panel
    catalog: HRV vs baseline band, resting-HR trend, sleep stages.
14. **Scale ingestion** (S, only if BLE scale exists) — weight/w-kg trend to race.

## Sources
GarminDB HN 42912515 · AthleteData 47865161 · PacePartner 47336248 ·
github: idaten, claude-coach, awesome-garmin, garmin-grafana, intervals-mcp-server,
git-sweaty, Endurain, garmin-trimp, endurance-in-zone, VirtualPartner, 4caster,
HMFields, ble-scale-sync, slipstream, quick-plan · runalyze.com/glossary/marathon-shape ·
Garmin forum 311694 · Runna "Not Feeling 100%" (Tom's Guide).
