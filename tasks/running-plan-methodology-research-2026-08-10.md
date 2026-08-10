# Running Plan Generator Research — how Runna & co. structure training plans

Research report (2026-08-10). Intended destination once plan mode lifts:
`/tmp/claude-1000/-home-azureuser/2921f55d-6d37-4dd9-a191-fbe6a1196f8c/scratchpad/running-plan-research.md`
(copy this file verbatim, minus this header note).

---

## 1. Workout type taxonomy (what a credible generator must encode)

Union of Runna's session set, Garmin DSW types, and Daniels/Pfitzinger/Hansons/80-20 vocabulary. Each type = purpose + intensity anchor + canonical structures.

| Type | Intensity anchor | Purpose | Canonical structures |
|---|---|---|---|
| **Recovery run** | Daniels E low end / 80-20 Zone 1; "slower than you think" | Circulation, active recovery day after quality | 20–40 min very easy, no targets |
| **Easy / foundation run** | E pace (59–74% vVO2max), conversational | Aerobic base, mitochondria, bulk of volume (70–80%) | 30–70 min steady easy |
| **Strides** | R-pace bursts, full recovery | Form, neuromuscular sharpness, cheap speed for beginners | 4–8 × 15–20 s fast + 45–60 s walk/jog, appended to an easy run |
| **Long run — unstructured** | E pace, Zone 2 | Time on feet, structural endurance | 60–180 min; marathon plans peak >32 km |
| **Long run — progression** | E → M → T finish | Run fast on tired legs | e.g. 16 km as 8 easy / 5 steady / 3 @ MP; or thirds easy/steady/hard |
| **Long run — blocks** | E alternating Zone 3 steady | Controlled intensity inside volume | e.g. 4 × (3 km easy + 2 km steady) |
| **Long run — race pace practice** | goal race pace reps | Race-specific rehearsal (Runna's hardest LR type) | e.g. 24 km with 3 × 5 km @ MP, 1 km float; Pfitz "long run w/ 12–16 km @ MP" |
| **Medium-long run** (Pfitz) | E/steady | Second endurance stimulus midweek | 18–24 km midweek, upper-easy pace |
| **Tempo / steady** | M-to-T band; Garmin "tempo" ≈ marathon pace | Sustained comfortably-hard, general stamina | 20–40 min continuous @ M–HM effort; Hansons "tempo" = 8–16 km @ goal MP |
| **Threshold / cruise intervals** | T pace ≈ 1-hr race pace / LT2 (~83–88% vVO2max) | Raise lactate threshold | 20 min continuous @ T; 3 × 10 min @ T, 2 min jog; 5–6 × 1 mi @ T, 60 s rest (Daniels cruise); Pfitz LT run 6–11 km @ 15k–HM pace |
| **Sub-threshold volume** (Norwegian singles) | 2.5–3.5 mmol/L, just under LT2 (~10k–HM pace + 10–20 s/km) | High repeatable quality volume, low fatigue cost | 5 × 6 min (1 min jog); 10 × 3 min (1 min); 25 × 400 m short rest; 3×/week sustainable |
| **VO2max intervals** | I pace ≈ 3k–5k pace (95–100% vVO2max) | Aerobic power | 5 × 1000 m @ 5k, 400 m jog; 6 × 800 m @ 5k, 90 s; 4–5 × 3–5 min, equal-time jog. Daniels caps: rep ≤ 5 min; I volume ≤ lesser of 10 km / 8% weekly mileage |
| **Repetition / speed** | R pace ≈ mile–3k (105–110%) full recovery | Economy, mechanics, top-end | 8 × 200 m fast / 200 jog; 6 × 400 m / 3 min; Daniels cap ≤ 5% weekly mileage; Hansons "speed" 400–1600 m @ 5k–10k |
| **Anaerobic / sprint** (Garmin DSW) | >R, 40–60 s reps; sprints all-out <20 s | Anaerobic capacity, power | 6–10 × 45 s hard / 2–3 min easy; 6 × 10 s hill sprints |
| **Hill reps** | Effort-based, no pace target (Runna does exactly this) | Strength, economy, injury-resistant speedwork | 8–10 × 45–90 s uphill hard, jog-down recovery; **Kenyan hills**: continuous 10–15 min rolling hard up+down |
| **Fartlek** | Mixed, by time or feel | Variety, pace-changing skill, mentally fresh | 1-2-3-2-1 min pyramid (equal jog); Kenyan Thursday: 20 × 2 min on / 1 min off |
| **Progression run** | E → T over the run | Finishing strength, discipline | Thirds: easy/steady/hard; last 15 min @ T ("fast finish", 80-20) |
| **Race pace intervals** | Goal pace for the target distance | Specificity in final phase | 10k plan: 3 × 3 km @ 10k pace; HM: 2 × 5 km @ HMP; taper: "Taper Intervals" — short, sharp, low volume (Runna race week) |
| **Time trial** | All-out benchmark | Fitness check, recalibrate paces, milestone | 1 mi / 3 km / 5 km TT mid-plan; feeds pace model like a race result |

Structural grammar every session shares (Runna's universal template): warm-up with a pace *ceiling* ("no faster than X"), main set of repeating blocks, prescribed recoveries, cool-down. Hills/RPE sessions are effort-based, no pace.

## 2. Weekly microcycle templates by level

Rules first (all sources agree): hard days never adjacent; long run on a fixed weekday (match race day — Runna); every week has ≥1 pure easy day per quality day; quality count = 1 (beginner) → 2 (intermediate) → 2 + quality-long-run (advanced). 80/20 check: ≥~80% of weekly time in Z1–Z2.

**Beginner, 3 days/wk** (Runna beginner ≈ this)
- Tue: Easy 30–40 min + 4 strides
- Thu: Q1 — fartlek by time (e.g. 8 × 1 min on / 1 off) or hills; later phases: short intervals
- Sun: Long run, unstructured
- 1 quality session; everything else easy. No pace targets early (RPE), paces introduced once baseline exists.

**Intermediate, 4–5 days/wk**
- Mon: rest · Tue: Q1 intervals (I-pace, e.g. 6 × 800 @ 5k / 90 s)
- Wed: Easy 40–60 min (+strides Fri if 5 days)
- Thu: Q2 tempo/threshold (e.g. 3 × 10 min @ T / 2 min)
- Fri: rest or easy · Sat: easy 30 min
- Sun: Long run — rotate unstructured → progression → blocks → race-pace weeks

**Advanced, 5–6 days/wk** (Pfitz-shaped)
- Mon: recovery · Tue: Q1 VO2max or hills
- Wed: **medium-long** 18–22 km · Thu: easy + strides
- Fri: Q2 threshold (LT run 6–10 km @ T)
- Sat: recovery/easy · Sun: Long run, every 2nd–3rd week with MP segments
- Hansons alternative: 3 SOS/week (speed or strength Tue, tempo=MP Thu, long Sun capped ~16 mi / 25–30% of weekly volume) with easy runs stacked before the long run for **cumulative fatigue**.
- Norwegian-singles alternative for 5–9 h/wk: Tue/Thu/Sat sub-threshold sessions, everything else easy + weekly strides; no true VO2max until race-sharpening.

Rotation is the anti-boredom mechanism: same slots, different fillings. Q1 cycles (800s → 1000s → pyramid → hills → fartlek), Q2 cycles (continuous tempo → cruise intervals → progression), long run cycles its 4 types. Runna explicitly varies session composition weekly while keeping the weekly skeleton fixed.

## 3. Periodization macro structure

**Phases** (Pfitz's 5 mesocycles = cleanest template; Runna compresses to base + key block + taper):
1. **Base / mileage establishment** (25–35% of plan): volume ramp, easy + strides + light fartlek/hills only.
2. **Build / LT + endurance** (30–40%): threshold emphasis, long run grows, first race-pace touches.
3. **Peak / race prep** (20–25%): VO2max sharpening + race-pace specificity; volume peaks then holds; hardest long runs (race-pace practice) here.
4. **Taper**: Runna rule — **3 weeks for HM+ or plans ≥10 wk; 2 weeks for ≤10k / short plans**. Volume drops ~25–30% then ~40–60% by race week; intensity *kept* but in small doses (Runna "Taper Intervals" in race week to stay sharp).
5. **Recovery** (post-race, Pfitz): reversed ramp; Runna sells this as "between race blocks" plans.

**Volume ramp**: Runna = fixed weekly percentage rate depending on ability and days/week, with a hard ceiling on any single week's increase (their version of the ~10% rule); beginners get a *double constraint* (whichever of two limits is more conservative). Plan length 8–20 weeks by goal/ability.

**Cutback weeks**: Runna pattern is **build, build, deload — then build again from a slightly higher base** (2:1). Classic alternative 3:1. Deload ≈ −20–30% volume, quality reduced but not removed. Long-run peak: marathon >32 km, 2–3 weeks before race day; peak week is the last build week before taper.

## 4. Pace-zone derivation (VDOT-style)

- Input: most recent race time (or time trial). Runna asks for a recent 5k/10k finish time + self-assessed ability and derives all pace targets from it, plus an **Estimated Race Time** for the goal distance that the whole plan is keyed to.
- Daniels: race time → VDOT (effective VO2max) via his formulas; then zones as %vVO2max: **E 59–74%, M ~75–84%, T ~83–88%, I 95–100%, R 105–110%** (equivalently E ~70%, M ~84%, T ~88%, I ~98%, R ~105+ of VDOT velocity). Tables/calculators: vdoto2 or the formula `VO2 = -4.6 + 0.182258·v + 0.000104·v²`, `%max = 0.8 + 0.1894393·e^(−0.012778·t) + 0.2989558·e^(−0.1932605·t)`.
- Practical shortcut set (good enough for a generator): T ≈ pace you could race for 60 min ≈ 10k pace + 8–10 s/km; I ≈ 3k–5k pace; R ≈ mile–3k pace; M ≈ marathon prediction from Riegel (t2 = t1·(d2/d1)^1.06) or VDOT-equivalent; E ≈ M + 45–90 s/km. Norwegian sub-T ≈ T + 10–20 s/km.
- Progression: don't re-derive zones from every run. Runna nudges the Estimated Race Time **20–30 s at a time** when a trend appears (see §5), and steps ability/pace up "a small structured amount each week" inside the coaching framework. Time trials mid-plan are explicit recalibration points.
- Fallbacks: no race time → conservative estimate from onboarding questions (how long since last run, exercise frequency/type — Runna's New to Running flow), or RPE-only sessions. Runna also offers RPE mode for trails/hills/heat, and since Jul 2026 automatically adjusts target paces for **heat & humidity**.

## 5. Adaptation rules

**Runna (deliberately conservative — structure never auto-changes):**
- **Pace Insights**: after every eligible session (intervals, tempo, TT, some long runs) you get a Pace Status — *Pace on Point / Ahead of the Pack (speed up) / Let's Review Your Pace (slow down) / Variable Pace Detected / Monitoring Your Pace Data*. Only a **consistent multi-session trend** triggers a recommendation; it adjusts estimated race time by 20–30 s; always advisory (accept/revert); paces change, plan structure doesn't. Beginner plans excluded.
- Missed sessions: move days freely; plan difficulty slider changes count/intensity of hard sessions and how many long runs carry pace targets.
- Environment: heat/humidity auto pace adjustment; RPE fallback.

**Garmin DSW (fully automatic, opposite philosophy):** model = VO2max estimate + 7-day load + **load focus** (anaerobic/high-aerobic/low-aerobic balance) + training status + recovery time + sleep/HRV. Each day it picks one of 7 types (recovery, base, tempo, threshold, VO2max, anaerobic, sprint) to fill the most-lacking load bucket; if recovery time is high or sleep was bad, it downgrades to recovery/base or rest. Poor execution vs. target lowers next suggestions.

**Strava:** Fitness & Freshness = Banister impulse-response over Relative Effort (TRIMP from HR or RPE); Athlete Intelligence is genAI summarization of the same, not a planner. Useful pattern: fitness/fatigue/form as a gating signal.

**Sane synthesis for a generator:**
1. Missed 1 session → drop it, never cram; keep long run > threshold > intervals as the priority order for what survives a short week.
2. Missed 4–7 days → repeat current week at prior volume; missed >7–14 days → step back one build cycle and re-ramp; longer → restart ramp at ~60–70%.
3. Pace trend rule (Runna-style): 2–3 consecutive quality sessions faster than target at OK RPE → offer +20–30 s race-time upgrade; consistent misses → offer downgrade. Never silent.
4. Fatigue gate (Garmin-style, if HR/RPE available): RPE ≥ 9 on an easy run, or rising HR at fixed pace, or 2 bad sessions in a row → convert next quality to easy, or pull the deload week forward.
5. Environment: heat/humidity pace offsets; hills/trails → switch session to RPE.
6. Injury/return flows use "where you are now, not where you were" baselining (Runna post-injury plans).

## 6. What Runna does that makes plans engaging (the checklist to copy)

1. **Named variety with a fixed skeleton** — 8 session types + 4 long-run types; weeks feel different while the rhythm stays predictable. Long runs are not always slogs: progression / blocks / race-pace practice embed quality.
2. **Every session has a story**: title, purpose line ("why this session"), phase context. Hills are effort-based (freeing), warm-ups have pace *ceilings* not targets.
3. **Visible macro narrative**: build → build → deload → taper is explicit; users know which week type they're in and why it's easier/harder.
4. **A single headline number that moves**: Estimated Race Time. Every quality session feeds Pace Insights; a "Pace Status" lands after each workout (instant feedback loop), and "Ahead of the Pack" upgrades feel like leveling up.
5. **The plan reacts but never scares**: adjustments are suggestions (accept/revert), 20–30 s at a time — user stays in control; structure is stable so the plan feels authored, not random.
6. **Watch-native execution**: structured workout pushed to Garmin/Apple — "no thinking involved"; auto-advancing steps, on-wrist paces.
7. **Tick-off compulsion**: reviewers literally call completing the plan checklist "addictive" — completed/remaining sessions, streaks, week progress.
8. **Milestones**: time trials as mid-plan fitness checks; race-week mode with its own content (Taper Intervals, race-week tips).
9. **Flexibility as a feature**: 2–6 days/wk, move any run, difficulty slider, long-run day choice, RPE mode, strength & mobility add-ons, treadmill/track variants of the same session.
10. **Context-aware polish**: automatic heat/humidity pace adjustment; post-injury/post-natal/between-races plan variants.
11. **Community layer**: events, classes, challenges (secondary, but reviewers mention it).
- Cautionary note from reviews: Runna's known criticisms are easy-pace targets too fast, marathon intensity too high for true beginners, and only one training philosophy. A generator can beat it by offering effort-based easy days and a Hansons/Norwegian-flavored alternative.

## 7. Sources

- Runna support: [How plans are built around current fitness](https://support.runna.com/en/articles/15231838-how-does-runna-build-your-training-plan-around-your-current-fitness) · [Understand your workouts](https://support.runna.com/en/articles/15690947-understand-your-runna-workouts) · [Pace Insights](https://support.runna.com/en/articles/14656203-what-are-pace-insights-and-how-do-they-work) · [Long runs](https://support.runna.com/en/articles/9357249-understanding-your-long-runs) · [Build weeks](https://support.runna.com/en/articles/15013260-what-is-a-build-week-understanding-progressive-overload-in-your-running-plan) · [Recovery/deload](https://support.runna.com/en/articles/15272605-how-does-runna-build-recovery-into-your-training-plan) · [Race week](https://support.runna.com/en/articles/6231540-top-tips-for-race-week) · [Adjusting estimated race time](https://support.runna.com/en/articles/6205998-adjusting-your-estimated-race-time-and-pace-targets) · [Training preferences](https://support.runna.com/en/articles/10393191-how-to-use-training-preferences) · [Create a plan](https://support.runna.com/en/articles/15443877-how-to-create-a-training-plan-in-runna)
- Runna marketing: [Training plans](https://www.runna.com/training/training-plans) · [Marathon plans](https://www.runna.com/training/marathon) · [Interval training guide](https://www.runna.com/guides/explainers/interval-training-what-is-it-and-how-does-it-work)
- Runna reviews: [The Runner Beans](https://therunnerbeans.com/runna-coaching-app-review/) · [Tom's Guide](https://www.tomsguide.com/reviews/runna-app) · [TechRadar on AI-plan injury risk](https://www.techradar.com/health-fitness/are-ai-training-apps-like-runna-putting-you-at-risk-of-injury-i-asked-a-real-life-running-coach) · [Bright Side Sunday](https://brightsidesunday.substack.com/p/runna-review-from-serial-quitter) · [9to5Mac heat adaptation](https://9to5mac.com/2026/07/29/runna-now-automatically-adapts-training-paces-based-on-heat-and-humidity/)
- Garmin: [DSW types for runners (Garmin blog)](https://www.garmin.com/en-US/blog/fitness/daily-workout-suggestions-for-runners/) · [the5krunner DSW algorithm](https://the5krunner.com/garmin-features/training/daily-suggested-workouts/) · [the5krunner training load](https://the5krunner.com/garmin-features/training/training-load/) · [Running Genie DSW explained](https://therunninggenie.com/blog/garmin-daily-suggested-workouts-explained)
- Strava: [Fitness & Freshness help](https://support.strava.com/en-us/articles/15402032-fitness-freshness) · [Athlete Intelligence press](https://press.strava.com/articles/stravas-athlete-intelligence-translates-workout-data-into-simple-and) · [the5krunner Relative Effort](https://the5krunner.com/2025/11/17/strava-relative-effort-guide-tss-2025/)
- Methodology: [Daniels VDOT zones explained](https://www.brenoamelo.com/blog/jack-daniels-vdot-explained) · [Daniels Running Formula review/summary](https://www.teesche.com/bookshelf/jack_daniels_daniels_running_formula) · [Pfitz plans explained](https://runningwithrock.com/pfitz-marathon-training-explained/) · [Hansons vs Pfitzinger](http://www.logicoflongdistance.com/2012/12/hansons-marathon-method-and-pfitzingers.html) · [80/20 intensity guidelines](https://www.8020endurance.com/intensity-guidelines-for-80-20-running/) · [80/20 plan structure](https://www.8020endurance.com/understanding-your-8020-run-plan/) · [80/20 summary](http://420to240runninggeek.blogspot.com/2016/01/matt-fitzgerald-8020-running-summary.html) · [Norwegian singles method](https://marathonhandbook.com/norwegian-singles-training/) · [Double threshold explained](https://marathonhandbook.com/double-threshold-training/) · [Norwegian singles comparative analysis](https://norwegiansingles.run/section7_comparative_analysis.html) · [Kenyan fartlek](https://www.traininkenya.com/2018/06/18/run-the-kenyan-way-fartlek/)
