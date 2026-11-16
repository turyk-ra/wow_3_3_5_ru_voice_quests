#!/usr/bin/env python3
"""Выгрузка квестов 1-60 (ruRU) из базы AzerothCore для CatQuest335.

Читает quest_template + locales_quest (ruRU), фильтрует по уровню/зоне.
Тексты Blizzard — выгружай только из своей базы для личного фан-проекта, не коммить их в git.
"""
import argparse, json
import mysql.connector

Q = """
SELECT q.ID, q.LogTitle, q.LogDescription, q.AreaDescription, q.QuestDescription, q.QuestCompletionLog,
       q.QuestLevel, q.MinLevel,
       COALESCE(l.Title, '') AS Title_ru, COALESCE(l.Objectives, '') AS Obj_ru,
       COALESCE(l.Details, '') AS Details_ru, COALESCE(l.EndText, '') AS End_ru
FROM quest_template q
LEFT JOIN locales_quest l ON l.ID = q.ID
WHERE 1=1
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--user', default='acore')
    ap.add_argument('--password', default='acore')
    ap.add_argument('--db', default='acore_world')
    ap.add_argument('--locale', default='ruRU')
    ap.add_argument('--min-level', type=int, default=1)
    ap.add_argument('--max-level', type=int, default=60)
    ap.add_argument('--limit', type=int, default=10)
    ap.add_argument('--out', default='data/quests_ru.json')
    a = ap.parse_args()

    con = mysql.connector.connect(host=a.host, user=a.user, password=a.password, database=a.db)
    cur = con.cursor(dictionary=True)
    cur.execute(Q)
    rows = cur.fetchall()
    out = []
    for r in rows:
        lvl = r['QuestLevel'] or r['MinLevel'] or 0
        if lvl == -1: lvl = r['MinLevel'] or 0
        if not (a.min_level <= lvl <= a.max_level):
            continue
        title = r['Title_ru'] or r['LogTitle'] or ''
        details = r['Details_ru'] or r['QuestDescription'] or ''
        endtext = r['End_ru'] or r['QuestCompletionLog'] or ''
        obj = r['Obj_ru'] or r['LogDescription'] or ''
        if not title or (not details and not endtext):
            continue
        out.append({
            'questID': int(r['ID']),
            'level': int(lvl),
            'title': title,
            'description': details,
            'completion': endtext,
            'objective': obj,
        })
        if len(out) >= a.limit:
            break
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"OK: {len(out)} quests -> {a.out} (уровень {a.min_level}-{a.max_level})")
    print("Дальше: python tools/normalize.py --in data/quests_ru.json --out data/quests_ru.clean.json")

if __name__ == '__main__':
    main()
