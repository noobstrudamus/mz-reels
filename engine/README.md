# mz-reel-template

Vertical 1080×1920, 30 fps reel engine for M&Z Consulting. Rebuilt from the production spec in
`/home/user/CLAUDE.md`. Brand colors and fonts come from mzconsulting.agency: Archivo,
Public Sans, and JetBrains Mono for SKUs. All three are OFL-licensed.

## Daily run

```bash
# 1. edit ONLY the REEL object in reel.html (between /* REEL:BEGIN */ and /* REEL:END */)
# 2. write vo.txt: 5 lines, one per scene, numbers as words
python3 voice.py            # Mert's voice/s1..s5.wav are kept; otherwise TTS. Must print ALL OK
python3 voice.py --fit      # optional: raises any scene dur that is shorter than its line + 0.3 s
python3 render.py --stills 0.5 4 9 15 20   # LOOK at every PNG in stills/
python3 render.py           # build/reel_video.mp4 (silent) + build/events.json (sound-effect cues)
python3 build_audio.py      # reel_final.mp4: voice + music + sound effects, -14 LUFS
```

## What the engine enforces

- Scene order is stamp → compare → pair → checklist → cta.
- Text limits: headline ≤30, note ≤60, stamp ≤8, compare value ≤11 (label ≤14), pair label ≤12,
  checklist name ≤18 and value ≤14 (3–4 items), cta line1 ≤20 and line2 ≤40.
- The CTA scene must match the GAP LIST or FINDER set word for word (`meta.cta`).
- Total length must be 18–24 s. Each scene's `dur` must be at least its voice line + 0.3 s
  (checked by `voice.py`).
- All text must sit inside the safe zone (x 80–936, y 250–1360), so Reels/Shorts UI never covers it.
  The engine also checks that nothing overflows or wraps past its line limit.
- If any check fails, `render.py` stops (`--force` overrides).

## Files

| file | role |
|---|---|
| `reel.html` | REEL object + deterministic engine (`reel.seek(t)`); open in a browser to preview, `?t=3.2` freezes a frame |
| `voice.py` | TTS via edge-tts (`en-US-AndrewNeural`, +6%), silence trim, fit check |
| `render.py` | Chromium frame render on several workers → H.264; stills; QA |
| `build_audio.py` | synthesized music bed (ducked under voice) + sound effects from the cue sheet, loudness normalization, mux |
| `reel_io.py` | shared helpers (reads the REEL object through node) |

## Requirements

Python packages: `edge-tts`, `playwright`, `numpy`, `scipy`. You also need `node`, `ffmpeg` and
Chromium (`/opt/pw-browsers/chromium` in the cloud container).

The cloud container runs behind a TLS-inspecting proxy. `voice.py` points edge-tts at
`/root/.ccr/ca-bundle.crt`, or at `$SSL_CERT_FILE` if that is set. It never disables certificate
verification.
