"""Voice lines for the reel.

  python voice.py           generate missing/changed TTS lines, then check fit -> must print ALL OK
  python voice.py --fit     same, but raise any scene dur that is too short (edits only REEL durs)
  python voice.py --force   regenerate every TTS line (never touches Mert's recordings)

Mert's recordings: drop voice/s1.wav ... voice/s5.wav. Any wav that was not produced by this
script (not in voice/.tts.json with a matching hash) is treated as a recording and kept as is.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import ssl
import subprocess
import sys
import tempfile

from reel_io import FIT_MARGIN, TOTAL_RANGE, VOICE_DIR, load_reel, read_vo, save_reel, wav_duration

TTS_VOICE = "en-US-AndrewNeural"   # warm, confident US male
TTS_RATE = "+6%"
MANIFEST = VOICE_DIR / ".tts.json"
CA_BUNDLE = os.environ.get("SSL_CERT_FILE") or "/root/.ccr/ca-bundle.crt"


def sha1(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()


def tts(text, out_wav, voice=TTS_VOICE):
    import edge_tts
    import edge_tts.communicate as comm
    if os.path.exists(CA_BUNDLE):  # trust the environment's CA bundle (behind a TLS-inspecting proxy)
        comm._SSL_CTX = ssl.create_default_context(cafile=CA_BUNDLE)
    with tempfile.TemporaryDirectory() as td:
        mp3 = os.path.join(td, "l.mp3")
        for attempt in range(3):
            try:
                asyncio.run(edge_tts.Communicate(text, voice, rate=TTS_RATE).save(mp3))
                if os.path.getsize(mp3) > 1000:
                    break
            except Exception as e:  # network hiccup: retry
                err = e
        else:
            raise SystemExit(f"TTS failed for: {text!r} ({err})")
        # 48 kHz mono, trim leading/trailing silence so the measured length is the spoken length
        trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02,"
                "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp3, "-af", trim, "-ar", "48000", "-ac", "1", str(out_wav)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true", help="raise too-short scene durations in REEL")
    ap.add_argument("--force", action="store_true", help="regenerate all TTS lines")
    a = ap.parse_args()

    reel = load_reel()
    voice = reel.get("meta", {}).get("voice") or TTS_VOICE   # experiment arm, e.g. en-US-AvaNeural
    lines = read_vo()
    problems = []
    if len(lines) != 5:
        raise SystemExit(f"vo.txt must have exactly 5 lines (one per scene), found {len(lines)}")
    for i, l in enumerate(lines, 1):
        if re.search(r"\d", l):
            problems.append(f"line {i}: write numbers as words ({l!r})")

    VOICE_DIR.mkdir(exist_ok=True)
    man = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    durs, kinds = [], []
    for i, text in enumerate(lines, 1):
        wav, key = VOICE_DIR / f"s{i}.wav", f"s{i}"
        entry = man.get(key)
        is_ours = wav.exists() and entry and entry.get("sha1") == sha1(wav)
        if wav.exists() and not is_ours:
            kinds.append("recording")                       # Mert's take: keep it
        else:
            fresh = is_ours and entry["text"] == text and entry["voice"] == voice and entry["rate"] == TTS_RATE
            if a.force or not fresh:
                tts(text, wav, voice)
                man[key] = {"text": text, "voice": voice, "rate": TTS_RATE, "sha1": sha1(wav)}
            kinds.append("tts")
        durs.append(wav_duration(wav))
    MANIFEST.write_text(json.dumps(man, indent=2))

    scenes = reel["scenes"]
    if a.fit:
        for s, v in zip(scenes, durs):
            need = math.ceil((v + FIT_MARGIN) * 10 - 1e-9) / 10
            if s["dur"] < need:
                s["dur"] = need
        save_reel(reel)

    print(f"{'#':<3}{'scene':<11}{'source':<11}{'voice s':>8}{'dur s':>8}{'spare':>8}  words  w/s   status")
    for i, (s, v, k, l) in enumerate(zip(scenes, durs, kinds, lines), 1):
        spare = s["dur"] - v
        ok = spare >= FIT_MARGIN - 1e-6
        w = len(l.split())
        print(f"{i:<3}{s['type']:<11}{k:<11}{v:>8.2f}{s['dur']:>8.2f}{spare:>8.2f}  {w:>5}  {w / v:>4.1f}   {'OK' if ok else 'TOO SHORT'}")
        if not ok:
            problems.append(f"scene {i}: dur {s['dur']:.2f} s < voice {v:.2f} s + {FIT_MARGIN} s (need >= {v + FIT_MARGIN:.2f}; run voice.py --fit)")
    total = sum(s["dur"] for s in scenes)
    if not TOTAL_RANGE[0] <= total <= TOTAL_RANGE[1]:
        problems.append(f"total {total:.2f} s outside {TOTAL_RANGE[0]:.0f}-{TOTAL_RANGE[1]:.0f} s")
    print(f"total {total:.2f} s | voice {sum(durs):.2f} s | voice {voice} {TTS_RATE}")

    if problems:
        print("FAIL")
        for p in problems:
            print("  - " + p)
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
