#!/usr/bin/env python3
"""Синтез RU для CatQuest335 через Vosk TTS (локально, бесплатно, многоголосая модель).

Голос выбирается по полу NPC (поля giver_* / ender_* из exporter/export_quests.py):
  описание (desc) читает NPC, который выдаёт квест; реплику сдачи (comp) — NPC, который принимает.
  Мужчины -> один из --male, женщины -> один из --female (стабильно по ID NPC: у одного NPC
  всегда один и тот же голос), предметы/доски/неизвестные -> --narrator.

Установка (один раз):
  python -m venv tts/.venv
  tts/.venv/Scripts/python -m pip install vosk-tts
  модель: https://alphacephei.com/vosk/models/vosk-model-tts-ru-0.10-multi.zip -> распаковать в tts/models/

Примеры:
  tts/.venv/Scripts/python tts/synthesize_vosk.py --samples --out tts/samples        # послушать все голоса
  tts/.venv/Scripts/python tts/synthesize_vosk.py --in data/starter_1_10.clean.json --out addon/CatQuest335_Voices
Потом: python tools/make_manifest.py ... --voices addon/CatQuest335_Voices
"""
import argparse, json, os, re, shutil, subprocess, sys, wave, zlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(HERE, "models", "vosk-model-tts-ru-0.10-multi")
RATE = 22050

# 20 Коршунов, 28 Лужков, 26 Лебедев, 13 Финагин, 47 Суслов, 27 Литвинов, 31 Михеев, 17 Князев
DEFAULT_MALE = [20, 28, 26, 13, 47, 27, 31, 17]
# 2 Бабенко, 5 Благушко, 11 Егорова, 19 Корнева, 36 Нижегородова, 44 Шамаева, 51 Урбанская
DEFAULT_FEMALE = [2, 5, 11, 19, 36, 44, 51]
DEFAULT_NARRATOR = 10  # Чонишвили

KINDS = {  # kind -> (поле текста, чей голос)
    "desc": ("description", "giver"),
    "desc_f": ("description_f", "giver"),
    "comp": ("completion", "ender"),
    "comp_f": ("completion_f", "ender"),
}

# Ударения для имён Азерота: "+" ПЕРЕД ударной гласной (Vosk это понимает).
# Слова, которых нет в словаре модели, без этого читаются без ударения. Расширяй.
STRESS = {
    "Штормград": "Штормгр+ад",
    "Оргриммар": "Оргр+иммар",
    "Азерот": "Азер+от",
    "Стальгорн": "Стальг+орн",
    "Дарнас": "Дарн+ас",
    "Подгород": "П+одгород",
    "Громовой Утёс": "Громов+ой Ут+ёс",
    "Элвинн": "+Элвинн",
    "Голдшир": "Голдш+ир",
    "Дун Морог": "Дун М+орог",
    "Тельдрассил": "Тельдрасс+ил",
    "Дуротар": "Дурот+ар",
    "Мулгор": "Мулг+ор",
    "Тирисфаль": "Тирисф+аль",
    "Брилл": "Бр+илл",
    "Каз Модан": "Каз Мод+ан",
    "Лок Модан": "Лок Мод+ан",
    "Западный Край": "З+ападный Кр+ай",
    "Красногорье": "Красног+орье",
    "Сумеречный лес": "С+умеречный л+ес",
}

PUNCT = " ,.?!;:\"()-+"


class VoskVoice:
    def __init__(self, model_path):
        from vosk_tts import Model, Synth
        self.model = Model(model_path=model_path)
        self.synth = Synth(self.model)
        self.allowed = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя" + PUNCT)
        self.n_speakers = int(self.model.config.get("num_speakers") or
                              len(self.model.config.get("speaker_id_map") or {}) or 1)

    def sanitize(self, text):
        for k, v in STRESS.items():
            text = re.sub(r"\b" + re.escape(k) + r"\b", v, text)
        text = (text.replace("—", "-").replace("–", "-").replace("…", "...")
                .replace("«", '"').replace("»", '"').replace("„", '"').replace("“", '"').replace("”", '"')
                .replace("’", "").replace("'", ""))
        out = []
        for ch in text:
            low = ch.lower()
            out.append(ch if (low in self.allowed or ch.isspace()) else " ")
        text = re.sub(r"\s+", " ", "".join(out))
        text = re.sub(r"\s+([,.?!;:])", r"\1", text)
        text = re.sub(r"\(\s*\)", " ", text)
        return text.strip(" ,;:-")

    def chunks(self, text, limit=300):
        """Режем по предложениям: короткие куски модель читает стабильнее, BERT не переполняется."""
        sents = re.split(r"(?<=[.!?])\s+", text)
        cur = ""
        for s in sents:
            while len(s) > limit:  # очень длинное предложение — по запятым/пробелам
                cut = max(s.rfind(", ", 0, limit), s.rfind(" ", 0, limit))
                cut = cut if cut > limit // 3 else limit
                piece, s = s[:cut + 1].strip(), s[cut + 1:].strip()
                if cur:
                    yield cur
                    cur = ""
                yield piece
            if cur and len(cur) + 1 + len(s) > limit:
                yield cur
                cur = s
            else:
                cur = (cur + " " + s).strip()
        if cur:
            yield cur

    def to_wav(self, text, wav_path, speaker, rate):
        text = self.sanitize(text)
        if not re.search(r"[а-яё]", text.lower()):
            return False
        gap = np.zeros(int(RATE * 0.22), dtype=np.int16)
        parts = []
        for ch in self.chunks(text):
            if not re.search(r"[а-яё]", ch.lower()):
                continue
            parts.append(self.synth.synth_audio(ch, speaker_id=speaker, speech_rate=rate))
            parts.append(gap)
        if not parts:
            return False
        audio = np.concatenate(parts[:-1])
        with wave.open(wav_path, "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(RATE)
            f.writeframes(audio.astype(np.int16).tobytes())
        return True


def to_mp3(wav, mp3, ffmpeg):
    # +0.6 с тишины в конце: аддон играет через PlayMusic (он зацикливает) и останавливает в этой паузе
    r = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", wav, "-af", "apad=pad_dur=0.6",
                        "-ac", "1", "-b:a", "64k", mp3])
    return r.returncode == 0


