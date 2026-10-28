# Reel 20261028_cost_05: If CBP asked for your certificate today, could you send it by tomorrow?

Slot 17:47 America/New_York. Arms: hook pain_quote, opener slam, length short, voice andrew, cta_mode playbook.

## Caption
If CBP asked for your certificate today, could you send it by tomorrow?
Under 16 CFR 1110.13(c), certifiers make certificates available immediately, meaning within 24 hours, when CPSC or CBP asks.
"Let me ask the factory" can take longer than that.
Keep the CPSC certificate and its records on file before a certificate request comes in.
Blocked right now? Forward the notice, gap list in 24h: link in bio
#amazonseller #cpsc #productcompliance #importing #privatelabel

## First comment (pin by hand)
Blocked right now? Forward the notice, gap list in 24h: link in bio

## Tracking link
https://mzconsulting.agency/?src=ig_20261028_cost_05#contact

## Sources
| claim | section | quote |
|---|---|---|
| Available within 24 hours on request by CPSC or CBP | 16 CFR 1110.13(c) | "Finished product certifiers must make finished product certificates available for inspection immediately, meaning within 24 hours, upon request by CPSC or CBP." |
| Certifiers keep certificates and supporting test records 5+ years | 16 CFR 1110.17 | "Finished product certifiers are required to maintain finished product certificates and the following records supporting such certificates for at least five years from the certificate creation date: (a) Records of test re…" |

## QA
| check | result |
|---|---|
| Duration | PASS — 19.9 s (short) |
| Voice fit | PASS — voice.py ALL OK |
| Stills | PASS — frames 0, 0.5, each scene, last frame viewed (contact sheet) |
| Safe zone / limits | PASS — render.py QA |
| CTA set | PASS — gaplist set verbatim; last VO line says it |
| Truth gate | FAIL (fixable) -> fixed ('within', checklist headline, 'can take') (batch adversarial verifier, eCFR 2026-10-19) |
| Topic not repeated (14 days + today) | PASS |
| Opener / hook | slam / pain_quote (#19 Deadline (24 h)) |
| Hook score | PASS — 54.8 for "CBP asks. You have 24 hours." (scored with digits; VO spells numbers out: "CBP asks. You have twenty-four hours.") |
| First VO line | 6 words |
| beats.py flags | Beat(s) 2, 4, 5 run past 4s. Either split the line or change what is on screen inside it. A static frame is where people leave.; Loops: the last beat repeats "hours, twenty-four" from the hook. Second watches are free reach. |
| Caption lint | READY (search terms: CPSC certificate,certificate request) |
| Human score (caption) | 62.1 REVIEW |
