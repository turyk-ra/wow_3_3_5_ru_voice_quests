#!/usr/bin/env python3
"""Бесплатный синтез RU для CatQuest335 через Piper (локально, без ключей).

Установка модели (один раз):
  python -m piper.download_voices ru_RU-irina-medium  (женский)
  или: ru_RU-dmitri-medium / ru_RU-ruslan-medium (мужские)

Пример:
  python tts/synthesize_piper.py --in data/quests_ru.clean.json --out addon/CatQuest335_Voices --voice irina
На выходе: <questID>_desc.mp3, <questID>_comp.mp3 (mp3 через ffmpeg) + voices_report.txt

Нужно: pip install -r tts/requirements.txt + установленный ffmpeg.
"""
import argparse, json, subprocess, shutil, os, sys

VOICE_MAP = {
    "irina": "ru_RU-irina-medium",
    "dmitri": "ru_RU-dmitri-medium",
    "ruslan": "ru_RU-ruslan-medium",
    "denis": "ru_RU-denis-medium",
}

def synth_piper(piper_bin, model, text, wav_path):
    p = subprocess.run([piper_bin, "--model", model, "--output_file", wav_path],
                       input=text.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode == 0

def wav_to_mp3(wav, mp3):
    # 64kbps mono — чтобы пак для 3.3.5 не раздулся
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-ac", "1", "-b:a", "64k", mp3])
    return r.returncode == 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', dest='out', required=True)
    ap.add_argument('--voice', default='irina', choices=list(VOICE_MAP))
    ap.add_argument('--limit-chars', type=int, default=1200)
    a = ap.parse_args()

    if not shutil.which("ffmpeg"):
        print("ERROR: нет ffmpeg. Ubuntu: sudo apt install ffmpeg", file=sys.stderr); sys.exit(1)
    piper_bin = shutil.which("piper")
    if not piper_bin:
        print("ERROR: нет piper. pip install piper-tts", file=sys.stderr); sys.exit(1)

    model_name = VOICE_MAP[a.voice]
    # piper хранит модели в ~/.local/share/piper-voices ; ищем .onnx
    import glob, pathlib
    cands = glob.glob(str(pathlib.Path.home() / ".local/share/piper-voices/**/*.onnx"), recursive=True)
    model = next((c for c in cands if model_name in c), None)
    if not model:
        print(f"Скачай голос: python -m piper.download_voices {model_name}", file=sys.stderr); sys.exit(1)

    os.makedirs(a.out, exist_ok=True)
    data = json.load(open(a.inp, encoding='utf-8'))
    report = []
    for q in data:
        qid = q['questID']
        for kind, key in (("desc", "description"), ("comp", "completion")):
            text = (q.get(key) or "")[:a.limit_chars]
            if not text.strip():
                continue
            wav = os.path.join(a.out, f"{qid}_{kind}.wav")
            mp3 = os.path.join(a.out, f"{qid}_{kind}.mp3")
            ok = synth_piper(piper_bin, model, text, wav)
            if ok: ok = wav_to_mp3(wav, mp3)
            try: os.remove(wav)
            except OSError: pass
            report.append(f"{qid}_{kind}: {'OK' if ok else 'FAIL'} ({len(text)} ch)")
            print(report[-1])
    open(os.path.join(a.out, "voices_report.txt"), "w", encoding="utf-8").write("\n".join(report))
    print(f"Готово. Папка {a.out} -> клади как Interface/AddOns/CatQuest335_Voices/")
    print("Важно: после добавления mp3 нужен ПОЛНЫЙ рестарт игры, /reload недостаточно.")

if __name__ == '__main__':
    main()
