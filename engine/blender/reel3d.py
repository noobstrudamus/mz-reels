"""Blender 3D reel pipeline.
  python3 reel3d.py prep   reels/<id>/scene3d.json   -> TTS lines + build/b3d_<id>/timing.json
  (render)  python3 scene3d.py build/b3d_<id>/timing.json build/b3d_<id>/frames [--still ...]
  python3 reel3d.py finish reels/<id>/scene3d.json   -> overlays (captions, offer band, end card) + voice/music
                                                         -> build/b3d_<id>.mp4 (1080x1920, -14 LUFS)"""
import json, subprocess, sys
from pathlib import Path
import numpy as np
ENGINE = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ENGINE))
from voice import tts                      # noqa: E402
from reel_io import wav_duration           # noqa: E402
import build_audio as BA                   # noqa: E402

FPS = 24

def load(p):
    s = json.loads(Path(p).read_text()); out = ENGINE / "build" / f"b3d_{s['id']}"; out.mkdir(parents=True, exist_ok=True)
    return s, out

def prep(p):
    s, out = load(p); durs = []
    for i, line in enumerate(s["vo"]):
        w, key = out / f"s{i+1}.wav", out / f"s{i+1}.txt"
        if not w.exists() or not key.exists() or key.read_text() != line + s["voice"]:
            tts(line, w, voice=s["voice"]); key.write_text(line + s["voice"])
        durs.append(wav_duration(w))
    starts, t = [], 0.15
    for d, m in zip(durs, s["min_dur"]):
        starts.append(round(t, 2)); t += max(d + 0.25, m)
    total = round(t + 0.15, 2)
    times = [0.0] + starts[1:] + [total]
    (out / "timing.json").write_text(json.dumps({"times": times, "starts": starts, "durs": durs, "fps": FPS,
                                                 "w": 720, "h": 1280, "samples": 6, "sku": s.get("sku", "")}))
    print(f"lines {[round(d,2) for d in durs]} starts {starts} total {total}s frames {int(total*FPS)}")

OVL = """<!doctype html><html><head><meta charset=utf-8><style>
@font-face{font-family:A;src:url(FONTS/archivo-wdth.woff2)}@font-face{font-family:P;src:url(FONTS/public-sans.woff2)}
@font-face{font-family:J;src:url(FONTS/jetbrains-mono-800.woff2)}
html,body{margin:0;width:1080px;height:1920px;background:transparent;overflow:hidden}
.grad{position:absolute;left:0;right:0;top:0;height:640px;background:linear-gradient(rgba(6,10,24,.82),rgba(6,10,24,0))}
.logo{position:absolute;left:64px;top:70px;font:800 34px A;color:#fff;letter-spacing:1px}.logo small{font:600 18px P;letter-spacing:5px;margin-left:10px;opacity:.85}
.h{position:absolute;left:64px;right:64px;top:170px;font:800 84px/1.02 A;color:#fff;text-shadow:0 4px 24px rgba(0,0,0,.5)}
.s{position:absolute;left:64px;right:64px;top:SUBTOPpx;font:500 40px/1.3 P;color:#f3f0e6;text-shadow:0 2px 12px rgba(0,0,0,.6)}
.c{position:absolute;left:64px;top:CITETOPpx;font:800 28px J;color:#9fd3ff}
.band{position:absolute;left:48px;bottom:250px;background:#ffcf3f;border-radius:22px;padding:16px 26px;font:800 38px A;color:#14161c}
.band span{font:700 26px P;margin-left:14px}
.foot{position:absolute;left:64px;bottom:200px;font:500 22px P;color:#e8e8e8;opacity:.85}
.card{position:absolute;inset:0;background:rgba(10,18,44,.88)}
.ch{position:absolute;left:64px;right:64px;top:430px;font:800 110px/1.0 A;color:#fff}
.c1{position:absolute;left:64px;top:690px;font:800 56px A;color:#ffcf3f}.c2{position:absolute;left:64px;top:770px;font:500 46px/1.25 P;color:#fff;width:900px}
.url{position:absolute;left:64px;top:930px;background:#ffcf3f;border-radius:40px;padding:18px 34px;font:800 44px A;color:#14161c}
.tag{position:absolute;left:64px;top:1110px;width:520px;background:#f5ecd6;border-radius:18px;padding:26px 30px;font:500 32px/1.3 P;color:#1d2230;border-bottom:8px solid #ffcf3f}
.tag b{display:block;font:800 22px A;letter-spacing:4px;margin-bottom:8px}
</style></head><body>BODY</body></html>"""

