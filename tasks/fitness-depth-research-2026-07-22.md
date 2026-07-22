# Fitness-depth research: what best-in-class apps do with daily health data

Date: 2026-07-22. Purpose: inspire a daily-readiness / actionable-insights upgrade for PaceForge, fed by a Garmin fēnix 7X Pro (VO2max, training readiness, training status, HRV status, sleep, Body Battery, RHR, stress, running dynamics, race predictor, load/TSB).

Method note: web research via built-in WebSearch (Firecrawl CLI not installed on this VM). Sources listed at the end.

---

## (a) Daily-readiness panel elements per app

| App | Daily panel elements | Score model | How advice is delivered |
|---|---|---|---|
| **Garmin (Morning Report + Training Readiness)** | Training Readiness 0–100, Sleep Score, Body Battery, HRV Status, Recovery Time (h), stress, weather, calendar, Daily Suggested Workout | 6 inputs: sleep score (last night), sleep history (3 nights), HRV status vs baseline, recovery time, acute load, stress history (3 days). >73 = ready for demanding effort; <34 = rest/light. Acute factors (last night) outweigh trends | One number + a Daily Suggested Workout that scales intensity to readiness; recovery-time countdown |
| **Whoop** | Recovery % (green 67–100 / yellow 34–66 / red 0–33), Strain target for the day, Sleep Performance, sleep debt, HRV/RHR/resp-rate/temp deltas | Recovery from overnight HRV, RHR, resp rate, sleep quantity/quality, skin temp, SpO2. Strain target derived from recovery and updates live during the day | Explicit daily prescription: "you're green — target strain X"; Sleep Coach names an exact bedtime from sleep need (need = baseline + strain + debt − naps) and a chosen goal level (Peak 100% / Perform 85% / Get By 75%) |
| **Oura** | Readiness 0–100 with named contributors (resting HR + timing, temp deviation, sleep, previous-day activity, HRV Balance, activity balance), bedtime window | HRV Balance = 14-day HRV avg vs 3-month avg, recent days weighted. Temperature shown as delta vs baseline (e.g. +0.3 °C) | Contributor list explains *why* the score is what it is; home-screen cards flag "ideal day for challenging / light / limited activity"; bedtime-window guidance; specific cause-hunting hints (lowest HR late in night → late meals/alcohol/caffeine) |
| **Athlytic** (Apple Watch) | Recovery %, Target Exertion range for today, out-of-range flags on HRV/RHR/SpO2/resp/temp | Today's HRV+RHR vs **60-day** personal baseline, HRV weighted higher | Gives a target exertion *band* to stay inside today; flags any vital outside its normal range with a one-line explanation |
| **Training Today** | Single Readiness-to-Train score, color-coded high/medium/low-intensity recommendation | Rolling 24 h HRV vs 60-day HRV average | One dial + one sentence naming the metric that drove the assessment |
| **Intervals.icu** | Fitness (CTL), Fatigue (ATL), Form (TSB) chart with 5 colored zones; wellness log (HRV, RHR, sleep, soreness) overlaid on load | Form zones (as % of CTL): >+20 Transition (yellow), +10..+20 Fresh (blue), +10..−5 Grey, −5..−30 **Optimal** (green), <−30 High Risk (red) | Zone color *is* the advice: green = productive training range, red = back off. Everything is charted vs time so the user self-serves trends |
| **Runalyze** | Effective VO2max (per-run, from HR:pace ratio), marathon shape %, race prognosis, TRIMP, monotony, training strain | Monotony = mean/SD of daily TRIMP over 7 days (<0.6 good, >0.67 critical); marathon shape from 6-month history: weekly km 2/3 + long runs 1/3; prognosis damped by shape | Numbers + thresholds, minimal prose; prognosis visibly drops if you don't do the long runs, which is itself the message |
| **Stryd** | Critical Power, power zones, Running Stress Balance (RSS-based TSB), power-duration curve, upcoming events | CP from best 3/9/20-min efforts (or single-run estimate); RSS from power not HR | "Train at X–Y watts today"; RSB tells you if the last weeks were too hard |
| **Runna** | Plan-first: today's workout with target paces; Pace Insights post-run; mileage/consistency graph | Paces adapted from executed speed sessions + post-workout RPE feedback + weather (heat/humidity) adjustments | Adapts the *next workout* rather than showing a readiness score: "we're bumping your tempo pace 5 s/km"; post-race recovery ease-back flow |

