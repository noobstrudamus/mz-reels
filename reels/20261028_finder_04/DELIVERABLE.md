# Reel 20261028_finder_04: A GCC on a kids' product is the wrong certificate.

Slot 15:47 America/New_York. Arms: hook consequence, opener slam, length short, voice ava, cta_mode comment.

## Caption
A GCC on a kids' product is usually the wrong certificate.
Under 16 CFR 1200.2, a children's product is one designed or intended primarily for children 12 and under, judged by four factors: the label, the marketing, how buyers see it, and the age guidelines.
Children's products subject to a CPSC rule get a Children's Product Certificate (CPC), not a GCC.
The free CPSC Finder asks for the intended age group, for this reason.
Not sure which rules apply? Comment M&Z and we'll DM you the free CPSC Finder.
#amazonseller #cpsc #productcompliance #importing #privatelabel

## First comment (pin by hand)
Not sure which rules apply? Comment M&Z and we'll DM you the free CPSC Finder.

## Tracking link
https://mzconsulting.agency/cpsc-compliance-finder?family=childrens_product&src=ig_20261028_finder_04

## Sources
| claim | section | quote |
|---|---|---|
| Children's product = 12 and under; four factors | 16 CFR 1200.2(a)(1) | "a children's product means a consumer product designed or intended primarily for children 12 years of age or younger. ... These factors are: (i) A statement by a manufacturer about the intended use of such product, inclu…" |
| CPC vs GCC | 16 CFR 1110.3 | "Children's Product Certificate (CPC) means a certificate of compliance for a finished product issued pursuant to section 14(a)(2) of the CPSA ... General Certificate of Conformity (GCC) means a certificate of compliance …" |
| A certificate is needed when a rule applies | 16 CFR 1110.5 | "Finished products subject to a consumer product safety rule under the CPSA, or similar rule, ban, standard, or regulation under any other law enforced by the Commission, which are imported for consumption or warehousing,…" |

## QA
| check | result |
|---|---|
| Duration | PASS — 19.9 s (short) |
| Voice fit | PASS — voice.py ALL OK |
| Stills | PASS — frames 0, 0.5, each scene, last frame viewed (contact sheet) |
| Safe zone / limits | PASS — render.py QA |
| CTA set | PASS — comment_finder set verbatim; last VO line says it |
| Truth gate | FAIL (fixable) -> fixed (Finder claim, 'usually a CPC') (batch adversarial verifier, eCFR 2026-10-19) |
| Topic not repeated (14 days + today) | PASS |
| Opener / hook | slam / consequence (#13 Before/After (consequence)) |
| Hook score | PASS — 59.6 for "Wrong certificate. Wrong age group." (scored with digits; VO spells numbers out: "Wrong certificate. Wrong age group.") |
| First VO line | 5 words |
| beats.py flags | Beat(s) 4 run past 4s. Either split the line or change what is on screen inside it. A static frame is where people leave.; No loop. The last beat shares no word with the hook, so the video ends flat. Echoing one word from beat 1 is the cheapest replay you get. |
| Caption lint | REVIEW (search terms: children's product certificate,CPC vs GCC) |
| Human score (caption) | 81.3 PASS |
