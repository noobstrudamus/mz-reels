# Daily reel run (the scheduled routine follows this exactly)

Runs every day at 06:47 America/New_York in a fresh cloud session with this repo checked out.
Goal: one verified reel queued for today's slot. GitHub Actions (publish.yml) publishes it at the slot.

## 0. Setup
```bash
pip install -q -r requirements.txt
python3 -c "import sys; sys.path.insert(0,'ops'); from ig import IG; print(IG().check_token())"   # must print mzconsulting.llc
```
If the token check fails (TokenExpired): stop, write `reels/HOLD_<date>.md`, commit, notify Mert. Do not continue.

## 1. Plan
`python3 ops/strategy.py plan` → JSON (id, pillar, cta, arms, voice_name, length_rule, hook_rule, slot, src, tracking_link,
keyword, dm_link, caption_cta, notes). Use it as-is; never override the strategy by taste. Create `reels/<id>/meta.json`
with {id, date, pillar, cta, arms, family}.

## 2. Script (2 agents max: one writer, one adversarial verifier)
- Read CLAUDE.md (playbook). Re-read mzconsulting.agency on Mondays. Check `reels/*/script.json` from the last 14 days: no repeated topic.
- Writer: draft the 5 scenes + 5 VO lines for the pillar using hook_rule and length_rule, the CTA set for `cta`
  (gaplist / finder / comment_gaplist / comment_finder, exactly as in engine/reel.html CTA_SETS), and only claims with a
  verbatim quote from current ecfr.gov (versioner API, --compressed, latest issue date) / cpsc.gov / fcc.gov.
- Verifier (fresh agent): re-fetch every source, refute overclaims, enforce limits. Anything unverifiable is removed.
- Write `reels/<id>/script.json` (scenes, vo, caption, pinned_comment, tracking_link, sources). Caption line 5 and
  pinned comment = plan.caption_cta for comment arms, otherwise the playbook CTA line.

## 3. Render
In engine/: put the scenes into the REEL object (meta: id, pillar, cta, voice = plan.voice_name, footnote
"Illustrative example. Not legal advice."), write vo.txt, then:
```bash
python3 voice.py --fit          # must print ALL OK; total must stay within the length_rule range
python3 render.py --stills <one mid-point per scene + last frame>   # LOOK at every PNG, fix, repeat
python3 render.py && python3 build_audio.py
```
Write `reels/<id>/DELIVERABLE.md` with the QA table.

## 4. Gates → queue
All of: truth gate passed, render QA PASS, voice ALL OK, stills looked at, no repeated topic.
If any fails → `reels/<id>/HOLD.md` with the reason, commit, notify Mert, stop.
Otherwise:
```bash
python3 ops/publish.py prepare --reel <id> --video engine/reel_final.mp4 --live
```
(uploads the video and queues it for the slot; publish.yml publishes it. Writes are off while settings.auto_publish is false.)

## 5. Finish
Commit `reels/<id>/` and `data/` (`git pull --rebase` first), push to main. Notify Mert in one short message:
topic, arms, slot, and the HOLD reason if any. Do not attach the mp4 to git.
