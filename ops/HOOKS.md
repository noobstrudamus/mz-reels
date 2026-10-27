# Hook bank: the first 2 seconds

Our first reels lost 87–93% of viewers before second 3 (reels_skip_rate), with 1.5–2.4 s average watch time.
The opening is now the main thing we test. `ops/strategy.py plan` picks a **hook** (what we say) and an
**opener** (how the first second is staged). This file is how the writer turns those two picks into the
first frame and the first voice line.

## Rules for every opening (all hook styles)

1. **Mute test.** Frame 0 must make sense with no sound. It needs a readable headline, kicker or stamp
   word, at most 7 words. Most people scroll Reels muted.
2. **First spoken line has at most 7 words.** It has to be finished before the viewer decides to scroll
   (about 1.5 s). The detail goes in line 2.
3. **Use the buyer's nouns.** Write *ASIN, listing, container, broker, lab report, certificate, CPC, GCC,
   Seller Central notice, launch date*. Never write *compliance solutions* or *regulatory journey*.
4. **Open a loop.** Name a problem or a wrong belief, then hold back the fix until scene 3 or 4.
5. **Truth rules still apply to the hook.**
   - No invented numbers, clients or results.
   - No "Amazon will approve".
   - No Amazon, CPSC or UL logos, and no screens that look like Amazon.
   - The scenario has to be framed as "say a seller…" somewhere in scene 1 (VO or on-screen note). The
     punch comes first and the framing second: **the first spoken words are never "Say a seller"**.
     hookscore.py rates every "Say a seller…" opener WEAK (30/100), because the framing pushes the
     claim out of the first two seconds. Put the framing in the scene 1 note or VO sentence 2.
   - Never offer a "free test report". We are not a lab.
6. **The hook headline does not repeat the caption's first line.** The caption rewords it.

## Openers (engine `meta.opener`)

| opener | first second | the writer supplies |
|---|---|---|
| `classic` | headline on frame 0, stamp lands at 0.9 s | retired from rotation 2026-10-24 (87–93% skip); engine default for old reels |
| `slam` | headline on frame 0, stamp lands at 0.15 s with a punch | a stamp word that is the verdict: `BLOCKED`, `ON HOLD`, `MYTH`, `WRONG`, `CHECK`, `MISSING` (≤ 8 chars) |
| `kicker` | 2–4 huge words fill the screen for 1 s, then scene 1 | `meta.kicker` ≤ 22 chars; the first VO words say the same words; scene 1 dur ≥ 3 s |

## Hook styles × pillars: starting lines

These are templates, not scripts. Rotate them, never reuse the exact same line within 14 days, and back
any rule they mention with a verified quote.

### `callout`: name the viewer in the first three words
| pillar | kicker / headline | first VO line |
|---|---|---|
| blocked | "Amazon seller?" | "Amazon seller with a blocked listing?" |
| finder | "Importing kids' toys?" | "Importing toys into the US?" |
| gap | "Private-label brand?" | "Private-label brand? Check this field." |
| deadline | "Selling kids' products?" | "Selling kids' products? This changed." (only with a verified date) |
| myth | "Got a lab report?" | "Got a passing lab report? Wait." |
| cost | "Container on hold?" | "Container on hold at the port?" |

### `consequence`: the end state first, then rewind
| pillar | kicker / stamp | first VO line, then line 2 |
|---|---|---|
| blocked | stamp `BLOCKED` | "Listing blocked. Lab report sent twice." → "Say a seller…" |
| gap | stamp `MISSING` | "One missing line. Whole shipment held." → name the field |
| cost | stamp `ON HOLD` | "Container's on hold. Launch date isn't." |
| myth | stamp `WRONG` | "Passed the test. Still rejected." |

### `question`: a yes/no question the buyer answers "yes" to
- "Did Seller Support send the same template twice?"
- "Does your certificate name the factory as certifier?" (only on a certifier-gap reel, 16 CFR 1110.7)
- "Is your kids' product on a GCC?" (CPC/GCC never mixed)

### `pain_quote`: the buyer's own words (playbook quotes), reworded
- "'We sent the lab report. Twice.'"
- "'The broker wants certificate data we don't have.'"
- "'The factory says it's certified.'"
These work best with the `kicker` opener: the quote is the kicker.

### `myth`: name the belief, flip it
- Kicker "Test report = certificate?" → stamp `MYTH`.
- "Made overseas, so the factory certifies it?" → stamp `WRONG` (importer certifies, 1110.7(a)).

