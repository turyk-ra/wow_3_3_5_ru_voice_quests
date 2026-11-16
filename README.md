# CatQuest335 — русская озвучка квестов 1-60 для WoW 3.3.5a (ruRU)

Фан-проект по мотивам CatQuest (Forever), но для старого клиента 3.3.5а и бесплатного синтеза.

Принцип: тексты берутся из **твоей базы AzerothCore**, синтезируются локально (бесплатно, Piper/Silero/XTTS),
раскладываются по `QuestID`, аддон в `Interface/AddOns` проигрывает их при взятии/сдаче квеста.

Состав:
- `exporter/` — выгрузка текстов из AzerothCore (quest_template + локали, npc_text, page_text)
- `tools/` — чистка текста, ударения, генерация манифеста для аддона
- `tts/` — бесплатный синтез (Piper ru_RU по умолчанию)
- `addon/CatQuest335/` — сам аддон под интерфейс 30300

Статус: прототип. Генерирует озвучку для любых квестов 1-60, очередь, субтитры, кнопки Читать/Стоп.

## Быстрый старт (прототип 10 квестов)

1. Выгрузи квесты из своей базы:
```bash
pip install mysql-connector-python num2words
python exporter/export_quests.py --host 127.0.0.1 --user acore --password acore --db acore_world --locale ruRU --min-level 1 --max-level 60 --limit 10 --out data/quests_ru.json
```

2. Нормализуй + сделай манифест:
```bash
python tools/normalize.py --in data/quests_ru.json --out data/quests_ru.clean.json
python tools/make_manifest.py --in data/quests_ru.clean.json --out addon/CatQuest335/manifest.lua
```

3. Синтезируй бесплатно (Piper):
```bash
pip install -r tts/requirements.txt
python tts/synthesize_piper.py --in data/quests_ru.clean.json --out addon/CatQuest335_Voices --voice irina
```

4. Поставь в клиент:
```
WoW 3.3.5/Interface/AddOns/CatQuest335/
WoW 3.3.5/Interface/AddOns/CatQuest335_Voices/   # сгенерированные mp3 + manifest
```
Удали `Cache/`, включи «Устаревшие модификации», проверь `/cq selftest`.

Подробно — см. `docs/` ниже и комменты в скриптах.

## Про GitHub

Этот проект уже git-репозиторий. Чтобы залить на свой GitHub:
```bash
cd CatQuest335
git remote add origin https://github.com/ТВОЙ_НИК/ТВОЕ_РЕПО.git
git branch -M main
git push -u origin main
```
Никаких токенов мне присылать не надо — пуш делается с твоего ПК.

## Дисклеймер

Некоммерческий фан-проект. Тексты квестов принадлежат Blizzard, синтез — твой локальный.
Войс-паки не коммить в git (они в .gitignore) — храни их в Releases, как делает CatQuest.
