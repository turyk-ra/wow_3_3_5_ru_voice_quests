#!/usr/bin/env python3
"""Бесплатный синтез RU для CatQuest335 через Piper (локально, без ключей).

Установка модели (один раз):
  python -m piper.download_voices ru_RU-irina-medium  (женский)
  или: ru_RU-dmitri-medium / ru_RU-ruslan-medium (мужские)

Пример:
  python tts/synthesize_piper.py --in data/quests_ru.clean.json --out addon/CatQuest335_Voices --voice irina
На выходе: <questID>_desc.mp3, <questID>_comp.mp3 (+ _desc_f / _comp_f для женских форм) и voices_report.txt
Потом ОБЯЗАТЕЛЬНО: python tools/make_manifest.py ... --voices addon/CatQuest335_Voices
(манифест строится по реально существующим файлам и их длительности).

Нужно: pip install -r tts/requirements.txt + установленный ffmpeg.
"""
import argparse, json, subprocess, shutil, os, sys, wave, pathlib, glob

VOICE_MAP = {
    "irina": "ru_RU-irina-medium",
    "dmitri": "ru_RU-dmitri-medium",
    "ruslan": "ru_RU-ruslan-medium",
    "denis": "ru_RU-denis-medium",
}

# Реплики: kind в имени файла -> поле в json
KINDS = {
    "desc": "description",
    "desc_f": "description_f",
    "comp": "completion",
    "comp_f": "completion_f",
}


def find_model(model_name):
    cands = []
    cands += glob.glob(str(pathlib.Path.home() / ".local/share/piper-voices/**/*.onnx"), recursive=True)
    here = pathlib.Path(__file__).parent
    for base in [pathlib.Path.cwd(), here, pathlib.Path.cwd() / "models", pathlib.Path.home()]:
        try:
            if base.is_dir():
                cands += glob.glob(str(base / "*.onnx"))
                if base in (pathlib.Path.cwd(), here):
                    cands += glob.glob(str(base / "**/*.onnx"), recursive=True)
        except Exception:
            pass
    for c in cands:
        if model_name in os.path.basename(c):
            return c
    for c in cands:
        if "ru_RU" in os.path.basename(c):
            return c
    return None


class Synth:
    """Piper через Python API (модель грузится один раз). Если API нет — CLI в режиме UTF-8."""

    def __init__(self, model):
        self.model = model
        self.voice = None
        try:
            from piper import PiperVoice
            self.voice = PiperVoice.load(model)
            print("piper: python API")
        except Exception as e:
            self.piper_bin = shutil.which("piper")
            if not self.piper_bin:
                print(f"ERROR: нет piper ({e}). pip install piper-tts", file=sys.stderr)
                sys.exit(1)
            print(f"piper: CLI {self.piper_bin}")

    def __call__(self, text, wav_path):
        if self.voice is not None:
            with wave.open(wav_path, "wb") as wf:
                self.voice.synthesize_wav(text, wf)
            return True
        # ВАЖНО: без PYTHONUTF8 piper на Windows читает stdin в cp1251 и озвучивает кракозябры
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        p = subprocess.run([self.piper_bin, "--model", self.model, "--output_file", wav_path],
                           input=text.encode("utf-8"), capture_output=True, env=env)
        return p.returncode == 0


def find_ffmpeg(cli_arg=None):
    if cli_arg and os.path.isfile(cli_arg):
        return cli_arg
    w = shutil.which("ffmpeg")
    if w:
        return w
    here = pathlib.Path(__file__).parent
    for c in [here / "ffmpeg.exe", here / "ffmpeg", pathlib.Path.cwd() / "ffmpeg.exe", pathlib.Path.cwd() / "ffmpeg"]:
        if c.is_file():
            return str(c)
    return None


def wav_to_mp3(wav, mp3, ffmpeg_bin):
    # 64kbps mono 22 kHz — чтобы пак для 3.3.5 не раздулся
    # +0.6 с тишины в конце: аддон играет через PlayMusic (он зацикливает) и останавливает в этой паузе
    r = subprocess.run([ffmpeg_bin, "-y", "-v", "error", "-i", wav, "-af", "apad=pad_dur=0.6", "-ac", "1", "-b:a", "64k", mp3])
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', dest='out', required=True)
    ap.add_argument('--voice', default='irina', choices=list(VOICE_MAP))
    ap.add_argument('--kinds', default=','.join(KINDS),
                    help='какие реплики синтезировать, через запятую: ' + ','.join(KINDS))
    ap.add_argument('--skip-existing', action='store_true', help='не пересинтезировать уже готовые mp3')
    ap.add_argument('--ffmpeg', default=None, help='путь к ffmpeg.exe если он не в PATH')
    ap.add_argument('--model', default=None, help='прямой путь к .onnx модели, если авто-поиск не находит')
    a = ap.parse_args()

    kinds = [k.strip() for k in a.kinds.split(',') if k.strip()]
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        sys.exit(f"неизвестные kinds: {bad}; допустимо: {list(KINDS)}")

    model = a.model or find_model(VOICE_MAP[a.voice])
    if not model:
        print(f"Скачай голос: python -m piper.download_voices {VOICE_MAP[a.voice]}", file=sys.stderr)
        print("Если скачал но не находит — найди .onnx и передай --model ПУТЬ", file=sys.stderr)
        sys.exit(1)
    print(f"model: {model}")

    ffmpeg_bin = find_ffmpeg(a.ffmpeg)
    if not ffmpeg_bin:
        sys.exit("ERROR: нет ffmpeg. Положи ffmpeg.exe рядом со скриптом или укажи --ffmpeg D:/ffmpeg/bin/ffmpeg.exe")
    print(f"ffmpeg: {ffmpeg_bin}")

    synth = Synth(model)
    os.makedirs(a.out, exist_ok=True)
    data = json.load(open(a.inp, encoding='utf-8'))
    report, n_ok, n_fail = [], 0, 0
    for q in data:
        qid = q['questID']
        for kind in kinds:
            text = (q.get(KINDS[kind]) or "").strip()
            if not text:
                continue
            wav = os.path.join(a.out, f"{qid}_{kind}.wav")
            mp3 = os.path.join(a.out, f"{qid}_{kind}.mp3")
            if a.skip_existing and os.path.isfile(mp3):
                continue
            try:
                ok = synth(text, wav) and wav_to_mp3(wav, mp3, ffmpeg_bin)
            except Exception as e:
                print(f"  ошибка {qid}_{kind}: {e}", file=sys.stderr)
                ok = False
            finally:
                try: os.remove(wav)
                except OSError: pass
            if not ok:
                try: os.remove(mp3)  # битый/недописанный mp3 не оставляем
                except OSError: pass
            n_ok += ok; n_fail += (not ok)
            report.append(f"{qid}_{kind}: {'OK' if ok else 'FAIL'} ({len(text)} ch)")
            print(report[-1], flush=True)
    open(os.path.join(a.out, "voices_report.txt"), "w", encoding="utf-8").write("\n".join(report) + "\n")
    print(f"Готово: OK={n_ok} FAIL={n_fail}. Теперь пересобери манифест: "
          f"python tools/make_manifest.py --in {a.inp} --voices {a.out} --out addon/CatQuest335/manifest.lua")
    print("Важно: после добавления mp3 нужен ПОЛНЫЙ рестарт игры, /reload недостаточно.")


if __name__ == '__main__':
    main()
