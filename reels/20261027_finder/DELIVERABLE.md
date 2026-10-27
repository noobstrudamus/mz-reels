# Reel 20261027_finder — Finder demo (toy): a toy CPC that cites only part 1250

Slot: 09:47 America/New_York (2026-10-27T13:47Z). Arms: hook cost, opener slam, length short, voice ava, cta_mode playbook (explore day).

## Caption
Toys stuck on hold, and the certificate cites one rule?
A children's toy certificate (CPC) has to list every applicable rule separately, not just the toy standard.
16 CFR part 1250 makes the applicable parts of ASTM F963-23 mandatory for toys. A painted toy for kids usually also falls under the lead paint ban, 16 CFR 1303.
A toy for children under 3 also falls under the small parts rule, 16 CFR 1501.
Free CPSC Finder, no account: link in bio
#amazonseller #cpsc #productcompliance #importing #privatelabel

## First comment (pin manually)
Free CPSC Finder, no account: link in bio

## Tracking link
https://mzconsulting.agency/cpsc-compliance-finder?family=toy&src=ig_20261027_finder

## Sources (current eCFR, Title 16 issue 2026-10-19)
| claim | source | verbatim quote |
|---|---|---|
| Every applicable rule listed separately | [16 CFR 1110.11(a)(2)](https://www.ecfr.gov/current/title-16/part-1110/section-1110.11) | "Finished product certificates must identify separately all applicable rules, bans, standards, or regulations." |
| Part 1250 = toy standard, F963-23 mandatory | [16 CFR 1250.1–1250.2(a)](https://www.ecfr.gov/current/title-16/part-1250) | "This part establishes a consumer product safety standard for toys." / "Each toy must comply with all applicable provisions of ASTM F963-23" |
| Existing bans are carved out of 1250 | [16 CFR 1250.2(b)](https://www.ecfr.gov/current/title-16/part-1250/section-1250.2) | "…any provision of ASTM F963 that restates or incorporates an existing mandatory standard or ban … are not part of the mandatory standard…" |
| Lead paint ban covers kids' toys with lead-containing paint | [16 CFR 1303.1(a)(1)](https://www.ecfr.gov/current/title-16/part-1303) | "Toys and other articles intended for use by children that bear 'lead-containing paint'." |
| Small parts: toys for under 3 | [16 CFR 1501.2(a)](https://www.ecfr.gov/current/title-16/part-1501/section-1501.2) | "applies to all toys and other articles intended for use by children under 3 years (36 months) of age" |
| Children's product = 12 and under → CPC | [16 CFR 1200.2(a)(1)](https://www.ecfr.gov/current/title-16/part-1200/section-1200.2) | "…designed or intended primarily for children 12 years of age or younger." |

## QA
| check | result |
|---|---|
| Duration 18–24 s (arm short 18–20) | PASS — 19.9 s |
| Voice fit | PASS — ALL OK, 46 words |
| Opener / hook | slam ("ON HOLD" lands at 0.15 s) / cost ("toys sit on hold") |
| Mute test (frames 0 and 0.5 s) | PASS — headline "Toy cert lists one rule?" + framing note on frame 0; stamp readable at 0.5 s |
| First VO line | PASS — 7 words |
| Stills checked | PASS — frames 0, 0.5, 1.2, 4, 8.5, 13, 14, 17, 19.6 viewed; red = gap, blue = fix |
| Safe zone / limits | PASS — render.py QA |
| CTA set | PASS — FINDER set verbatim; last VO line says it |
| Truth gate | PASS — adversarial verifier: 2 overclaims fixed ("At least two are missing", "Usually add 1303"); CPC only, no GCC; fictional SKU |
| Topic not repeated (14 days) | PASS — 10-22 certifier, 10-23 test≠cert, 10-24 electric toys 1505 |

## Notes
- Previous skip rates: 87% (10-22), 93% (10-23). Today's opening differs: the stamp hits at 0.15 s instead of 0.9 s, and the first line states the cost ("toys sit on hold").
- Engine fix: the CTA line2 limit went from 40 to 41 characters, because the playbook's own FINDER line2 is 41 characters.
- 25 and 26 October had no reel: the routine firings reached the session two days late.
- In replies, don't say every painted toy fails without 1303: the ban covers lead-containing paint, and certifying to it is the usual practice.