### `cost`: the cost of waiting (no invented numbers)
- "Every day on hold costs something. Here's the fix." Use only prices and dates from the site or a
  verified source. Never a made-up dollar figure.

## Lines that are not allowed
- "You won't believe…", "Nobody talks about this", "99% of sellers…" (invented number), or any line that
  promises approval.
- Questions answered "no" by most viewers ("Do you love compliance?").
- An opening that names M&Z before the problem. The brand is already in the header.

## Feedback loop
- `ops/metrics.py` collects `skip_rate` and `avg_watch_time_ms` per reel every morning. Since 2026-10-24
  `ops/strategy.py` scores skip rate (20% of the proxy), so openers that keep viewers past the first
  seconds win the opener and hook factors.
- Daily run, step 1: read the last 7 days in `python3 ops/strategy.py status`. If the latest scored reel
  had skip_rate > 80%, write one line in today's DELIVERABLE.md saying what today's opening does
  differently, still inside the plan's arms.
- Sunday report: list skip rate and average watch time per reel next to its hook and opener. Retire a
  bank line after 2 reels above 85% skip.

## Scoring with the instagram-agent pack (installed 2026-10-27, `.claude/skills/ig-*`)

The pack ([Jakeschincariol/instagram-agent-skill](https://github.com/Jakeschincariol/instagram-agent-skill),
MIT) adds 26 hook formulas (`.claude/skills/ig-reel/hooks.json`) and local scoring tools. Our TRUTH RULES and
CTA sets override the pack wherever they disagree. One difference: the pack ends at "the user posts it"; our
routine publishes automatically behind the hard gates in CLAUDE.md.

**Hook arm → formulas to draft from** (write 3 candidates from different formulas, then score):

| plan.hook | formulas (hooks.json id) | M&Z-safe example (score) |
|---|---|---|
| pain_quote | #12 The Objection, #16 Verbatim Question | "\"We sent the lab report twice.\" Here's the line that was missing." (49.8, add stakes) |
| question | #10 If This Then Watch, #16 Verbatim Question | "Kids' product on a general certificate? That's the wrong form." (51.0) |
| myth | #2 Negative Command, #20 Permission, #22 Contrarian Flip | "Stop sending Seller Support the lab report. Send the certificate." (81.8) / "You usually don't need another lab test. You need the right certificate." (76.4) |
| cost | #19 The Deadline (real dates only), #7 Wrong Way Right Way | "Lab report passed. Certificate failed." (56.0) |
| callout | #14 The Callout | "Amazon sellers importing kids' products: check line three of your certificate." (46.8, add stakes) |
| consequence | #13 Before And After, #21 Mid-Sentence Start | "...and that's when the broker asked for the certificate." |
| (any) | #17 Head To Head | "Lab report versus certificate. Only one of them gets you unblocked." (85.6) |

**Off limits for us until real, publishable proof exists** (config/voice.md): #1 Cost Confession, #5 Time
Collapse, #6 The Receipt, #15 The Flop Record, #25 Someone Else's Result. #23 The Statistic only with a
number quoted from cpsc.gov / ecfr.gov / fcc.gov.

**Measured on our first four reels** (2026-10-27): every "Say a seller…" opener 30.0 WEAK; "The factory says
it's certified. The PDF doesn't say what you think." 60.8 OK. Skip rates were 87–93%.

**Required tool runs per reel** (record the numbers in DELIVERABLE.md):
- `python3 .claude/skills/ig-reel/hookscore.py hooks.txt`: 3 candidates. **The chosen first VO line must
  score ≥ 50**, or rewrite. Prefer the top one unless it breaks a truth rule.
- `python3 .claude/skills/ig-reel/beats.py engine/vo.txt --target <seconds> --wpm 165`: fix the hook >3 s
  flag and the "no loop" flag (the last line echoes one word from line 1, e.g. "certificate").
- `python3 .claude/skills/ig-human/humanize.py caption.txt -o clean.txt --report`, then `detect.py`: the
  caption and VO should reach PASS (≥ 70). Rewrite flagged structures by hand. Never change a quoted rule.
- `python3 .claude/skills/ig-caption/caption.py caption.txt --keywords "<2 search phrases>"`: no FAIL. Put
  the phrases a seller would type (e.g. "children's product certificate", "Amazon CPC") into the caption body
  as plain words. Line 1 should hold one concrete name or number (a rule number counts).
