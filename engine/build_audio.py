"""Mix voice + music + sound effects and mux with the rendered video.

  python build_audio.py   -> reel_final.mp4  (needs build/reel_video.mp4 and build/events.json from render.py,
                                              and voice/s1.wav ... s5.wav from voice.py or Mert's recordings)

Music and sound effects are synthesized here (no third-party audio, nothing to license).
The music ducks under the voice; the final mix is loudness-normalized to -14 LUFS for Reels/Shorts.
"""
import json
import subprocess
import sys
import wave

import numpy as np
from scipy.signal import butter, sosfilt

from reel_io import BUILD_DIR, ROOT, VOICE_DIR, VOICE_OFFSET, load_reel, scene_starts

SR = 48000
TARGET_LUFS = -14.0
MUSIC_DB = -14.0     # music bed relative to voice peak, before ducking (~12 LU under the voice)
DUCK_DB = -7.0       # extra attenuation while the voice is speaking
SFX_DB = -11.0       # sound effects relative to voice peak
rng = np.random.default_rng(7)


# ---------------- io ----------------
def read_wav(path):
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).astype(np.float64)


def write_wav(path, x):
    x = np.atleast_2d(x)
    if x.shape[0] < x.shape[1]:
        x = x.T
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1]); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


def db(x):
    return 10 ** (x / 20)


def t_axis(sec):
    return np.arange(int(sec * SR)) / SR


def lp(x, hz, order=2):
    return sosfilt(butter(order, hz, "low", fs=SR, output="sos"), x)


