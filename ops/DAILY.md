# Daily reel run (the scheduled routine follows this exactly)

Runs every day at 06:47 America/New_York (catch-up firings later in the day continue it).
Goal: settings.reels_per_day verified reels (2 since 2026-10-29, was 10 on 2026-10-28; halved automatically by the strategy's
brake when reach per reel collapses) and settings.stories_per_day stories (5), each queued for its own slot.
GitHub Actions (publish.yml) publishes them; the session's safety-net trigger dispatches it hourly.

**Resume, never redo.** The run can be interrupted (session restarts). At the start of every firing, list
today's plans and skip every reel/story that already has a queue item, a HOLD.md, or a committed
DELIVERABLE.md. Commit and push after EACH queued reel or story, so an interruption loses at most one.

## 0. Setup
```bash
pip install -q -r requirements.txt
python3 -c "import sys; sys.path.insert(0,'ops'); from ig import IG; print(IG().check_token())"   # must print mzconsulting.llc
mkdir -p ~/.claude/instagram && cp config/voice.md ~/.claude/instagram/voice.md   # voice profile for .claude/skills/ig-*
```

If the token check fails (TokenExpired): stop, write `reels/HOLD_<date>.md`, commit, notify Mert. Do not continue.

## 1. Plan
`python3 ops/strategy.py plan --all` → a JSON list, one plan per reel (k = 0..n-1; plan.brake says if the
count was halved). Each item: (id, pillar, cta, arms, voice_name, length_rule, hook_rule, slot, src, tracking_link,
keyword, dm_link, caption_cta, notes). Use it as-is; never override the strategy by taste. Create `reels/<id>/meta.json`
with {id, date, pillar, cta, arms, family} for every reel. Ten reels rotate through all seven pillars (reel k follows
the calendar of day+k), each with its own hook, opener, voice, CTA mode and slot.

## 2. Script (2 agents max: one writer for all reels, one adversarial verifier for the whole batch)
- Read CLAUDE.md (playbook). Re-read mzconsulting.agency on Mondays. Check `reels/*/script.json` from the last 14 days
  AND today's other reels: no repeated topic. Ten a day needs ten distinct, verifiable angles; when the pool runs dry
  the reel gets a HOLD.md ("no unrepeated verified topic"), never a repeat or an unverified claim.
- deadline pillar: only a verified current rule change or compliance date; if there is none, HOLD that reel.
- Write all scripts first, then hand the whole batch to ONE verifier agent (one report per reel), then render.
- Writer: read ops/HOOKS.md first (including "Scoring with the instagram-agent pack"). Draft 3 hook
  candidates from different formulas in `.claude/skills/ig-reel/hooks.json` that fit plan.hook, score them
  with `hookscore.py`, and use one scoring >= 50 as the first VO line. Build the opening from plan.hook + plan.opener (mute test: frame 0
  readable without sound; first VO line <= 7 words). Then draft the 5 scenes + 5 VO lines for the pillar
  using hook_rule, opener_rule and length_rule, the CTA set for `cta`
  (gaplist / finder / comment_gaplist / comment_finder, exactly as in engine/reel.html CTA_SETS), and only claims with a
  verbatim quote from current ecfr.gov (versioner API, --compressed, latest issue date) / cpsc.gov / fcc.gov.
- Verifier (fresh agent): re-fetch every source, refute overclaims, enforce limits. Anything unverifiable is removed.
- Write `reels/<id>/script.json` (scenes, vo, caption, pinned_comment, tracking_link, sources). Caption line 5 and
  pinned comment = plan.caption_cta for comment arms, otherwise the playbook CTA line.

## 3. Render
In engine/: put the scenes into the REEL object (meta: id, pillar, cta, voice = plan.voice_name,
opener = plan.opener, kicker (kicker opener only), look = settings.reel_look (batch_render.py sets it; `dossier` since 2026-11-01), footnote "Illustrative example. Not legal advice."),
write vo.txt, then:
```bash
python3 voice.py --fit          # must print ALL OK; total must stay within the length_rule range
python3 render.py --stills 0 0.5 <one mid-point per scene + last frame>   # LOOK at every PNG, fix, repeat
# frame 0 and 0.5 s are the hook: would a muted seller scrolling past stop? If not, rewrite the opening.
python3 ../.claude/skills/ig-reel/beats.py vo.txt --target <total s> --wpm 165   # fix hook>3s / no-loop flags
python3 render.py && python3 build_audio.py
```
Caption: run `.claude/skills/ig-human/humanize.py` + `detect.py` (target PASS) and
`.claude/skills/ig-caption/caption.py --keywords "<2 search phrases>"` (no FAIL).
Write `reels/<id>/DELIVERABLE.md` with the QA table (add rows: hook score + formula, beats flags, human
score, caption lint verdict, opener + hook used, mute test PASS/FAIL,
first VO line word count). Add the opener to meta.json arms (plan.arms already has it).

