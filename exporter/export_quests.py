#!/usr/bin/env python3
"""Выгрузка квестов 1-60 (ruRU) из базы AzerothCore для CatQuest335.

Поддерживает и новый AzerothCore (quest_template_locale), и старый (locales_quest).
Тексты Blizzard — выгружай только из своей базы для личного фан-проекта, не коммить их в git.
"""
import argparse, json, re
import mysql.connector

def table_exists(cur, name):
    cur.execute("SHOW TABLES LIKE %s", (name,))
    return cur.fetchone() is not None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=3306)
    ap.add_argument('--user', default='acore')
    ap.add_argument('--password', default='acore')
    ap.add_argument('--db', default='acore_world')
    ap.add_argument('--locale', default='ruRU')
    ap.add_argument('--min-level', type=int, default=1)
    ap.add_argument('--max-level', type=int, default=60)
    ap.add_argument('--limit', type=int, default=10)
    ap.add_argument('--zone', type=int, default=None, help='ZoneOrSort, напр. 1=Дун Морог, 12=Элвиннский лес. Без фильтра — все зоны')
    ap.add_argument('--out', default='data/quests_ru.json')
    a = ap.parse_args()

    con = mysql.connector.connect(host=a.host, port=a.port, user=a.user, password=a.password, database=a.db)
    cur = con.cursor(dictionary=True)

    use_new = table_exists(cur, 'quest_template_locale')
    use_old = table_exists(cur, 'locales_quest')
    print(f"tables: quest_template_locale={use_new}, locales_quest={use_old}")

    # ZoneOrSort в старых базах, QuestSortID в новых AzerothCore
    cur.execute("SHOW COLUMNS FROM quest_template LIKE 'QuestSortID'")
    has_questsort = cur.fetchone() is not None
    zone_col = 'QuestSortID' if has_questsort else 'ZoneOrSort'
    print(f"zone column: {zone_col}")
    params = []
    zone_filter = ""
    if a.zone is not None:
        zone_filter = f"WHERE q.{zone_col} = %s"
        params.append(a.zone)
    if use_new:
        # AzerothCore: quest_template_locale(ID, locale, Title, Details, Objectives, EndText, ...)
        q = f"""
            SELECT q.ID, q.LogTitle, q.LogDescription, q.QuestDescription, q.QuestCompletionLog,
                   q.QuestLevel, q.MinLevel, q.{zone_col} AS ZoneOrSort,
                   l.Title AS Title_ru, l.Objectives AS Obj_ru,
                   l.Details AS Details_ru, l.EndText AS End_ru
            FROM quest_template q
            LEFT JOIN quest_template_locale l ON l.ID = q.ID AND l.locale = %s
            {zone_filter}
            ORDER BY q.ID
        """
        cur.execute(q, (a.locale, *params))
    elif use_old:
        cur.execute("""
            SELECT q.ID, q.LogTitle, q.LogDescription, q.QuestDescription, q.QuestCompletionLog,
                   q.QuestLevel, q.MinLevel,
                   l.Title AS Title_ru, l.Objectives AS Obj_ru,
                   l.Details AS Details_ru, l.EndText AS End_ru
            FROM quest_template q
            LEFT JOIN locales_quest l ON l.ID = q.ID
        """)
    else:
        # Нет локалей вообще — только английский из quest_template
        cur.execute("""
            SELECT q.ID, q.LogTitle, q.LogDescription, q.QuestDescription, q.QuestCompletionLog,
                   q.QuestLevel, q.MinLevel
            FROM quest_template q
        """)
    rows = cur.fetchall()
    print(f"rows in quest_template: {len(rows)}")

    # Реплика NPC при сдаче квеста (окно награды) лежит НЕ в quest_template.EndText
    # (это короткая строка журнала "Вернитесь к ..."), а в quest_offer_reward(_locale).RewardText.
    # Английский текст берём только если локали нет вообще — иначе русский голос читал бы английский.
    reward = {}
    has_reward_locale = table_exists(cur, 'quest_offer_reward_locale')
    if table_exists(cur, 'quest_offer_reward') and (a.locale == 'enUS' or not has_reward_locale):
        cur.execute("SELECT ID, RewardText FROM quest_offer_reward")
        reward.update({int(r['ID']): (r['RewardText'] or '') for r in cur.fetchall()})
    if has_reward_locale and a.locale != 'enUS':
        cur.execute("SELECT ID, RewardText FROM quest_offer_reward_locale WHERE locale = %s", (a.locale,))
        for r in cur.fetchall():
            if (r['RewardText'] or '').strip():
                reward[int(r['ID'])] = r['RewardText']
    print(f"reward texts ({a.locale}): {len(reward)}")

    # Кто выдаёт квест (entry NPC / объекта) — аддон сверяет с GUID собеседника,
    # это самый надёжный способ различить квесты с одинаковым названием.
    starters = {}
    for tbl in ('creature_queststarter', 'gameobject_queststarter'):
        if table_exists(cur, tbl):
            cur.execute(f"SELECT id, quest FROM {tbl}")
            for r in cur.fetchall():
                starters.setdefault(int(r['quest']), []).append(int(r['id']))

    # Пол NPC — чтобы мужчин озвучивал мужской голос, женщин женский.
    # Описание читает тот, кто выдаёт квест; реплику сдачи — тот, кто принимает.
    # 0 = мужчина, 1 = женщина, 2/нет = не задан (объект, доска объявлений) -> голос рассказчика
    npc_gender = {}
    if table_exists(cur, 'creature_template_model') and table_exists(cur, 'creature_model_info'):
        cur.execute("""SELECT ctm.CreatureID AS id, cmi.Gender AS g FROM creature_template_model ctm
                       JOIN creature_model_info cmi ON cmi.DisplayID = ctm.CreatureDisplayID
                       WHERE ctm.Idx = 0""")
        npc_gender = {int(r['id']): int(r['g']) for r in cur.fetchall()}
    elif table_exists(cur, 'creature_model_info'):  # старые базы: modelid1 в creature_template
        cur.execute("""SELECT ct.entry AS id, cmi.Gender AS g FROM creature_template ct
                       JOIN creature_model_info cmi ON cmi.DisplayID = ct.modelid1""")
        npc_gender = {int(r['id']): int(r['g']) for r in cur.fetchall()}
    creature_start, creature_end = {}, {}
    for tbl, dst in (('creature_queststarter', creature_start), ('creature_questender', creature_end)):
        if table_exists(cur, tbl):
            cur.execute(f"SELECT id, quest FROM {tbl} ORDER BY id")
            for r in cur.fetchall():
                dst.setdefault(int(r['quest']), []).append(int(r['id']))

    def speaker(npcs):
        """(entry, пол) первого NPC с известным полом; иначе рассказчик."""
        for n in npcs or []:
            g = npc_gender.get(n)
            if g in (0, 1):
                return n, ('m' if g == 0 else 'f')
        return (npcs[0] if npcs else 0), 'n'

    # Маски рас/классов — чтобы различать квесты с одинаковым названием (Альянс/Орда, разные классы)
    races, classes = {}, {}
    cur.execute("SHOW COLUMNS FROM quest_template LIKE 'AllowableRaces'")
    if cur.fetchone():
        cur.execute("SELECT ID, AllowableRaces FROM quest_template")
        races = {int(r['ID']): int(r['AllowableRaces'] or 0) for r in cur.fetchall()}
    if table_exists(cur, 'quest_template_addon'):
        cur.execute("SHOW COLUMNS FROM quest_template_addon LIKE 'AllowableClasses'")
        if cur.fetchone():
            cur.execute("SELECT ID, AllowableClasses FROM quest_template_addon")
            classes = {int(r['ID']): int(r['AllowableClasses'] or 0) for r in cur.fetchall()}
    out = []
    skipped_noru = 0
    for r in rows:
        lvl = r.get('QuestLevel') or r.get('MinLevel') or 0
        if lvl == -1:
            lvl = r.get('MinLevel') or 0
        if not (a.min_level <= (lvl or 0) <= a.max_level):
            continue
        title_ru = (r.get('Title_ru') or '').strip() if 'Title_ru' in r else ''
        details_ru = (r.get('Details_ru') or '').strip() if 'Details_ru' in r else ''
        end_ru = (r.get('End_ru') or '').strip() if 'End_ru' in r else ''
        obj_ru = (r.get('Obj_ru') or '').strip() if 'Obj_ru' in r else ''

        # Если русской строки нет — пропускаем (чтобы пак был чисто RU).
        # Если хочешь EN-фолбэк — убери этот if.
        if use_new or use_old:
            if not title_ru:
                skipped_noru += 1
                continue
        localized = use_new or use_old
        title = title_ru or r.get('LogTitle') or ''
        # при локализованной базе английские тексты не подставляем — русский голос их не прочитает
        details = details_ru if localized else (r.get('QuestDescription') or '')
        qid = int(r['ID'])
        rewardtext = (reward.get(qid) or '').strip()
        obj = obj_ru if localized else (r.get('LogDescription') or '')
        if not title or (not details and not rewardtext):
            continue
        # служебные/вырезанные квесты: <UNUSED>, [UNUSED], <TEST>, "zzOLD..." и т.п.
        if re.search(r'unused|<test|\[test|^zz|deprecated', title, re.I):
            continue
        out.append({
            'questID': qid,
            'level': int(lvl or 0),
            'title': title,
            'description': details,
            'completion': rewardtext,   # то, что NPC говорит в окне награды
            'objective': obj,
            'races': races.get(qid, 0),
            'classes': classes.get(qid, 0),
            'starters': sorted(set(starters.get(qid, []))),
        })
        out[-1]['giver_npc'], out[-1]['giver_gender'] = speaker(creature_start.get(qid))
        out[-1]['ender_npc'], out[-1]['ender_gender'] = speaker(creature_end.get(qid))
        if len(out) >= a.limit:
            break
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"OK: {len(out)} quests -> {a.out} (уровень {a.min_level}-{a.max_level}), пропущено без RU: {skipped_noru}")
    if not out:
        print("Пусто! Причины: 1) в quest_template_locale нет ruRU строк, 2) репак только EN. Проверь: SELECT * FROM quest_template_locale WHERE locale='ruRU' LIMIT 3;")
    else:
        print("Дальше: python tools/normalize.py --in data/quests_ru.json --out data/quests_ru.clean.json")

if __name__ == '__main__':
    main()
