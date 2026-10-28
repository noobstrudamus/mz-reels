"""Render one Instagram story frame (stories/<id>/script.json) to a still and a 6 s mp4.

  python3 story.py ../stories/20261028_story_01            -> stills/story_<id>.png + build/story_<id>.mp4
  python3 story.py ../stories/20261028_story_01 --still    -> the PNG only (LOOK at it)

script.json: {"frame": {...story.html frame...}, "from_reel": "reels/<id>", "sources": [...]}.
Stories never carry a new claim: a rule frame's quote must appear word for word in the from_reel script's
sources and its cite must be one of their sections; sources are copied from that reel. Validation, the
safe zone (y 260-1580) and overflow are checked; any failure stops the render (--force overrides).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "story.html"
CHROMIUM = "/opt/pw-browsers/chromium"
SECONDS = 6


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower().replace("“", '"').replace("”", '"')


def check_sources(script, repo):
    """Errors when the story is not backed by its reel's verified sources."""
    errs, frame = [], script.get("frame") or {}
    reel = repo / str(script.get("from_reel") or "")
    rs = reel / "script.json"
    if not script.get("from_reel") or not rs.is_file():
        return [f"from_reel {script.get('from_reel')!r} has no script.json: a story repeats a verified reel"]
    src = json.loads(rs.read_text(encoding="utf-8")).get("sources") or []
    if not script.get("sources"):
        errs.append("sources missing: copy them from the reel")
    if frame.get("type") == "rule":
        quotes = [norm(s.get("quote")) for s in src]
        if not any(norm(frame.get("quote")) in q for q in quotes):
            errs.append("rule quote is not word for word in the reel's verified sources")
        if not any(norm(frame.get("cite")) in norm(s.get("section")) for s in src):
            errs.append(f"cite {frame.get('cite')!r} is not a section in the reel's sources")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("story_dir")
    ap.add_argument("--still", action="store_true", help="PNG only")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    d = Path(a.story_dir).resolve()
    script = json.loads((d / "script.json").read_text(encoding="utf-8"))
    frame, sid = script.get("frame") or {}, d.name
    errs = check_sources(script, d.parent.parent)

    from playwright.sync_api import sync_playwright
    png = ROOT / "stills" / f"story_{sid}.png"
    png.parent.mkdir(exist_ok=True)
    with sync_playwright() as p:
        kw = {"args": ["--no-sandbox", "--font-render-hinting=none", "--disable-lcd-text"]}
        if os.path.exists(CHROMIUM):
            kw["executable_path"] = CHROMIUM
        browser = p.chromium.launch(**kw)
        page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.goto(HTML.as_uri())
        page.evaluate("story.ready")
        errs += page.evaluate("f => story.validate(f)", frame)
        if not page.evaluate("f => story.validate(f)", frame):
            page.evaluate("f => story.build(f)", frame)
            errs += page.evaluate("story.qa()")
        page.screenshot(path=str(png))
        browser.close()
    print("QA  story:", "PASS" if not errs else "FAIL")
    for e in errs:
        print("    - " + e)
    print(f"still {png.relative_to(ROOT)}")
    if errs and not a.force:
        return 1
    if a.still:
        return 0
    out = ROOT / "build" / f"story_{sid}.mp4"
    out.parent.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-i", str(png),
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(SECONDS),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", "30",
                    "-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart", str(out)], check=True)
    print(f"-> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