## 4. Gates → queue (per reel)
All of: truth gate passed, render QA PASS, voice ALL OK, stills looked at, no repeated topic, hook score >= 50.
If any fails → `reels/<id>/HOLD.md` with the reason, commit, and go on with the next reel (one HOLD does not
stop the day; three HOLDs in a row do: stop and notify Mert).
Otherwise:
```bash
python3 ops/publish.py prepare --reel <id> --video engine/reel_final.mp4 --live
```
(uploads the video and queues it for the slot; publish.yml publishes it. Writes are off while settings.auto_publish is false.)

After each `prepare`: commit `reels/<id>/` and `data/` (`git pull --rebase` first) and push to main.

## 5. Stories (settings.stories_per_day, slots settings.story_slots)
Stories only repeat what today's verified reels already say: no new claim, no new source. Per story create
`stories/<YYYYMMDD>_story_<NN>/script.json` {"frame": {...}, "from_reel": "reels/<id>", "sources": <that reel's
sources>} and meta.json {"id", "date", "slot"}. Frame types (engine/story.html): promo (a reel's hook + stamp),
rule (a quote copied word for word from the reel's sources + its section; story.py checks this), check (the
reel's checklist), myth (myth/fact from a myth reel), cta (Finder or gap-list set; "link in bio"). A day's five:
promo, rule, check, myth or a second rule, cta. Stickers (poll, link) cannot be added through the API.
```bash
cd engine && python3 story.py ../stories/<id> --still   # LOOK at engine/build/story_stills/story_<id>.png; QA must PASS
python3 story.py ../stories/<id>                         # build/story_<id>.mp4 (6 s)
cd .. && python3 ops/publish.py prepare --story stories/<id> --video engine/build/story_<id>.mp4 --live
```
Commit `stories/<id>/` and `data/` after each.

## 6. Finish
Notify Mert in one short message: reels queued / held (with reasons), stories queued, the brake note if any.
Never commit an mp4.

## Reel format: mise-en-scene (default since 2026-11-05, Mert)
Mert: "from now on make videos like this" (reels/sample_scene_port, published as 20261105_blocked_03). Every reel is an
acted, first-person story, not an explainer. `config/settings.json` `reel_format: "scene"`.
- Template: `engine/scene/scene.html` (port with workers + forklift → crane sets the container on a truck → pan to a
  generic customs gate, barrier stays down → office/desk with laptop checklist → flat end card with the CTA set and the
  brand card). The presenter (engine/scene/_ava2.svg) walks, gestures with two-part arms, tilts her head, blinks and
  lip-syncs to the voice. Female presenter = female voice (en-US-AvaNeural), always.
- Per reel write `reels/<id>/scene.json`: {id, voice, vo[5] (first person, scene 1 or caption 1 frames it as
  "Say I'm a seller…"), caps[4] ([headline, sub, cite]), min_dur[5], props {box, hold, phoneWho, phoneMsg,
  laptopTitle, rows[5], doc, gate, cta[4] (exact CTA set)}}. The story must fit the topic; when a topic needs a set the
  template lacks (warehouse, store shelf, home, retailer meeting), add it to scene.html as a new world group and keep
  the timeline a pure function of t. Never draw a real agency seal, Amazon/CPSC/UL logos or a real port name.
- Render: `cd engine/scene && python3 render_scene.py ../../reels/<id>/scene.json --stills ...` (LOOK at every still),
  then without --stills → `engine/build/scene_<id>.mp4`. Total 18–24 s (shorten VO lines when over).
- Same gates as before (verbatim sources + one adversarial verifier, hookscore on line 1, caption lint), then
  `python3 ops/publish.py prepare --reel <id> --video engine/build/scene_<id>.mp4 --live`.
- Iterate from the numbers (Mert: "change the start, the end, whatever the stats say"): each morning read
  `ops/metrics.py show`; when a scene reel's skip rate is worse than the last 3, change the first 2 s (set, first line,
  first motion) of the next one; when watch time drops mid-reel, cut the slowest beat. Record what changed in
  DELIVERABLE.md.

### Vary the story world every reel (Mert, 2026-11-13: "one format, not the same video every time; the port is only one of the events")
The format (acted first-person story, moving presenter, flat end card) stays. The EVENT and the SET must change:
- Never reuse a story world from the previous 4 reels. Record it in meta.json as `"world": "<name>"` and check
  reels/*/meta.json before writing. Used so far: `port_customs` (20261105_blocked_03, 20261106_myth_01, 20261113_myth_01),
  so the port is off limits for the next 4 reels.
- Worlds to draw from (add more; each is a different event a seller actually lives through):
  `listing_takedown` (home desk at night, phone buzzes, listing goes grey on a generic marketplace screen),
  `warehouse_inbound` (fulfillment dock refuses the pallets, cartons pile up), `retailer_meeting` (buyer's office, the
  item can't be set up, shelf stays empty), `lab_report` (test bench, report comes back with findings, launch calendar),
  `factory_call` (video call with the factory, "certified" PDF on screen), `broker_email` (broker asks for certificate
  data, clock running, storage fees meter), `launch_day` (packing table, ads running, sales counter stops),
  `customer_return` (doorstep delivery, complaint message, recall-style notice), `port_customs`.
- The worlds below are already drawn (engine/scene/worlds.html). A further new world = a new entry in its `W` registry
  (sets A/B/C + tick); different opening shot, different props, different middle beat. Also vary the first 2 s
  (where she is, what moves first) and the camera move between sets; only the end card stays the same.
- No real brand UI or logos in any set (generic marketplace/retailer screens only).

### Story worlds and the 2-month drawing schedule (Mert, 2026-11-13: "draw them all, decide what is drawn each day for the next two months, save it in DAILY.md; whichever is next gets drawn and published")
All nine worlds are drawn. `port_customs` renders from engine/scene/scene.html, the other eight from
engine/scene/worlds.html; set `"world": "<name>"` in scene.json and meta.json and render_scene.py picks the template.
- `listing_takedown`: night at the desk, the phone buzzes, the listing goes grey
- `warehouse_inbound`: truck backs into the dock, the receiving line stops, cartons refused
- `retailer_meeting`: buyer meeting, then the store aisle with one empty slot
- `lab_report`: test bench, the report prints with findings, launch calendar runs out
- `factory_call`: video call "it is certified", then zoom into the PDF that names another model
- `broker_email`: broker email lands, clock runs, storage days count up in the yard
- `launch_day`: launch-day packing table, then the sales line drops flat on the dashboard
- `customer_return`: doorstep delivery, the customer asks "is this tested?", the box comes back
- `port_customs`: ship docks, crane, truck stops at the customs gate (engine/scene/scene.html)

Each world has three sets (scene 1 = the event starts, scene 2 = the block, with the red stamp + message bubble,
scenes 3-4 = where she fixes the file, with the checklist panel), its own transition and presenter side, then the same
flat end card. Per-reel props: box (SKU), hold (stamp, <= 8 chars), gate (the sign/banner inside set B), phoneWho,
phoneMsg, say (speech bubble / email subject in factory_call and broker_email), doc, laptopTitle, rows[5], cta[4],
open (`walk` she walks in, `late` the set plays first and she rises in at 0.9 s, `pop` she is already there),
pose2 (`phone` or `shock`, her reaction in scene 2).

**How to use the table.** For reel k of today take the row with today's date and that reel number: the world and the
opening are fixed by the table, the pillar comes from the calendar (`strategy.py plan` gives the same pillar; hook,
length, CTA mode and slot still come from the plan). Write the first-person story for THAT event; the topic must fit
it and pass the usual truth gate. If a reel is held or a day is missed, do not shift the table: the next reel simply
takes its own row. If the numbers say a world works clearly better or worse (3+ reels each), swap rows inside the
same week but keep the rule "no world from the previous 4 reels", and note the swap in DELIVERABLE.md. When the
table runs out (after 2027-01-13), extend it with the same rule, ordered by skip rate of each world so far.

| date | reel | pillar | world | opening |
|---|---|---|---|---|
| 2026-11-13 Fri | 2 | finder | `factory_call` | late |
| 2026-11-14 Sat | 1 | finder | `launch_day` | pop |
| 2026-11-14 Sat | 2 | cost | `warehouse_inbound` | walk |
| 2026-11-15 Sun | 1 | cost | `broker_email` | late |
| 2026-11-15 Sun | 2 | blocked | `listing_takedown` | pop |
| 2026-11-16 Mon | 1 | blocked | `retailer_meeting` | walk |
| 2026-11-16 Mon | 2 | finder | `lab_report` | late |
| 2026-11-17 Tue | 1 | finder | `customer_return` | pop |
| 2026-11-17 Tue | 2 | gap | `factory_call` | walk |
| 2026-11-18 Wed | 1 | gap | `warehouse_inbound` | late |
| 2026-11-18 Wed | 2 | deadline | `port_customs` | pop |
| 2026-11-19 Thu | 1 | deadline | `launch_day` | walk |
| 2026-11-19 Thu | 2 | myth | `listing_takedown` | late |
| 2026-11-20 Fri | 1 | myth | `lab_report` | pop |
| 2026-11-20 Fri | 2 | finder | `retailer_meeting` | walk |
| 2026-11-21 Sat | 1 | finder | `customer_return` | late |
| 2026-11-21 Sat | 2 | cost | `broker_email` | pop |
| 2026-11-22 Sun | 1 | cost | `warehouse_inbound` | walk |
| 2026-11-22 Sun | 2 | blocked | `port_customs` | late |
| 2026-11-23 Mon | 1 | blocked | `listing_takedown` | pop |
| 2026-11-23 Mon | 2 | finder | `factory_call` | walk |
| 2026-11-24 Tue | 1 | finder | `launch_day` | late |
| 2026-11-24 Tue | 2 | gap | `lab_report` | pop |
| 2026-11-25 Wed | 1 | gap | `retailer_meeting` | walk |
| 2026-11-25 Wed | 2 | deadline | `port_customs` | late |
| 2026-11-26 Thu | 1 | deadline | `factory_call` | pop |
| 2026-11-26 Thu | 2 | myth | `customer_return` | walk |
| 2026-11-27 Fri | 1 | myth | `listing_takedown` | late |
| 2026-11-27 Fri | 2 | finder | `launch_day` | pop |
| 2026-11-28 Sat | 1 | finder | `lab_report` | walk |
| 2026-11-28 Sat | 2 | cost | `broker_email` | late |
| 2026-11-29 Sun | 1 | cost | `warehouse_inbound` | pop |
| 2026-11-29 Sun | 2 | blocked | `retailer_meeting` | walk |
| 2026-11-30 Mon | 1 | blocked | `port_customs` | late |
| 2026-11-30 Mon | 2 | finder | `factory_call` | pop |
| 2026-12-01 Tue | 1 | finder | `customer_return` | walk |
| 2026-12-01 Tue | 2 | gap | `lab_report` | late |
| 2026-12-02 Wed | 1 | gap | `broker_email` | pop |
| 2026-12-02 Wed | 2 | deadline | `launch_day` | walk |
| 2026-12-03 Thu | 1 | deadline | `retailer_meeting` | late |
| 2026-12-03 Thu | 2 | myth | `listing_takedown` | pop |
| 2026-12-04 Fri | 1 | myth | `factory_call` | walk |
| 2026-12-04 Fri | 2 | finder | `customer_return` | late |
| 2026-12-05 Sat | 1 | finder | `lab_report` | pop |
| 2026-12-05 Sat | 2 | cost | `warehouse_inbound` | walk |
| 2026-12-06 Sun | 1 | cost | `port_customs` | late |
| 2026-12-06 Sun | 2 | blocked | `broker_email` | pop |
| 2026-12-07 Mon | 1 | blocked | `retailer_meeting` | walk |
| 2026-12-07 Mon | 2 | finder | `launch_day` | late |
| 2026-12-08 Tue | 1 | finder | `factory_call` | pop |
| 2026-12-08 Tue | 2 | gap | `lab_report` | walk |
| 2026-12-09 Wed | 1 | gap | `warehouse_inbound` | late |
| 2026-12-09 Wed | 2 | deadline | `port_customs` | pop |
| 2026-12-10 Thu | 1 | deadline | `retailer_meeting` | walk |
| 2026-12-10 Thu | 2 | myth | `listing_takedown` | late |
| 2026-12-11 Fri | 1 | myth | `customer_return` | pop |
| 2026-12-11 Fri | 2 | finder | `launch_day` | walk |
| 2026-12-12 Sat | 1 | finder | `factory_call` | late |
| 2026-12-12 Sat | 2 | cost | `broker_email` | pop |
| 2026-12-13 Sun | 1 | cost | `warehouse_inbound` | walk |
| 2026-12-13 Sun | 2 | blocked | `port_customs` | late |
| 2026-12-14 Mon | 1 | blocked | `retailer_meeting` | pop |
| 2026-12-14 Mon | 2 | finder | `lab_report` | walk |
| 2026-12-15 Tue | 1 | finder | `customer_return` | late |
| 2026-12-15 Tue | 2 | gap | `factory_call` | pop |
| 2026-12-16 Wed | 1 | gap | `broker_email` | walk |
| 2026-12-16 Wed | 2 | deadline | `launch_day` | late |
| 2026-12-17 Thu | 1 | deadline | `port_customs` | pop |
| 2026-12-17 Thu | 2 | myth | `listing_takedown` | walk |
| 2026-12-18 Fri | 1 | myth | `lab_report` | late |
| 2026-12-18 Fri | 2 | finder | `retailer_meeting` | pop |
| 2026-12-19 Sat | 1 | finder | `customer_return` | walk |
| 2026-12-19 Sat | 2 | cost | `warehouse_inbound` | late |
| 2026-12-20 Sun | 1 | cost | `broker_email` | pop |
| 2026-12-20 Sun | 2 | blocked | `port_customs` | walk |
| 2026-12-21 Mon | 1 | blocked | `listing_takedown` | late |
| 2026-12-21 Mon | 2 | finder | `factory_call` | pop |
| 2026-12-22 Tue | 1 | finder | `launch_day` | walk |
| 2026-12-22 Tue | 2 | gap | `lab_report` | late |
| 2026-12-23 Wed | 1 | gap | `retailer_meeting` | pop |
| 2026-12-23 Wed | 2 | deadline | `port_customs` | walk |
| 2026-12-24 Thu | 1 | deadline | `factory_call` | late |
| 2026-12-24 Thu | 2 | myth | `customer_return` | pop |
| 2026-12-25 Fri | 1 | myth | `listing_takedown` | walk |
| 2026-12-25 Fri | 2 | finder | `launch_day` | late |
| 2026-12-26 Sat | 1 | finder | `lab_report` | pop |
| 2026-12-26 Sat | 2 | cost | `warehouse_inbound` | walk |
| 2026-12-27 Sun | 1 | cost | `broker_email` | late |
| 2026-12-27 Sun | 2 | blocked | `retailer_meeting` | pop |
| 2026-12-28 Mon | 1 | blocked | `port_customs` | walk |
| 2026-12-28 Mon | 2 | finder | `factory_call` | late |
| 2026-12-29 Tue | 1 | finder | `customer_return` | pop |
| 2026-12-29 Tue | 2 | gap | `lab_report` | walk |
| 2026-12-30 Wed | 1 | gap | `warehouse_inbound` | late |
| 2026-12-30 Wed | 2 | deadline | `launch_day` | pop |
| 2026-12-31 Thu | 1 | deadline | `retailer_meeting` | walk |
| 2026-12-31 Thu | 2 | myth | `listing_takedown` | late |
| 2027-01-01 Fri | 1 | myth | `factory_call` | pop |
| 2027-01-01 Fri | 2 | finder | `customer_return` | walk |
| 2027-01-02 Sat | 1 | finder | `lab_report` | late |
| 2027-01-02 Sat | 2 | cost | `broker_email` | pop |
| 2027-01-03 Sun | 1 | cost | `port_customs` | walk |
| 2027-01-03 Sun | 2 | blocked | `warehouse_inbound` | late |
| 2027-01-04 Mon | 1 | blocked | `retailer_meeting` | pop |
| 2027-01-04 Mon | 2 | finder | `launch_day` | walk |
| 2027-01-05 Tue | 1 | finder | `factory_call` | late |
| 2027-01-05 Tue | 2 | gap | `lab_report` | pop |
| 2027-01-06 Wed | 1 | gap | `broker_email` | walk |
| 2027-01-06 Wed | 2 | deadline | `port_customs` | late |
| 2027-01-07 Thu | 1 | deadline | `retailer_meeting` | pop |
| 2027-01-07 Thu | 2 | myth | `listing_takedown` | walk |
| 2027-01-08 Fri | 1 | myth | `customer_return` | late |
| 2027-01-08 Fri | 2 | finder | `launch_day` | pop |
| 2027-01-09 Sat | 1 | finder | `factory_call` | walk |
| 2027-01-09 Sat | 2 | cost | `warehouse_inbound` | late |
| 2027-01-10 Sun | 1 | cost | `broker_email` | pop |
| 2027-01-10 Sun | 2 | blocked | `port_customs` | walk |
| 2027-01-11 Mon | 1 | blocked | `retailer_meeting` | late |
| 2027-01-11 Mon | 2 | finder | `lab_report` | pop |
| 2027-01-12 Tue | 1 | finder | `customer_return` | walk |
| 2027-01-12 Tue | 2 | gap | `factory_call` | late |
| 2027-01-13 Wed | 1 | gap | `warehouse_inbound` | pop |
| 2027-01-13 Wed | 2 | deadline | `launch_day` | walk |