def ids(s):
    return [int(x) for x in str(s).split(",") if x.strip() != ""]


def pick_speaker(npc, gender, a):
    pool = {"m": a.male, "f": a.female}.get(gender)
    if not pool:
        return a.narrator
    return pool[zlib.crc32(str(npc).encode()) % len(pool)]  # стабильно для одного NPC


SAMPLE = ("Приветствую, путник! Гаррик Тихокрад уже много недель не даёт покоя нашим крестьянам. "
          "Принеси мне его голову, и Штормград тебя щедро наградит.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    # Подобраны по tts/rate_voices.py: разборчивость (CER 0.03) + высота голоса соответствует полу.
    # Имена дикторов: config.json модели -> speaker_id_map. Пробы всех голосов: --samples.
    ap.add_argument("--male", type=ids, default=DEFAULT_MALE, help="ID голосов для мужчин, через запятую")
    ap.add_argument("--female", type=ids, default=DEFAULT_FEMALE, help="ID голосов для женщин")
    ap.add_argument("--narrator", type=int, default=DEFAULT_NARRATOR, help="голос для предметов/досок")
    ap.add_argument("--rate", type=float, default=1.0, help="темп речи: 1.1 = на 10%% быстрее")
    ap.add_argument("--kinds", default=",".join(KINDS))
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--samples", action="store_true", help="сделать по пробной фразе каждым голосом модели")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    a = ap.parse_args()
    if not a.ffmpeg:
        sys.exit("нет ffmpeg в PATH (или укажи --ffmpeg)")
    if not os.path.isdir(a.model):
        sys.exit(f"нет модели: {a.model}")

    voice = VoskVoice(a.model)
    os.makedirs(a.out, exist_ok=True)
    print(f"модель: {a.model}, голосов: {voice.n_speakers}", flush=True)

    if a.samples:
        for sid in range(voice.n_speakers):
            wav = os.path.join(a.out, f"voice_{sid}.wav")
            voice.to_wav(SAMPLE, wav, sid, a.rate)
            to_mp3(wav, os.path.join(a.out, f"voice_{sid}.mp3"), a.ffmpeg)
            os.remove(wav)
            print(f"voice_{sid}.mp3", flush=True)
        return

    kinds = [k.strip() for k in a.kinds.split(",") if k.strip()]
    data = json.load(open(a.inp, encoding="utf-8"))
    report, vmap, n_ok, n_fail = [], [], 0, 0
    for q in data:
        qid = q["questID"]
        for kind in kinds:
            field, who = KINDS[kind]
            text = (q.get(field) or "").strip()
            if not text:
                continue
            npc, gender = q.get(f"{who}_npc", 0), q.get(f"{who}_gender", "n")
            sid = pick_speaker(npc, gender, a)
            mp3 = os.path.join(a.out, f"{qid}_{kind}.mp3")
            vmap.append(f"{qid}_{kind}\tnpc={npc}\t{gender}\tvoice={sid}")
            if a.skip_existing and os.path.isfile(mp3):
                continue
            wav = mp3[:-4] + ".wav"
            try:
                ok = voice.to_wav(text, wav, sid, a.rate) and to_mp3(wav, mp3, a.ffmpeg)
            except Exception as e:
                print(f"  ошибка {qid}_{kind}: {e!r}", file=sys.stderr, flush=True)
                ok = False
            finally:
                if os.path.exists(wav):
                    os.remove(wav)
            if not ok and os.path.exists(mp3):
                os.remove(mp3)
            n_ok += ok; n_fail += (not ok)
            report.append(f"{qid}_{kind}: {'OK' if ok else 'FAIL'} voice={sid} ({len(text)} ch)")
            print(report[-1], flush=True)
    open(os.path.join(a.out, "voices_report.txt"), "w", encoding="utf-8").write("\n".join(report) + "\n")
    open(os.path.join(a.out, "voices_map.txt"), "w", encoding="utf-8").write("\n".join(vmap) + "\n")
    print(f"Готово: OK={n_ok} FAIL={n_fail}")


if __name__ == "__main__":
    main()
