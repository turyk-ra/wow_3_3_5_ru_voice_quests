#!/usr/bin/env python3
"""Объективная оценка голосов Vosk TTS по пробным фразам (tts/samples/voice_N.mp3):
  * CER — доля ошибок распознавания (меньше = разборчивее), распознаёт vosk-model-small-ru;
  * F0 — медианная высота голоса, Гц (мужчины ~85-160, женщины ~165-280) — проверка пола.

  tts/.venv/Scripts/python tts/rate_voices.py tts/samples
"""
import json, os, re, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from synthesize_vosk import SAMPLE  # noqa: E402

SR = 16000


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16)


def f0_median(x):
    x = x.astype(np.float32) / 32768
    win, hop = int(0.04 * SR), int(0.01 * SR)
    lo, hi = int(SR / 350), int(SR / 70)
    f0s = []
    for i in range(0, len(x) - win, hop):
        fr = x[i:i + win] - x[i:i + win].mean()
        e = float(np.dot(fr, fr))
        if e < 1e-3:
            continue
        ac = np.correlate(fr, fr, "full")[win - 1:]
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / ac[0] > 0.5:  # только звонкие кадры
            f0s.append(SR / lag)
    return float(np.median(f0s)) if f0s else 0.0


def norm(t):
    t = t.lower().replace("ё", "е")
    return re.sub(r"[^а-я ]", "", t).split()


def cer(ref, hyp):
    r, h = " ".join(ref), " ".join(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


def main():
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
    asr = Model(os.path.join(HERE, "models", "vosk-model-small-ru-0.22"))
    names = {v: k for k, v in json.load(open(os.path.join(HERE, "models", "vosk-model-tts-ru-0.10-multi", "config.json"),
                                            encoding="utf-8"))["speaker_id_map"].items()}
    ref = norm(SAMPLE)
    d = sys.argv[1]
    rows = []
    for f in sorted(os.listdir(d), key=lambda s: int(re.sub(r"\D", "", s) or 0)):
        m = re.match(r"voice_(\d+)\.mp3$", f)
        if not m:
            continue
        sid = int(m.group(1))
        x = decode(os.path.join(d, f))
        rec = KaldiRecognizer(asr, SR)
        rec.AcceptWaveform(x.tobytes())
        hyp = norm(json.loads(rec.FinalResult()).get("text", ""))
        rows.append((sid, names.get(sid, "?"), round(f0_median(x)), round(cer(ref, hyp), 3), len(x) / SR))
    print("id\tname\tF0\tCER\tsec")
    for r in rows:
        print("\t".join(str(v) if not isinstance(v, float) else f"{v:.2f}" for v in r))


if __name__ == "__main__":
    main()
