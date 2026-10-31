# Reel 20261031_cost_02: Shipping baby swings for Q4? Check 16 CFR part 1223 first.

Slot 08:47 America/New_York. Arms: hook callout, opener slam, length long, voice ava, cta_mode comment.

## Caption
Shipping baby swings for the holidays? Check 16 CFR part 1223 first.
Since July 25, 2026, the rule says each infant and cradle swing, including combination swings, must comply with ASTM F2088-25. Before that date, it cited F2088-24.
If your test reports and certificate file only point to the 2024 version, check them against the current rule before the holiday shipment.
Your certificate must list each applicable rule, like part 1223, separately (16 CFR 1110.11(a)(2)).
Want a free gap list? Comment M&Z and we'll DM you the link.
#amazonseller #cpsc #productcompliance #importing #privatelabel

## First comment (pin by hand)
Want a free gap list? Comment M&Z and we'll DM you the link.

## Tracking link
https://mzconsulting.agency/?src=ig_20261031_cost_02#contact

## Sources
| claim | section | quote |
|---|---|---|
| Infant and cradle swings: ASTM F2088-25 | 16 CFR 1223.2 | "Each infant and cradle swing (including combination swings) must comply with all applicable provisions of ASTM F2088-25, Standard Consumer Safety Specification for Infant and Cradle Swings, approved on November 15, 2025." |
| Before: ASTM F2088-24 | 16 CFR 1223.2 as of 2026-07-24 (eCFR point-in-time) | "Link to an amendment published at 91 FR 20880, Apr. 20, 2026. Each infant and cradle swing (including combination swings) must comply with all applicable provisions of ASTM F2088-24, Standard Consumer Safety Specificatio…" |
| Swing rule changed July 25, 2026 | 16 CFR 1223.2, eCFR version history | "§ 1223.2 'Requirements for infant and cradle swings.' amendment_date 2026-07-25" |
| Every applicable rule listed separately | 16 CFR 1110.11(a)(2) | "Finished product certificates must identify separately all applicable rules, bans, standards, or regulations." |

## QA
| check | result |
|---|---|
| Duration | PASS — 22.6 s (long) |
| Voice fit | PASS — voice.py ALL OK |
| Stills | PASS — frames 0, 0.5, each scene, last frame viewed (contact sheet) |
| Safe zone / limits | PASS — render.py QA |
| CTA set | PASS — comment_gaplist set verbatim; last VO line says it |
| Truth gate | FAIL (fixable) -> fixed (older edition not called wrong; check against current rule; holidays wording) (batch adversarial verifier, eCFR 2026-10-19) |
| Topic not repeated (14 days + today) | PASS |
| Opener / hook | slam / callout (#14 The Callout + #19 The Deadline) |
| Hook score | PASS — 59.0 for "Selling baby swings? Check 1223 before the holidays." (scored with digits; VO spells numbers out: "Selling baby swings? Check twelve twenty-three before the holidays.") |
| First VO line | 9 words |
| beats.py flags | Beat 1 takes 3.3s to say. Cut it to 8 words or fewer, or the hook lands after the decision has been made.; Beat(s) 2, 4, 5 run past 4s. Either split the line or change what is on screen inside it. A static frame is where people leave.; No loop. The last beat shares no word with the hook, so the vide |
| Caption lint | REVIEW (search terms: baby swing,ASTM F2088) |
| Human score (caption) | 74.8 REVIEW |