**Pattern:** every leader converges on (1) one headline number 0–100, (2) traffic-light color, (3) a *named list of contributors* explaining the number, (4) one concrete action for today (workout, exertion band, or bedtime). The score without the "because X, Y" and the "so do Z" is what commodity apps do; the leaders always close the loop.

---

## (b) Catalog of actionable-insight rules (metric condition → advice wording)

Conventions: `hrv7` = 7-day HRV rolling avg; `swc` = smallest worthwhile change = ±0.5 × SD of nightly HRV over the baseline window; baseline = ~60–90 day weighted normal range. TSB = CTL − ATL. ACWR = 7-day load / 28-day avg load.

### HRV / autonomic recovery
1. **hrv7 within baseline range (Balanced)** → "HRV balanced — your body is absorbing the training. Proceed with the plan as written."
2. **Last-night HRV below hrv7 − swc, single night** → "HRV dipped last night. One-off dips are usually sleep/alcohol/stress, not fitness. Keep today's session but cap the intensity — finish feeling like you could do more."
3. **hrv7 below baseline − swc (Low status)** → "HRV has been below your normal range for several days. Swap today's quality session for an easy Z2 run; retest tomorrow." (HRV-guided-training protocol: high-intensity only when HRV ≥ SWC lower bound; studies show ~+8% endurance gains and ~26% fewer sick days vs fixed plans.)
4. **hrv7 unusually HIGH vs baseline (Unbalanced-high)** → "HRV is unusually elevated — this can be parasympathetic overcompensation from accumulated fatigue, not super-recovery. Treat it like a caution flag if it coincides with poor sleep or high load."
5. **HRV low + RHR up ≥5 bpm + (if available) temp/resp elevated** → "Multiple recovery vitals are off baseline — possible incoming illness. Rest today; a missed easy run costs nothing, running sick costs a week."

### Resting HR
6. **RHR ≥ +5 bpm over 7-day avg, isolated** → "Resting HR is up 5+ bpm. Common causes: late meal, alcohol, heat, stress, incubating illness. Go easy and hydrate."
7. **RHR trending down over 4–6 weeks at stable load** → "Resting HR down X bpm this month — a classic aerobic-fitness adaptation. The base work is paying off."
8. **Lowest overnight HR occurs in second half of night (Oura pattern)** → "Your heart rate bottomed out late in the night — your body spent the first half digesting/processing. Avoid meals, caffeine, alcohol and hard exercise in the 3 h before bed."

### Sleep
9. **Sleep < need for 2+ consecutive nights (sleep debt accumulating)** → "You're ~1.5 h in sleep debt. Tonight's target bedtime: 22:30 (need + debt repayment). Recovery is where training becomes fitness."
10. **Bedtime SD over last 7 days > 45–60 min** → "Your bedtime varied by over an hour this week. Consistency beats duration: same bedtime ±30 min (weekends too) measurably improves sleep efficiency." (Whoop Sleep Consistency + athlete-sleep literature.)
11. **Poor sleep night before a planned quality session** → "Short sleep last night (5 h 40). Keep the session but expect paces to feel harder — judge by effort, not the watch. If it's a key workout, consider swapping with tomorrow's easy day."
12. **Deep sleep/restorative sleep low + evening activity late** → "Hard sessions ending <3 h before bed suppress deep sleep. Shift quality runs earlier or push bedtime later on interval days."
13. **Sleep score high + HRV balanced + TSB > −10** → "Green day: slept well, HRV balanced, fatigue manageable. If you've been saving a hard session, today is the day."

### Body Battery / stress
14. **Morning Body Battery < 30 (failed to charge overnight)** → "Body Battery barely charged overnight — recovery didn't happen. Make today easy regardless of what the plan says."
15. **Body Battery < ~40 before a planned evening quality session** → "Today's stress already drained you to 35. An interval session now yields junk fatigue — swap to easy Z2 or move the workout to tomorrow morning."
16. **3+ consecutive mornings with Body Battery plateauing in the 40–60 band** → "Your energy isn't rebounding morning-to-morning — a reliable early sign of accumulating fatigue. Insert an extra rest day this week."
17. **Days-to-recharge after hard effort > typical** → "It took 4 days for morning Body Battery to clear 80 after Sunday's long run (usually 2). Your load is outpacing recovery capacity — hold volume flat this week."
18. **All-day stress avg high on a rest day** → "Rest day, but physiological stress stayed high — rest isn't only about not running. Aim for a real wind-down tonight."