def overlays(s, out):
    from playwright.sync_api import sync_playwright
    fonts = (ENGINE / "fonts").as_uri()
    logo = '<div class=logo>M&amp;Z<small>CONSULTING</small></div>'
    foot = '<div class=foot>Illustrative example. Not legal advice.</div>'
    band = f'<div class=band>{s["offer"]}<span>{s["cta"][3]}</span></div>'
    pages = []
    for h, sub, cite in s["caps"]:
        lines = 1 if len(h) <= 18 else 2
        subtop = 170 + lines * 88 + 30; citetop = subtop + (2 if len(sub) > 38 else 1) * 54 + 20
        body = f'<div class=grad></div>{logo}<div class=h>{h}</div><div class=s>{sub}</div>' + \
               (f'<div class=c>{cite}</div>' if cite else '') + band + foot
        pages.append(OVL.replace("SUBTOP", str(subtop)).replace("CITETOP", str(citetop)).replace("BODY", body))
    c = s["cta"]
    pages.append(OVL.replace("BODY", f'<div class=card></div>{logo}<div class=ch>{c[0]}</div><div class=c1>{c[1]}</div>'
                 f'<div class=c2>{c[2]}</div><div class=url>{c[3]}</div><div class=tag><b>M&amp;Z CONSULTING</b>'
                 f'It\'s almost never the product. It\'s the file.</div>{foot}'))
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"], **({"executable_path": "/opt/pw-browsers/chromium"} if Path("/opt/pw-browsers/chromium").exists() else {}))
        pg = b.new_page(viewport={"width": 1080, "height": 1920})
        for i, html in enumerate(pages):
            f = out / f"ovl_{i}.html"; f.write_text(html.replace("FONTS", fonts)); pg.goto(f.as_uri()); pg.wait_for_timeout(300)
            pg.screenshot(path=str(out / f"ovl_{i}.png"), omit_background=True)
        b.close()

def finish(p):
    from PIL import Image
    s, out = load(p); tm = json.loads((out / "timing.json").read_text())
    times, starts, total = tm["times"], tm["starts"], tm["times"][-1]
    overlays(s, out)
    ov = [Image.open(out / f"ovl_{i}.png").convert("RGBA") for i in range(5)]
    n_frames = int(round(total * FPS)) + 1
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-r", "30",
                            str(out / "video.mp4")], stdin=subprocess.PIPE)
    import io
    for k in range(1, n_frames + 1):
        fp = out / "frames" / f"f_{k:04d}.png"
        base = Image.open(fp).convert("RGBA").resize((1080, 1920), Image.LANCZOS)
        sec = (k - 1) / FPS; sc = max(i for i in range(5) if times[i] <= sec + 1e-6)
        o = ov[sc]; fade = min(1.0, (sec - times[sc]) / 0.3) if sc < 4 or True else 1.0
        if fade < 1.0:
            o = o.copy(); o.putalpha(o.getchannel("A").point(lambda a: int(a * fade)))
        base.alpha_composite(o)
        buf = io.BytesIO(); base.convert("RGB").save(buf, "PNG", compress_level=1); enc.stdin.write(buf.getvalue())
    enc.stdin.close(); enc.wait()
    sr = 48000; n = int(total * sr); voice = np.zeros(n)
    for st, i in zip(starts, range(5)):
        x = BA.read_wav(out / f"s{i+1}.wav"); a = int(st * sr); voice[a:a + x.size] += x[: max(0, n - a)]
    env = np.convolve(np.abs(voice) > 0.02, np.ones(sr // 10) / (sr // 10), "same")
    mus = BA.music(total)[:, :n] * BA.db(BA.MUSIC_DB) * (BA.db(BA.DUCK_DB) ** np.clip(env * 3, 0, 1))
    fx = np.zeros((2, n))
    for k, at in [("whoosh", 0.05), ("pop", 1.15), ("whoosh", starts[1]), ("whoosh", starts[2]), ("pop", starts[2] + 1.6),
                  ("pop", starts[3] + 1.2), ("whoosh", starts[4])]:
        x = BA.sfx(k); x = x / (np.abs(x).max() + 1e-9); BA.add(fx, np.vstack([x, x]) * 0.5, at)
    fx *= BA.db(BA.SFX_DB)
    mix = np.vstack([voice, voice]) * 0.92 + mus + fx; mix /= max(1.0, np.abs(mix).max() / 0.98)
    BA.write_wav(out / "mix.wav", mix); BA.loudnorm(out / "mix.wav", out / "mix_norm.wav")
    final = ENGINE / "build" / f"b3d_{s['id']}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out / "video.mp4"), "-i", str(out / "mix_norm.wav"), "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final)], check=True)
    print("->", final)

if __name__ == "__main__":
    {"prep": prep, "finish": finish}[sys.argv[1]](sys.argv[2])
