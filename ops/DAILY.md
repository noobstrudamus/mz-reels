# Daily reel run (the scheduled routine follows this exactly)

Runs every day at 06:47 America/New_York (catch-up firings later in the day continue it).
Goal: settings.reels_per_day verified reels (10 since 2026-10-28, halved automatically by the strategy's
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
opener = plan.opener, kicker (kicker opener only), footnote "Illustrative example. Not legal advice."),
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
