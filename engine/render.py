"""Render reel.html.

  python render.py --stills 0.5 4 9 15 20   PNG stills into stills/ (+ QA report) -> LOOK at every one
  python render.py                          full 30 fps render -> build/reel_video.mp4 (silent) + build/events.json

Every run validates the REEL object (order, text limits, CTA set, 18-24 s) and checks that all
text sits inside the safe zone without overflowing. Rendering stops on any failure unless --force.
"""
import argparse
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import time

from reel_io import BUILD_DIR, HTML, STILLS_DIR

CHROMIUM = "/opt/pw-browsers/chromium"


def open_page(p):
    kw = {"args": ["--no-sandbox", "--font-render-hinting=none", "--disable-lcd-text"]}
    if os.path.exists(CHROMIUM):
        kw["executable_path"] = CHROMIUM
    browser = p.chromium.launch(**kw)
    page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
    page.goto(HTML.as_uri())
    page.evaluate("reel.ready")
    return browser, page


def check(page):
    errs = page.evaluate("reel.validate()")
    issues = page.evaluate("reel.qa()")
    return errs, issues


def report(errs, issues):
    print("QA  REEL object   :", "PASS" if not errs else "FAIL")
    for e in errs:
        print("    - " + e)
    print("QA  safe zone/fit :", "PASS" if not issues else "FAIL")
    for e in issues:
        print("    - " + e)


def render_chunk(args):
    """Worker: render frames [f0, f1) and encode them to one H.264 segment."""
    f0, f1, fps, seg = args
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, page = open_page(p)
        enc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
             "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-profile:v", "high",
             "-r", str(fps), seg], stdin=subprocess.PIPE)
        for f in range(f0, f1):
            page.evaluate(f"reel.seek({f / fps})")
            # JPEG q98 is visually lossless before H.264 4:2:0 and ~4x faster to encode than PNG here
            enc.stdin.write(page.screenshot(type="jpeg", quality=98))
        enc.stdin.close()
        enc.wait()
        browser.close()
        if enc.returncode:
            raise RuntimeError(f"ffmpeg failed on segment {seg}")
    return seg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", nargs="+", type=float, help="times in seconds")
    ap.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--force", action="store_true", help="render even if QA fails")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, page = open_page(p)
        info = page.evaluate("reel.info()")
        errs, issues = check(page)
        report(errs, issues)
        BUILD_DIR.mkdir(exist_ok=True)
        (BUILD_DIR / "events.json").write_text(json.dumps(page.evaluate("reel.events()"), indent=1))
        (BUILD_DIR / "timeline.json").write_text(json.dumps(info, indent=1))
        if a.stills:
            STILLS_DIR.mkdir(exist_ok=True)
            for t in a.stills:
                t = min(t, info["duration"] - 0.001)
                page.evaluate(f"reel.seek({t})")
                out = STILLS_DIR / f"still_{t:05.2f}s.png"
                page.screenshot(path=str(out))
                scene = next(i for i, s in enumerate(info["scenes"], 1) if s["start"] <= t < s["start"] + s["dur"])
                print(f"still {out.relative_to(HTML.parent)}  (scene {scene}: {info['scenes'][scene - 1]['type']})")
        browser.close()

    if (errs or issues) and not a.force:
        sys.exit(1)
    if a.stills:
        return

    fps, dur = info["fps"], info["duration"]
    n = round(dur * fps)
    w = max(1, min(a.workers, n // 30))
    seg_dir = BUILD_DIR / "segments"
    shutil.rmtree(seg_dir, ignore_errors=True)
    seg_dir.mkdir(parents=True)
    bounds = [round(i * n / w) for i in range(w + 1)]
    jobs = [(bounds[i], bounds[i + 1], fps, str(seg_dir / f"seg{i:02d}.mp4")) for i in range(w)]
    t0 = time.time()
    print(f"rendering {n} frames ({dur:.2f} s @ {fps} fps) on {w} workers ...")
    with mp.get_context("spawn").Pool(w) as pool:
        segs = pool.map(render_chunk, jobs)
    lst = seg_dir / "list.txt"
    lst.write_text("".join(f"file '{os.path.basename(s)}'\n" for s in segs))
    out = BUILD_DIR / "reel_video.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)], check=True)
    got = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_frames", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    print(f"video {out.relative_to(HTML.parent)}: {got} frames in {time.time() - t0:.1f} s (expected {n})")
    if str(n) != got:
        sys.exit("frame count mismatch")


if __name__ == "__main__":
    main()