def hp(x, hz, order=2):
    return sosfilt(butter(order, hz, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def note(n):
    """MIDI note -> Hz"""
    return 440.0 * 2 ** ((n - 69) / 12)


def add(buf, x, at):
    i = int(round(at * SR))
    if i >= buf.shape[-1]:
        return
    n = min(x.shape[-1], buf.shape[-1] - i)
    buf[..., i:i + n] += x[..., :n]


# ---------------- music ----------------
def saw_pad(freq, sec, detune_cents):
    t = t_axis(sec)
    f = freq * 2 ** (detune_cents / 1200)
    out = np.zeros_like(t)
    for k in range(1, 12):
        if f * k > 6000:
            break
        out += np.sin(2 * np.pi * f * k * t + rng.uniform(0, 2 * np.pi)) / k * np.exp(-k / 5)
    return out


def music(total):
    bpm = 100.0
    beat = 60.0 / bpm
    bar = 4 * beat
    chords = [[57, 60, 64], [53, 57, 60], [55, 60, 64], [55, 59, 62]]   # Am  F  C/G  G
    roots = [45, 41, 43, 43]
    L = int((total + 0.5) * SR)
    pad = np.zeros((2, L)); drums = np.zeros(L); bass = np.zeros(L); arp = np.zeros((2, L))
    nbars = int(np.ceil(total / bar)) + 1
    for b in range(nbars):
        c, r, t0 = chords[b % 4], roots[b % 4], b * bar
        seg = bar + 0.6
        env = np.minimum(1, t_axis(seg) / 0.35) * np.minimum(1, np.maximum(0, (seg - t_axis(seg)) / 0.6))
        for ch, det in ((0, -5), (1, 5)):
            x = sum(saw_pad(note(n), seg, det) for n in c) + 0.6 * np.sin(2 * np.pi * note(c[0] - 12) * t_axis(seg))
            add(pad[ch], lp(x, 1500) * env, t0)
        for k in range(4):                                                        # bass on every beat
            tb = t_axis(beat * 0.95)
            f = note(r)
            x = (np.sin(2 * np.pi * f * tb) + 0.35 * np.sin(4 * np.pi * f * tb) + 0.15 * np.sin(6 * np.pi * f * tb))
            add(bass, x * np.exp(-tb / 0.28) * np.minimum(1, tb / 0.006), t0 + k * beat)
        for k in (0, 2):                                                          # kick on 1 and 3
            tk = t_axis(0.35)
            ph = 2 * np.pi * np.cumsum(48 + 110 * np.exp(-tk / 0.035)) / SR
            add(drums, np.sin(ph) * np.exp(-tk / 0.16) * 0.9, t0 + k * beat)
        for k in range(8):                                                        # off-beat hats
            if k % 2:
                th = t_axis(0.06)
                add(drums, hp(rng.standard_normal(th.size), 7000) * np.exp(-th / 0.018) * 0.22, t0 + k * beat / 2)
        if b >= 1:                                                                # 16th arp from bar 2
            tones = [c[0] + 12, c[2] + 12, c[1] + 12, c[2] + 12]
            for k in range(16):
                ta = t_axis(0.22)
                f = note(tones[k % 4])
                tri = 2 / np.pi * np.arcsin(np.sin(2 * np.pi * f * ta))
                x = lp(tri * np.exp(-ta / 0.09), 3500)
                pan = 0.5 + 0.35 * np.sin(k * 0.8)
                add(arp, np.vstack([x * (1 - pan), x * pan]) * 2 * 0.55, t0 + k * beat / 4)
    # sidechain pump on pad from the beat grid
    tt = np.arange(L) / SR
    pump = 1 - 0.35 * np.exp(-((tt % beat) / 0.11))
    m = pad * 0.22 * pump + arp * 0.15 + np.vstack([bass, bass]) * 0.20 + np.vstack([drums, drums]) * 0.26
    m = m[:, :int(total * SR)]
    n = m.shape[1]
    fade = np.ones(n)
    fi, fo = int(0.25 * SR), int(1.4 * SR)
    fade[:fi] = np.linspace(0, 1, fi)
    fade[-fo:] = np.linspace(1, 0, fo) ** 1.5
    return m * fade / (np.abs(m).max() + 1e-9)


# ---------------- sound effects ----------------
def sfx(kind):
    if kind in ("whoosh", "swish"):
        sec = 0.42 if kind == "whoosh" else 0.24
        t = t_axis(sec)
        x = rng.standard_normal(t.size)
        out = np.zeros_like(t)
        hop = 512
        for i in range(0, t.size, hop):                                          # sweeping band-pass
            p = i / t.size
            fc = (700 + 3800 * np.sin(np.pi * p)) if kind == "whoosh" else (1800 + 5000 * p)
            seg = x[i:i + hop * 2]
            out[i:i + seg.size] += bp(seg, fc * 0.6, min(fc * 1.6, SR / 2 - 100)) * np.hanning(seg.size)
        return out * np.sin(np.pi * t / sec) ** 2 * 1.6
    if kind == "thud":                                                            # rubber stamp on paper
        t = t_axis(0.5)
        ph = 2 * np.pi * np.cumsum(42 + 90 * np.exp(-t / 0.03)) / SR
        body = np.sin(ph) * np.exp(-t / 0.12)
        slap = bp(rng.standard_normal(t.size), 600, 3200) * np.exp(-t / 0.025)
        click = hp(rng.standard_normal(t.size), 3000) * np.exp(-t / 0.004)
        return body * 1.1 + slap * 0.9 + click * 0.5
    if kind == "error":                                                           # soft two-note "nope"
        out = np.zeros(int(0.34 * SR))
        for i, f in enumerate((392.0, 311.1)):
            t = t_axis(0.16)
            x = np.sign(np.sin(2 * np.pi * f * t)) * 0.4 + np.sin(2 * np.pi * f * t)
            add(out, lp(x, 2200) * np.exp(-t / 0.07) * np.minimum(1, t / 0.004), i * 0.13)
        return out * 0.7
    if kind == "pop":
        t = t_axis(0.12)
        ph = 2 * np.pi * np.cumsum(500 + 500 * (1 - np.exp(-t / 0.02))) / SR
        return np.sin(ph) * np.exp(-t / 0.03)
    if kind == "chime":                                                           # positive two-note
        out = np.zeros(int(0.9 * SR))
        for i, f in enumerate((659.3, 987.8)):
            t = t_axis(0.7)
            x = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)
            add(out, x * np.exp(-t / 0.25) * np.minimum(1, t / 0.003), i * 0.09)
        return out * 0.6
    if kind == "tick":
        t = t_axis(0.06)
        return (np.sin(2 * np.pi * 1900 * t) + 0.5 * hp(rng.standard_normal(t.size), 4000)) * np.exp(-t / 0.012)
    if kind == "ding":                                                            # bell
        t = t_axis(1.6)
        f = 1046.5
        x = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t / d) for r, a, d in
                ((1, 1, 0.9), (2.76, 0.45, 0.35), (5.4, 0.25, 0.18), (8.93, 0.12, 0.09)))
        return x * np.minimum(1, t / 0.002) * 0.55
    raise ValueError(kind)


