# Reel 20261024_finder — Finder demo (electrical): 120-volt kids' toy, CPC vs GCC, 16 CFR 1505 package labels

Slot: 15:47 America/New_York (2026-10-24T19:47Z). Arms: hook pain_quote, length short, voice ava, cta_mode comment.

## Caption
Your factory says the wall-powered toy is certified. Certified to which rule?
Who it's made for decides the paperwork: children's products get a CPC, general-use products a GCC, when a CPSC rule applies.
Most toys for kids that run on 120-volt wall power fall under their own CPSC rule, 16 CFR part 1505 (video games are excluded).
That rule also sets what goes on the package: electrical ratings, required warnings, and the month and year it was made (or a date code).
Not sure which rules apply? Comment M&Z and we'll DM you the free CPSC Finder.
#amazonseller #cpsc #productcompliance #importing #privatelabel

## First comment (pin manually — the Instagram API cannot pin)
Not sure which rules apply? Comment M&Z and we'll DM you the free CPSC Finder.

## Tracking link
https://mzconsulting.agency/cpsc-compliance-finder?family=electrical&src=ig_20261024_finder (DM link: src=ig_20261024_finder_dm)

## Sources (current eCFR, Title 16 issue 2026-10-19)
| claim | source | verbatim quote |
|---|---|---|
| Certificate needed when a CPSC rule applies | [16 CFR 1110.5](https://www.ecfr.gov/current/title-16/part-1110/section-1110.5) | "Finished products subject to a consumer product safety rule … must be accompanied by a finished product certificate." |
| CPC vs GCC are the two finished product certificates | [16 CFR 1110.3](https://www.ecfr.gov/current/title-16/part-1110/section-1110.3) | "There are two types of finished product certificates: Children's Product Certificates (CPCs) and General Certificates of Conformity (GCCs)." |
| Part 1505 scope: kids' toys on 120 V branch circuits; exclusions | [16 CFR 1505.1(a)(1)](https://www.ecfr.gov/current/title-16/part-1505/section-1505.1) | "…intended to be powered by electrical current from nominal 120 volt (110-125 v.) branch circuits. … does not include components which are powered by circuits of 30 volts r.m.s. … or video games." |
| Part 1505 is the rule such toys must meet to not be banned | [16 CFR 1505.2](https://www.ecfr.gov/current/title-16/part-1505/section-1505.2) | "…are not banned toys or banned articles under § 1500.18(b)(1) of this chapter." |
| Package: ratings, required warnings, month/year or code | [16 CFR 1505.3(b)(2)](https://www.ecfr.gov/current/title-16/part-1505/section-1505.3) | "(i) The date (month and year) of manufacture (or appropriate codes). (ii) The electrical ratings … (iii) Any precautionary statements required by paragraph (e)…" |

## QA
| check | result |
|---|---|
| Duration 18–24 s | PASS — 20.2 s (arm "short" targets 18–20 s; 0.2 s over because voice.py --fit rounds each scene up to 0.1 s) |
| Voice fit (voice.py) | PASS — ALL OK, 51 words, spare 0.33–0.38 s per scene |
| Stills checked | PASS — 6 stills, every scene + last frame, viewed; no overflow; red = problem (GCC sent / missing), blue = ok (CPC / Part 1505) |
| Text inside safe zone | PASS — render.py QA |
| CTA set used | PASS — comment_finder set verbatim; last VO line says it aloud |
| Truth gate | PASS — independent adversarial verifier: draft FAILED (3 VO + 2 caption overclaims), all fixes applied → PASS. Fictional SKU KID-24-BLUE, "say a seller"; CPC/GCC not mixed; no approval promise; no logos |
| Topic not repeated (14 days) | PASS — previous: certifier identity (10-22), test report ≠ certificate (10-23) |
| Loudness / encode | PASS — -14.1 LUFS, -1.0 dBTP; H.264 1080×1920 30 fps, AAC, 606 frames |

## Notes
- Engine fix in this run: build_audio.py truncated the music bed with int() while the voice track used round(); at 20.20 s that differed by one sample and crashed. Now both use round().
- In replies, don't say every plug-in toy is under 1505: adapter-powered (≤30 V) designs and video games are outside the definition's text.
