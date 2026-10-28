"""Render one reel from reels/<id>/script.json through the engine (used by the multi-reel daily run).

  python3 batch_render.py <id> --fit      voice only: REEL + vo.txt, voice.py --fit, print timing
  python3 batch_render.py <id> --stills   + stills at 0, 0.5, one per scene and the last frame
  python3 batch_render.py <id>            + full render, audio mix, copy to build/<id>.mp4

The engine works on one reel at a time (reel.html, vo.txt, voice/, reel_final.mp4); run reels one after another.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from reel_io import ROOT, load_reel, save_reel

REPO = ROOT.parent


def run(*cmd):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    sys.stdout.write(r.stdout[-3000:])
    sys.stderr.write(r.stderr[-2000:])
    return r.returncode


def main(argv):
    rid, mode = argv[0], (argv[1] if len(argv) > 1 else "--full")
    d = REPO / "reels" / rid
    script, meta = json.loads((d / "script.json").read_text()), json.loads((d / "meta.json").read_text())
    voices = json.loads((REPO / "config" / "arms.json").read_text())["factors"]["voice"]
    m = {"id": rid, "pillar": meta["pillar"], "cta": meta["cta"], "voice": voices[meta["arms"]["voice"]],
         "opener": meta["arms"].get("opener", "classic"), "footnote": "Illustrative example. Not legal advice."}
    if m["opener"] == "kicker" and script.get("kicker"):
        m["kicker"] = script["kicker"]
    save_reel({"meta": m, "scenes": script["scenes"]})
    (ROOT / "vo.txt").write_text("\n".join(script["vo"]) + "\n")
    if run("python3", "voice.py", "--fit"):
        return 1
    reel = load_reel()                       # --fit raised the durations: keep them in script.json too
    script["scenes"] = reel["scenes"]
    (d / "script.json").write_text(json.dumps(script, indent=1, ensure_ascii=False))
    if mode == "--fit":
        return 0
    t, marks = 0.0, ["0", "0.5"]
    for s in reel["scenes"]:
        marks.append(f"{t + s['dur'] * 0.75:.2f}")
        t += s["dur"]
    marks.append(f"{t - 0.1:.2f}")
    shutil.rmtree(ROOT / "stills", ignore_errors=True)
    if run("python3", "render.py", "--stills", *marks):
        return 1
    keep = ROOT / "build" / f"stills_{rid}"
    shutil.rmtree(keep, ignore_errors=True)
    shutil.copytree(ROOT / "stills", keep)
    if mode == "--stills":
        return 0
    if run("python3", "render.py") or run("python3", "build_audio.py"):
        return 1
    (ROOT / "build").mkdir(exist_ok=True)
    shutil.copy(ROOT / "reel_final.mp4", ROOT / "build" / f"{rid}.mp4")
    print(f"-> engine/build/{rid}.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
