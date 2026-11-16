#!/usr/bin/env python3
"""Чистка русского текста перед бесплатным TTS: stage-ремарки, числа, ё, ударения-заготовки."""
import argparse, json, re

# Мини-словарь ударений для имен Азерота (расширяй; CatQuest использует ~4700 статей)
STRESS = {
    "Оргриммар": "Оргримма+р",
    "Штормград": "Штормгра+д",
    "Элвинн": "Э+лвинн",
    "Кельтас": "Ке+льтас",
    "Азерот": "Азеро+т",
}

STAGE_RE = re.compile(r"\*.*?\*|\(.*?\)|\[.*?\]")

def expand_numbers_ru(s: str) -> str:
    # Заглушка: Piper/Silero числа читают сами, но сложные "1-60" чиним
    s = s.replace("1-60", "с первого по шестидесятый уровень")
    return s

def clean(s: str) -> str:
    if not s: return ""
    s = s.replace("$B", " ").replace("$b", " ")
    s = re.sub(r"\$[NnCcRr]", "герой", s)  # $N - имя игрока, $C - класс и т.п.
    s = STAGE_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = expand_numbers_ru(s)
    for k, v in STRESS.items():
        s = s.replace(k, v.replace("+", ""))  # + убран: Piper его не ест, оставляем как есть; словарь нужен для XTTS/проверки
    # Ёфикация грубая
    s = s.replace("еще", "ещё").replace("ее ", "её ")
    return s

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', dest='out', required=True)
    a = ap.parse_args()
    data = json.load(open(a.inp, encoding='utf-8'))
    for q in data:
        q['description'] = clean(q.get('description', ''))
        q['completion'] = clean(q.get('completion', ''))
        # Ограничение прототипа: первые 1200 символов, иначе очередь и память 3.3.5 страдают
        q['description'] = q['description'][:1200]
        q['completion'] = q['completion'][:1200]
    json.dump(data, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"OK: {len(data)} cleaned -> {a.out}")

if __name__ == '__main__':
    main()