def loudnorm(src, dst):
    """Two-pass EBU R128 normalization to TARGET_LUFS, true peak -1 dBTP."""
    f = f"loudnorm=I={TARGET_LUFS}:TP=-1.0:LRA=11"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f + ":print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    js = r.stderr[r.stderr.rfind("{"):r.stderr.rfind("}") + 1]
    m = json.loads(js)
    f2 = (f + f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
          f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", f2, "-ar", str(SR), str(dst)], check=True)
    return m


def measure(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = json.loads(r.stderr[r.stderr.rfind("{"):r.stderr.rfind("}") + 1])
    return float(m["input_i"]), float(m["input_tp"])


def main():
    reel = load_reel()
    starts, total = scene_starts(reel)
    video = BUILD_DIR / "reel_video.mp4"
    evp = BUILD_DIR / "events.json"
    if not video.exists() or not evp.exists():
        sys.exit("run python render.py first (build/reel_video.mp4 + build/events.json missing)")
    events = json.loads(evp.read_text())
    n = int(round(total * SR))

    # voice
    voice = np.zeros(n)
    for i, t0 in enumerate(starts, 1):
        w = VOICE_DIR / f"s{i}.wav"
        if not w.exists():
            sys.exit(f"{w} missing: run python voice.py")
        x = read_wav(w)
        add(voice, x, t0 + VOICE_OFFSET)
    vpk = np.abs(voice).max() + 1e-9
    voice /= vpk

    # ducking envelope from the voice
    win = int(0.02 * SR)
    rms = np.sqrt(np.convolve(voice ** 2, np.ones(win) / win, mode="same"))
    act = (rms > 0.02).astype(float)
    a_att, a_rel = np.exp(-1 / (0.04 * SR / win)), np.exp(-1 / (0.30 * SR / win))
    act_ds = act[::win]
    env = np.zeros_like(act_ds)
    for i in range(1, env.size):
        a = a_att if act_ds[i] > env[i - 1] else a_rel
        env[i] = a * env[i - 1] + (1 - a) * act_ds[i]
    env = np.interp(np.arange(n), np.arange(env.size) * win, env)
    duck = db(DUCK_DB) ** env

    mus = music(total) * db(MUSIC_DB) * duck

    # sound effects from the render's cue sheet
    fx = np.zeros((2, n))
    for e in events:
        x = sfx(e["kind"]) * e.get("gain", 1.0)
        x = x / (np.abs(x).max() + 1e-9)
        pan = {"whoosh": 0.5, "swish": 0.5, "tick": 0.55, "pop": 0.45}.get(e["kind"], 0.5)
        add(fx, np.vstack([x * np.sqrt(1 - pan), x * np.sqrt(pan)]) * e.get("gain", 1.0), e["t"])
    fx *= db(SFX_DB)

    mix = np.vstack([voice, voice]) * 0.92 + mus + fx
    mix /= max(1.0, np.abs(mix).max() / 0.98)

    BUILD_DIR.mkdir(exist_ok=True)
    write_wav(BUILD_DIR / "stem_voice.wav", voice)
    write_wav(BUILD_DIR / "stem_music.wav", mus)
    write_wav(BUILD_DIR / "stem_sfx.wav", fx)
    write_wav(BUILD_DIR / "mix_raw.wav", mix)
    loudnorm(BUILD_DIR / "mix_raw.wav", BUILD_DIR / "mix.wav")
    lufs, tp = measure(BUILD_DIR / "mix.wav")

    out = ROOT / "reel_final.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(BUILD_DIR / "mix.wav"),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
                    "-shortest", "-movflags", "+faststart", str(out)], check=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,duration",
                            "-of", "compact=p=0:nk=0", str(out)], capture_output=True, text=True).stdout.strip()
    print(f"sfx cues: {len(events)} | music ducked {DUCK_DB} dB under voice")
    print(f"loudness: {lufs:.1f} LUFS integrated, true peak {tp:.1f} dBTP (target {TARGET_LUFS} LUFS)")
    print(probe)
    print(f"-> {out.name}")


if __name__ == "__main__":
    main()
