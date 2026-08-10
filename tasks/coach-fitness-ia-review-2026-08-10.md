# Coach & Fitness UX review — 2026-08-10

Interactive proposal + mockup: https://claude.ai/code/artifact/1b25220a-5fd0-4995-933d-c2ed2d33a9f2
Measured live at 390px (Playwright, Victor's data).

## Findings

- Coach: 5811px = **6.9 phone screens**. Daily brief + week review + Coach's Take + Insights + 30 analysis rows, all expanded.
- Fitness: pill sub-nav sits **1.8 screens down** (below always-rendered Insights panel + Coach's Take); every one of the 8 sub-tabs re-serves that header. Sub-tabs run 2.6–3.9 screens each.
- **Duplication**: `renderInsightsPanel` + `renderCoachTake` render on BOTH Coach and Fitness (web/index.html renderCoach + renderFitness).
- No summary layer anywhere: 8 domains, ~30 cards, no at-a-glance state; pills encode no status.

## Proposal (direction A — status board + drill-in)

- **Fitness** → one-screen status board: vitals strip (readiness/illness/TSB/ACWR) + 8 domain tiles (status dot from existing grades, headline number, verdict line). Tap → full-screen domain detail (existing renderers unchanged) with back button + lateral domain chips. Insights/Coach's Take removed from Fitness; one-line coach strip links to Coach.
- **Coach** → briefing feed: daily brief lead (sections collapsed), Coach's Take + limiters second (only home), then one chronological feed (pulses / week review / analyses) as compact rows opening the existing modal; 5 visible + "show all".
- Engine/data untouched; purely web/index.html. Effort M overall.
- Expected: Coach 6.9 → ~2.5 screens; Fitness overview ~1.2 screens.

## Status

AWAITING VICTOR: "go" (full direction A) vs "minimal fix" (dedupe + sticky pills only). No implementation yet.
