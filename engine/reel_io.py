"""Shared helpers: read/write the REEL object inside reel.html, paths, voice timing."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "reel.html"
VOICE_DIR = ROOT / "voice"
STILLS_DIR = ROOT / "stills"
BUILD_DIR = ROOT / "build"

VOICE_OFFSET = 0.15   # each voice line starts this long after its scene starts
FIT_MARGIN = 0.30     # playbook: scene dur >= voice line + 0.3 s
TOTAL_RANGE = (18.0, 24.0)

_BLOCK = re.compile(r"(/\* REEL:BEGIN \*/\s*)(const REEL = .*?;)(\s*/\* REEL:END \*/)", re.S)


def load_reel():
    """Evaluate the REEL object with node so JS-style edits (unquoted keys, trailing commas) still work."""
    m = _BLOCK.search(HTML.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("reel.html: REEL block between /* REEL:BEGIN */ and /* REEL:END */ not found")
    js = m.group(2) + "\nprocess.stdout.write(JSON.stringify(REEL));"
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    if out.returncode:
        raise SystemExit("reel.html: REEL object does not parse:\n" + out.stderr.strip())
    return json.loads(out.stdout)


def save_reel(reel):
    """Write REEL back (pretty JSON is valid JS). Only the REEL block is touched."""
    src = HTML.read_text(encoding="utf-8")
    body = "const REEL = " + json.dumps(reel, indent=2, ensure_ascii=False) + ";"
    new, n = _BLOCK.subn(lambda m: m.group(1) + body + m.group(3), src)
    if n != 1:
        raise SystemExit("reel.html: could not locate REEL block to update")
    HTML.write_text(new, encoding="utf-8")


def scene_starts(reel):
    t, starts = 0.0, []
    for s in reel["scenes"]:
        starts.append(t)
        t += s["dur"]
    return starts, t


def read_vo():
    p = ROOT / "vo.txt"
    if not p.exists():
        raise SystemExit("vo.txt missing: write 5 lines, one per scene")
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def wav_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    return float(out.stdout.strip())
