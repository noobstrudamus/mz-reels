"""Render a mise-en-scene reel from scene.html + a scene script (JSON).

  python3 render_scene.py <script.json> [--stills 0 3 8 ...]

script.json: {"id", "world", "voice", "vo": [5 lines], "caps": [[headline, sub, cite] x4], "props": {...}}
Voice: edge TTS (voice.tts). Timeline: scene k starts when VO line k starts; each line gets +0.35 s air.
Output: build/scene_<id>.mp4 (video + voice + music + whoosh/pop cues, -14 LUFS).
"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE))
import numpy as np                                     # noqa: E402
from voice import tts                                  # noqa: E402
from reel_io import wav_duration                       # noqa: E402
import build_audio as BA                               # noqa: E402

FPS = 30


def main(argv):
    sp = Path(argv[0]); stills = None
    if "--stills" in argv:
        stills = [float(x) for x in argv[argv.index("--stills") + 1:]]
    s = json.loads(sp.read_text())
    out = ENGINE / "build" / f"scene_{s['id']}"
    out.mkdir(parents=True, exist_ok=True)
    durs = []
    for i, line in enumerate(s["vo"]):
        w = out / f"s{i + 1}.wav"
        key = out / f"s{i + 1}.txt"
        if not w.exists() or not key.exists() or key.read_text() != line + s["voice"]:
            tts(line, w, voice=s["voice"]); key.write_text(line + s["voice"])
        durs.append(wav_duration(w))
    gaps = s.get("min_dur", [0] * 5)
    starts, t = [], 0.15
    for d, m in zip(durs, gaps):
        starts.append(round(t, 2)); t += max(d + 0.25, m)
    total = round(t + 0.15, 2)
    times = [0.0] + starts[1:] + [total]
    sr = 48000; n = int(total * sr)
    voice = np.zeros(n)
    for st, i in zip(starts, range(5)):
        x = BA.read_wav(out / f"s{i + 1}.wav")
        a = int(st * sr); voice[a:a + x.size] += x[: max(0, n - a)]
    # lip-sync: RMS per video frame -> 0..1 openness, lightly smoothed
    hop = sr // FPS
    rms = np.array([np.sqrt(np.mean(voice[i:i + hop] ** 2)) for i in range(0, n, hop)])
    mouth = np.clip(rms / (np.percentile(rms[rms > 1e-4], 90) + 1e-9), 0, 1) if (rms > 1e-4).any() else rms
    mouth = np.convolve(mouth, [0.25, 0.5, 0.25], "same")
    world = s.get("world") or "port_customs"          # port_customs = scene.html; every other world lives in worlds.html
    html = (HERE / ("scene.html" if world == "port_customs" else "worlds.html")).read_text().replace("{{WORLD}}", json.dumps(world))
    ava = (HERE / "_ava2.svg").read_text()
    page_html = (html.replace("{{AVA}}", ava).replace("{{TIMES}}", json.dumps(times)).replace("{{CAPS}}", json.dumps(s["caps"]))
                 .replace("{{PROPS}}", json.dumps(s.get("props", {}))).replace("{{MOUTH}}", json.dumps([round(float(v), 3) for v in mouth])))
    page = out / "page.html"
    page.write_text(page_html.replace("../fonts/", (ENGINE / "fonts").as_uri() + "/"))
    print(f"lines {[round(d, 2) for d in durs]} | starts {starts} | total {total}s")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--font-render-hinting=none"], **({"executable_path": "/opt/pw-browsers/chromium"} if Path("/opt/pw-browsers/chromium").exists() else {}))
        pg = b.new_page(viewport={"width": 1080, "height": 1920})
        pg.goto(page.as_uri()); pg.evaluate("reel.ready")
        if stills is not None:
            for st in stills:
                pg.evaluate(f"reel.seek({st})"); pg.screenshot(path=str(out / f"still_{st:05.2f}.png"))
            b.close(); print("stills ->", out); return 0
        enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                                "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS),
                                str(out / "video.mp4")], stdin=subprocess.PIPE)
        for f in range(int(total * FPS)):
            pg.evaluate(f"reel.seek({f / FPS})"); enc.stdin.write(pg.screenshot(type="jpeg", quality=95))
        enc.stdin.close(); enc.wait(); b.close()
    env = np.convolve(np.abs(voice) > 0.02, np.ones(sr // 10) / (sr // 10), "same")
    mus = BA.music(total)[:, :n] * BA.db(BA.MUSIC_DB) * (BA.db(BA.DUCK_DB) ** np.clip(env * 3, 0, 1))
    fx = np.zeros((2, n))
    cues = [("whoosh", 0.05), ("whoosh", starts[1]), ("pop", starts[1] + 1.95), ("pop", starts[1] + 2.45),
            ("whoosh", starts[2]), ("tick", starts[3] + 0.5), ("tick", starts[3] + 0.95), ("tick", starts[3] + 1.4),
            ("tick", starts[3] + 1.85), ("tick", starts[3] + 2.3), ("whoosh", starts[4])]
    for k, at in cues:
        x = BA.sfx(k); x = x / (np.abs(x).max() + 1e-9)
        BA.add(fx, np.vstack([x, x]) * 0.5, at)
    fx *= BA.db(BA.SFX_DB)
    mix = np.vstack([voice, voice]) * 0.92 + mus + fx
    mix /= max(1.0, np.abs(mix).max() / 0.98)
    BA.write_wav(out / "mix.wav", mix)
    BA.loudnorm(out / "mix.wav", out / "mix_norm.wav")
    final = ENGINE / "build" / f"scene_{s['id']}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out / "video.mp4"), "-i", str(out / "mix_norm.wav"), "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final)], check=True)
    print("->", final)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
