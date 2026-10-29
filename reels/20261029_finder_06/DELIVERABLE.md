# Reel 20261029_finder_06: Selling coin or button batteries on their own? Look at the package first.

Slot 10:47 America/New_York. Arms: hook callout, opener slam, length short, voice andrew, cta_mode comment.

## Caption
Selling coin or button batteries on their own? Look at the package first.
16 CFR 1263.4 sets labeling rules for button cell and coin battery packaging: a warning label on the principal display panel (if space is tight, the icon there and the text on a secondary panel), in English, clearly visible and legible.
The signal word WARNING and the safety alert symbol are black on orange, unless only one color is present or that would hurt visibility.
The free CPSC Finder has a battery product family.
Not sure which rules apply? Comment M&Z and we'll DM you the free CPSC Finder.
#amazonseller #cpsc #productcompliance #importing #privatelabel

## First comment (pin by hand)
Not sure which rules apply? Comment M&Z and we'll DM you the free CPSC Finder.

## Tracking link
https://mzconsulting.agency/cpsc-compliance-finder?family=battery_product&src=ig_20261029_finder_06

## Sources
| claim | section | quote |
|---|---|---|
| Coin/button battery packaging: warning label on the principal display panel, English, WARNING black on orange | 16 CFR 1263.4(a)(1), (3), (5), (b)(1) | "(1) All warning statements must be clearly visible, prominent, legible, and permanently marked. ... (3) Warning statements must be in English. ... (5) The signal word “WARNING” and safety alert symbol must be in black le…" |
| If space prohibits: icon on PDP, text on secondary panel | 16 CFR 1263.4(b)(2) | "(2) If space prohibits the full warning label shown in figure 1 to paragraph (b)(1), place the icon shown in figure 2 to this paragraph (b)(2) on the principal display panel with the text shown in figure 3 to this paragr…" |

## QA
| check | result |
|---|---|
| Duration | PASS — 19.0 s (short) |
| Voice fit | PASS — voice.py ALL OK |
| Stills | PASS — frames 0, 0.5, each scene, last frame viewed (contact sheet) |
| Safe zone / limits | PASS — render.py QA |
| CTA set | PASS — comment_finder set verbatim; last VO line says it |
| Truth gate | FAIL (fixable) -> fixed (PDP label exception 1263.4(b)(2) added) (batch adversarial verifier, eCFR 2026-10-19) |
| Topic not repeated (14 days + today) | PASS |
| Opener / hook | slam / callout (#14 The Callout) |
| Hook score | PASS — 56.0 for "Selling button batteries? The box needs WARNING." (scored with digits; VO spells numbers out: "Selling button batteries? The box needs WARNING.") |
| First VO line | 7 words |
| beats.py flags | Beat(s) 2 run past 4s. Either split the line or change what is on screen inside it. A static frame is where people leave.; No loop. The last beat shares no word with the hook, so the video ends flat. Echoing one word from beat 1 is the cheapest replay you get. |
| Caption lint | REVIEW (search terms: coin battery,warning label) |
| Human score (caption) | 63.3 REVIEW |
