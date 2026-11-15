# Reel 20261115_cost: POV cost of waiting: shipment in storage, certificate only in Chinese, broker can't file; 16 CFR 1110.9(a) English requirement

Format: mise-en-scene, world `broker_email`, opening `walk` (schedule row 2026-11-15 in ops/DAILY.md), Ava voice, slot 14:47 America/New_York.
First reel with the offer band from frame 0 ("Get your gap list in 24 hours · mzconsulting.agency") and the 1-reel/day plan.

## Caption
Say your customs broker asks for an English certificate while the shipment waits in storage.
16 CFR 1110.9(a): an eFiled certificate must be in English, and every other certificate must be in English too. It may also carry the same content in another language.
Say a seller's factory sent the certificate in Chinese only. An English version comes first; every day without it can add storage costs.
Blocked right now? Forward the notice, gap list in 24h: link in bio
#amazonseller #cpsc #productcompliance #importing #privatelabel

## First comment (pin by hand)
Blocked right now? Forward the notice, gap list in 24h: link in bio

## Tracking link
https://mzconsulting.agency/?src=ig_20261115_cost#contact

## Sources (eCFR as of 2026-11-12)
| claim | section | quote |
|---|---|---|
| Certificates must be in English; other languages may be added with the same content | 16 CFR 1110.9(a) | "An eFiled finished product certificate must be in the English language. All other certificates, including hard copy and electronic certificates, must be in the English language and may also contain the same content in any other language." |

## QA
| check | result |
|---|---|
| Duration | PASS — 21.0 s (fit before the final verifier pass) |
| Voice | PASS — 5 TTS lines, en-US-AvaNeural; each scene gap = line + 0.25 s or min_dur |
| Stills | PASS — 0, 0.6, 2.5, 5.5, 7, 9.5, 13, 16.5 s viewed; offer band visible from frame 0 |
| Text limits | PASS — headlines <= 17, subs <= 49, stamp 7 |
| CTA set | PASS — GAP LIST set verbatim; last VO line says it |
| Truth gate | PASS — independent verifier re-fetched part 1110; first pass FAIL (caption line 1 unframed, VO3 dropped "same content"), fixes applied, final wording re-checked: PASS |
| Topic not repeated (14 days) | PASS — 1110.9(a) last used 2026-10-28 |
| Hook score | PASS — 80.8 "Day four in storage. My certificate? Chinese only." |
| Caption lint | READY |
| Human score (caption) | 71.3 PASS |
