#!/usr/bin/env python3
"""Чистка русского текста перед бесплатным TTS: плейсхолдеры WoW, ремарки, числа, ё.

Плейсхолдеры WoW:
  $N/$n — имя игрока, $C/$c — класс, $R/$r — раса  -> нейтральное слово
  $B/$b — перенос строки                            -> пауза
  $Gмуж:жен; — форма по полу персонажа             -> два варианта текста:
     description / completion       (мужской персонаж)
     description_f / completion_f   (женский, только если текст отличается)
"""
import argparse, json, re

# Мини-словарь ударений для имен Азерота (расширяй; CatQuest использует ~4700 статей).
# Piper знак ударения не понимает, поэтому сейчас словарь только для справки / других TTS.
STRESS = {
    "Оргриммар": "Оргримма+р",
    "Штормград": "Штормгра+д",
    "Элвинн": "Э+лвинн",
    "Кельтас": "Ке+льтас",
    "Азерот": "Азеро+т",
}

STAGE_RE = re.compile(r"\*.*?\*|\(.*?\)|\[.*?\]")
GENDER_RE = re.compile(r"\$[Gg]\s*([^:;]*):([^;]*);")
MAX_CHARS = 1200


def expand_numbers_ru(s: str) -> str:
    """Цифры -> слова (Vosk цифры не читает). Падеж не согласуется, но "5 склянок" -> "пять склянок"."""
    s = s.replace("1-60", "с первого по шестидесятый уровень")
    try:
        from num2words import num2words
    except ImportError:
        return s
    return re.sub(r"\d+", lambda m: num2words(int(m.group(0)), lang="ru"), s)


def yo(s: str) -> str:
    # Только целые слова: раньше "вещей" превращалось в "вещёй", а "более " — в "болеё "
    s = re.sub(r"\b([Ее])ще\b", r"\1щё", s)
    s = re.sub(r"\b([Ее])е\b", r"\1ё", s)
    s = re.sub(r"\b([Нн])ее\b", r"\1её", s)
    return s


def cut(s: str, limit: int = MAX_CHARS) -> str:
    """Обрезает по концу предложения, а не посреди слова."""
    if len(s) <= limit:
        return s
    head = s[:limit]
    m = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    return head[: m + 1] if m > limit // 2 else head.rsplit(" ", 1)[0] + "…"


def clean(s: str, female: bool = False) -> str:
    if not s:
        return ""
    if not re.search(r"[А-Яа-яЁё]", s):
        return ""  # в ruRU-локали базы иногда лежит непереведённый английский текст
    # склонятор русского клиента: |3-6($c) = "класс в 6-м падеже" -> просто слово
    s = re.sub(r"\|3-\d+\((.*?)\)", r"\1", s)
    s = GENDER_RE.sub(lambda m: (m.group(2) if female else m.group(1)).strip(), s)
    s = re.sub(r"(\s*\$[Bb])+", "\x00", s)
    s = re.sub(r"([.!?…:;,])\s*\x00", r"\1 ", s)  # перед переносом уже есть знак — точку не добавляем
    s = s.replace("\x00", ". ")
    s = re.sub(r"\$[Nn]", "путник", s)
    s = re.sub(r"\$[CcRr]", "герой", s)
    s = re.sub(r"\$\w", "", s)  # прочие неизвестные плейсхолдеры
    s = STAGE_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^[\s.]+", "", s).strip()
    s = expand_numbers_ru(s)
    s = yo(s)
    return cut(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', dest='out', required=True)
    a = ap.parse_args()
    data = json.load(open(a.inp, encoding='utf-8'))
    nf = 0
    for q in data:
        for key in ('description', 'completion'):
            raw = q.get(key) or ''
            q[key] = clean(raw)
            fem = clean(raw, female=True)
            if fem != q[key]:
                q[key + '_f'] = fem
                nf += 1
            else:
                q.pop(key + '_f', None)
    json.dump(data, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"OK: {len(data)} cleaned -> {a.out} (женских вариантов: {nf})")


if __name__ == '__main__':
    main()