### Training load / TSB / ACWR
19. **TSB in −10..−30 (Friel optimal / Intervals.icu green)** → "Form −18: productive training zone. You're loaded but adapting — this is where fitness is built. Stay the course."
20. **TSB < −30 (high-risk red)** → "Form −34: you've outrun your recovery. Injury/illness risk is elevated — cut the next 2–3 days to easy running and let form climb back above −30."
21. **TSB > +15 outside a taper** → "You're very fresh (+18) with no race coming — you're losing fitness. Time to add a quality session or bump volume."
22. **Race in 7–14 days** → "Taper math: to hit race day at form +15..+25 (Friel's sweet spot), start dropping volume now; keep some intensity so you don't go flat."
23. **ACWR > 1.3 (this week's load >1.3× the 4-week avg)** → "This week is running 1.4× your recent norm. Above 1.5 injury risk is 2–4× for the next 7 days — trim the remaining sessions to land back under 1.3."
24. **ACWR < 0.8 for 2+ weeks** → "You're undertraining vs your base (ratio 0.7). Detraining plus a spike risk later — rebuild gradually, ~10% per week."
25. **Monotony > ~0.67 / no hard-easy variation (Foster)** → "Seven near-identical days in a row. High monotony + high load = overtraining risk. Polarize: make hard days harder and easy days genuinely easy."
26. **3–4 weeks since last down-week and CTL rising** → "You've built for 4 straight weeks — schedule a cutback week: −30–50% volume, reduced intensity. Adaptation happens in the recovery week."

### VO2max / performance trend
27. **VO2max ↑ over 4–6 weeks** → "VO2max 52 → 54 since June. Your 10K prediction improved 1:10. Whatever you're doing, it's working."
28. **Load adequate but VO2max flat/declining ≥2 weeks (Garmin 'Unproductive')** → "Training load is fine but fitness is trending down — the usual culprits are sleep, stress, fueling or too much monotony, not the running itself. Check the recovery side before adding more load."
29. **Race predictor delta vs goal pace** → "Predictor says 1:52 half vs your 1:50 goal. Gap ≈ 4 s/km. Note: Garmin's marathon estimate runs 30–60 min optimistic without high volume — trust 5K/10K predictions, discount the marathon one unless weekly km and long runs back it up (Runalyze-style 'shape' damping)."

### Running dynamics (from activities)
30. **Avg cadence < ~164 spm on easy runs (Garmin red/orange percentile)** → "Cadence 158 — overstriding territory for most runners. Try +5% (166) on one easy run this week; a metronome beep or playlist helps. Don't jump straight to 180 — it's a guideline from elites, not a law."
31. **GCT > 300 ms sustained** → "Ground contact 305 ms (recreational range is 250–300, elites <200). Shorter, quicker steps with the foot landing under your hips will trim it — same cue as cadence."
32. **Vertical ratio high (VO/stride length > ~9–10%)** → "You're spending energy going up, not forward (vertical ratio 10.2%). Improves naturally with cadence work — track it per-pace, not absolute."
33. **Cadence drops >5% in the last third of long runs** → "Your cadence decays late in long runs — a form-fatigue signature. Add strides after two easy runs a week and check the trend next month."
34. **Dynamics improving at same pace** → "Same 5:30/km pace, but GCT −12 ms and vertical ratio −0.6% vs last month — you're getting cheaper to run. Efficiency gains bank race time without fitness change."
35. **GCT balance persistently off 50/50 by >2%** → "Left/right ground-contact imbalance of 52.3/47.7 persists across runs — worth watching after any niggle; a growing asymmetry often precedes injury complaints."

### Cross-metric "day plans" (the pattern users love in Whoop/Garmin)
36. **Everything green** → "Green light: readiness 82, HRV balanced, form −12. Great day for the scheduled interval session — you can hit the top of the pace targets."
37. **Mixed signals (good sleep, deep TSB hole)** → "You slept well but you're 3 hard days deep (form −28). Readiness is about more than last night — keep today aerobic."
38. **Red day with planned key workout** → "Readiness 28. Moving Thursday's intervals to Saturday costs nothing; forcing them today costs the weekend. Plan updated — confirm?"

---

## (c) Freshness / trend-direction UX patterns

- **Two-window baselines everywhere.** Short window vs long window is the universal idiom: Garmin HRV = 7-day avg vs ~90-day weighted baseline (needs 3 weeks to establish); Oura HRV Balance = 14-day vs 3-month; Athlytic/Training Today = today vs 60-day; load = 7-day acute vs 28/42-day chronic (ATL/CTL, ACWR). PaceForge already has TSB-style pairs — reuse the same idiom for HRV/RHR/sleep.
- **Show the value AND the delta vs "your normal".** Oura renders temperature purely as a delta ("+0.3 °C vs baseline"); Whoop shows HRV/RHR against 30-day lines. A number without its personal-normal band is meaningless to users.
- **Personal normal range as a shaded band** on sparklines (mean ± SWC / ±1 SD), with status words derived from band position: Balanced / Unbalanced / Low (Garmin's exact model). Words + color, not just numbers.
- **Traffic-light zones with named meanings**: Whoop green/yellow/red with % cutoffs (67/34); Intervals.icu 5-zone form colors (Transition / Fresh / Grey / Optimal / High Risk). Users learn "green = push, red = rest" instantly.
- **Contributor breakdown under every headline score** (Oura's readiness contributors, Garmin's 6 readiness factors): each factor gets its own mini-bar/status so a low score is self-explanatory.
- **Trend arrows + timeframe pickers**: Whoop Trend Views (weekly / monthly / 6-month), year heatmaps in its Monthly Performance Assessment; Oura Trends with daily/weekly/monthly rollups, big current value top-left with period average alongside.
- **Data recency handled explicitly**: Garmin shows "Recovery Time: 34 h" as a countdown (recency built into the metric); readiness apps recompute each morning and label the panel "as of this morning"; Athlytic surfaces "Recovery hasn't updated" as a first-class troubleshooting state. For a sync-based app like PaceForge: stamp every panel with "last sync: X h ago" and grey out / de-color panels when data is >24–36 h stale — never show a confident green from stale data.
- **Real-time vs daily split**: Garmin separates once-a-day Training Readiness from continuously-updating Body Battery; Whoop's strain target updates live during the day. A daily-sync app should be honest that it's the once-a-day kind.

---

## (d) Prioritized recommendation for PaceForge (solo-dev, self-hosted, daily Garmin sync)

**P0 — Morning readiness panel (biggest win, all data already synced).**
One page/section: headline readiness (either surface Garmin's own Training Readiness or compute a transparent local blend), traffic-light color, and a contributor list (sleep score, HRV vs band, Body Battery, TSB, RHR delta). Every metric shown as *value + delta vs personal baseline + 7-day sparkline with shaded normal band*. Stamp with last-sync time; grey out when stale. This is 80% of the perceived value of Whoop/Oura and is mostly presentation over data PaceForge already has.

**P1 — Rules engine → one daily sentence + workout adjustment.**
Implement ~15–20 of the catalog rules in (b) as a plain ordered rule table (condition → template). Priority order: illness guard (#5) > HRV low (#3) > TSB red (#20) > ACWR spike (#23) > green-day (#13/36) > sleep nudges (#9/10) > dynamics tips (#30–34, weekly not daily). Output exactly ONE primary recommendation per day ("today: easy 45 min, because HRV low + form −26") plus optionally one secondary nudge. Wire it to the plan: on red days offer a one-click "swap today's quality session with the next easy day" (Runna's adaptivity is its whole moat, and the swap is cheap to implement).
Concrete thresholds to hardcode: SWC = ±0.5 SD of nightly HRV over 60 days; RHR alert +5 bpm vs 7-day avg; TSB zones (−5..−30 green, <−30 red, >+15 stale/taper); ACWR 0.8–1.3 ok / >1.3 warn / >1.5 red; monotony >0.67 warn; bedtime SD >45 min nudge; cadence <164 spm tip.

**P2 — Sleep/bedtime coaching.**
Sleep need = personal average + debt repayment; suggest a bedtime ("target 22:45 tonight — you're 70 min in debt and tomorrow is intervals"). Weekly bedtime-consistency stat. Cheap: it's arithmetic over data already synced.

**P3 — Weekly digest + down-week detector.**
One weekly summary (VO2max trend, CTL change, monotony, dynamics trends, race-predictor delta vs goal) and an automatic "you've built 4 weeks — this week is a cutback: −40% volume" flag that actually edits the plan week. Suits a self-hosted app better than more daily noise.

**Skip:** real-time strain targets (needs all-day streaming, Garmin sync is daily), ML-based scores (opaque, unverifiable solo), duplicating Garmin's own once-a-day numbers without adding the *because/so-do* layer — the research shows the advice loop, not the score, is what differentiates the leaders.

---

## Sources

- Garmin Training Readiness: https://the5krunner.com/garmin-features/training/training-readiness/ ; fēnix 7 manual https://www8.garmin.com/manuals/webhelp/GUID-C001C335-A8EC-4A41-AB0E-BAC434259F92/EN-US/GUID-C21BE0C8-A08E-4DA1-B6C6-2E0E2DDDB372.html
- Garmin Morning Report: https://the5krunner.com/2022/06/28/garmin-morning-report/ ; https://www.shoulditrain.com/blog/garmin-morning-report-explained
- Garmin HRV Status: https://www.garmin.com/en-US/blog/fitness/understanding-the-hrv-status-on-your-garmin-smartwatch/ ; https://www.wareable.com/garmin/garmin-hrv-status-explained-what-is-it-how-to-use
- Garmin Training Status: https://the5krunner.com/2023/06/28/garmin-training-status-in-detail-and-chaging-to-be-productive/ ; https://www.garmin.com/en-US/blog/fitness/garmin-training-status-and-how-to-use-it/
- Garmin Body Battery: https://the5krunner.com/garmin-features/sleep/body-battery/ ; https://www.datadrivenathlete.org/blog/garmin-body-battery-guide ; https://www.shoulditrain.com/blog/garmin-body-battery-for-athletes
- Garmin Race Predictor: https://gadgetsandwearables.com/2022/09/19/garmin-race-predictor-accuracy/ ; https://the5krunner.com/garmin-features/performance/race-predictor/
- Whoop Recovery: https://www.whoop.com/us/en/thelocker/how-does-whoop-recovery-work-101/ ; https://developer.whoop.com/docs/whoop-101/ ; Strain target https://www.whoop.com/us/en/thelocker/work-out-frequency-strain-target/
- Whoop Sleep Coach / consistency / debt: https://support.whoop.com/hc/en-us/articles/360023249533-Sleep-Coach ; https://www.whoop.com/us/en/thelocker/sleep-consistency-more-to-sleep-than-sleep-need/ ; https://www.whoop.com/us/en/thelocker/everything-to-know-about-sleep/
- Whoop trends/UI: https://www.whoop.com/us/en/thelocker/track-progress-with-new-trend-views/ ; https://www.whoop.com/eu/en/thelocker/monthly-performance-assessment/ ; https://www.925studios.co/blog/whoop-design-breakdown
- Oura Readiness: https://ouraring.com/blog/readiness-score/ ; contributors https://support.ouraring.com/hc/en-us/articles/360057791533-Readiness-Contributors ; trends https://support.ouraring.com/hc/en-us/articles/360055983614-Using-Trends ; https://ouraring.com/blog/trends/
- Athlytic: https://www.athlyticapp.com/getting-started ; https://athlyticapp.helpscoutdocs.com/article/21-recovery-preferences
- Training Today: https://trainingtodayapp.helpscoutdocs.com/article/84-how-training-today-works
- Intervals.icu: https://www.intervals.icu/features/fitness-chart/ ; form zones https://forum.intervals.icu/t/zones-of-form-in-fitness-chart/3623
- Runalyze: https://blog.runalyze.com/tutorial/runalyze-understanding-the-calculations/ ; monotony https://runalyze.com/glossary/monotony ; strain https://runalyze.com/glossary/training-strain
- Stryd: https://blog.stryd.com/2021/08/04/what-is-critical-power/ ; https://help.stryd.com/en/articles/8258035-estimated-critical-power
- Runna: https://support.runna.com/en/articles/14656203-what-are-pace-insights-and-how-do-they-work ; https://www.runningwestwardho.co.uk/post/runna-app-updates-2026-smarter-training-plans-adaptive-coaching-new-features-explained
- HRV-guided training / SWC: https://help.elitehrv.com/article/355-what-is-the-hrv-7-day-rolling-average-and-coefficient-of-variation ; https://www.trainingpeaks.com/coach-blog/new-study-widens-hrv-evidence-for-more-athletes/ ; https://www.athletedata.health/guides/hrv-guided-training
- TSB zones (Friel): https://joefrieltraining.com/managing-training-using-tsb/ ; https://www.trainingpeaks.com/learn/articles/applying-the-numbers-part-3-training-stress-balance/
- ACWR: https://pubmed.ncbi.nlm.nih.gov/32485779/ ; https://www.scienceforsport.com/acutechronic-workload-ratio/
- Running dynamics norms: https://the5krunner.com/garmin-features/running-dynamics/ ; cadence percentiles https://the5krunner.com/garmin-features/running-dynamics/cadence/ ; https://thewiredrunner.com/ground-contact-vertical-oscillation/
- Athlete sleep consistency: https://www.gssiweb.org/sports-science-exchange/article/sse-113-sleep-and-the-elite-athlete ; https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9206056/
- Down weeks: https://runtothefinish.com/recovery-week-running/ ; https://www.builttoendure.pro/post/deload-weeks-the-important-weeks-most-runners-and-cyclists-skip
