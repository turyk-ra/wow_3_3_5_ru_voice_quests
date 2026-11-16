#!/usr/bin/env python3
"""Прогон аддона CatQuest335 вне игры: настоящие core.lua + manifest.lua в LuaJIT (Lua 5.1, как в WoW)
с заглушками API клиента 3.3.5. Проверяет автозапуск, очередь, Повтор/Далее/Стоп, возврат настроек музыки.

  tts/.venv/Scripts/python -m pip install lupa
  tts/.venv/Scripts/python tests/sim_addon.py
"""
import os, sys
from lupa import luajit21 as lupa

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "addon", "CatQuest335")

MOCK = r"""
local log = {}
_LOG = log
local function L(s) table.insert(log, s) end
_CVARS = { Sound_EnableMusic = "1", Sound_MusicVolume = "0.1", Sound_EnableAllSound = "1", Sound_MasterVolume = "1" }
function GetCVar(k) return _CVARS[k] end
function SetCVar(k, v) _CVARS[k] = tostring(v) end
function PlayMusic(p) L("PlayMusic " .. p:match("([^\\]+)%.mp3$")) end
function StopMusic() L("StopMusic") end
function PlaySoundFile() L("PlaySoundFile!") end
DEFAULT_CHAT_FRAME = { AddMessage = function(_, m) L("CHAT " .. m) end }

_FRAMES = {}
local FrameMT = {}
FrameMT.__index = function(t, k)
  local f = rawget(FrameMT, k)
  if f then return f end
  return function() end -- любые прочие методы — no-op
end
function FrameMT.SetScript(self, ev, fn) self._scripts[ev] = fn end
function FrameMT.RegisterEvent(self, ev) self._events[ev] = true end
function FrameMT.Show(self) self._shown = true end
function FrameMT.Hide(self) self._shown = false end
function FrameMT.IsShown(self) return self._shown end
function FrameMT.SetText(self, t) self._text = t end
function FrameMT.GetText(self) return self._text end
function FrameMT.SetUnit(self, u) self._unit = u; L("SetUnit " .. u) end
function FrameMT.SetCamera(self, c) self._cam = c end
local function newObj()
  local o = setmetatable({ _scripts = {}, _events = {}, _shown = true }, FrameMT)
  return o
end
function FrameMT.CreateFontString() return newObj() end
function FrameMT.CreateTexture() return newObj() end
function CreateFrame(kind, name, parent)
  local f = newObj()
  table.insert(_FRAMES, f)
  if name then _G[name] = f end
  return f
end
SlashCmdList = {}
UIParent = newObj()
QuestFrameDetailPanel, QuestFrameAcceptButton = newObj(), newObj()
QuestFrameRewardPanel, QuestFrameCompleteQuestButton = newObj(), newObj()

-- состояние "окна квеста" и мира
_W = { title = "", obj = "", npc = nil, guid = nil, sex = 2, race = "Human", class = "WARRIOR", log = {} }
function GetTitleText() return _W.title end
function GetObjectiveText() return _W.obj end
function UnitName(u) if u == "npc" then return _W.npc end if u == "player" then return "Тест" end end
function UnitExists(u) if u == "npc" then return _W.npc ~= nil end return u == "player" end
function UnitGUID(u) if u == "npc" then return _W.guid end end
function UnitRace() return "Человек", _W.race end
function UnitClass() return "Воин", _W.class end
function UnitSex() return _W.sex end
function GetNumQuestLogEntries() return #_W.log end
function GetQuestLogTitle(i) local e = _W.log[i]; return e.title, 1, nil, nil, nil, nil, nil, nil, e.id end

function _FIRE(ev, ...)
  for _, f in ipairs(_FRAMES) do
    if f._events[ev] and f._scripts.OnEvent then f._scripts.OnEvent(f, ev, ...) end
  end
end
function _TICK(sec, step)
  step = step or 0.05
  local t = 0
  while t < sec - 1e-9 do
    for _, f in ipairs(_FRAMES) do
      if f._scripts.OnUpdate then f._scripts.OnUpdate(f, step) end
    end
    t = t + step
  end
end
function _CLEAR() for i = #log, 1, -1 do log[i] = nil end end
"""


def main():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(MOCK)
    for f in ("manifest.lua", "core.lua"):
        src = open(os.path.join(ADDON, f), encoding="utf-8").read()
        lua.execute(src)
    G = lua.globals()
    W = G._W
    fails = []

    def log():
        return [G._LOG[i] for i in range(1, len(G._LOG) + 1)]

    def music():
        return [l for l in log() if l.startswith("PlayMusic") or l == "StopMusic"]

    def check(name, cond, extra=""):
        print(("  OK   " if cond else "  FAIL ") + name + (("  " + str(extra)) if not cond else ""))
        if not cond:
            fails.append(name)

    M = G.CatQuest335Manifest

    def dur(qid, kind):
        return M[qid].v[kind]

    def talk(qid, npc="Маршал Мак-Брайд", guid=None):
        W.title = M[qid].title
        W.obj = M[qid].obj
        W.npc = npc
        W.guid = guid

    print("== загрузка")
    G._FIRE("ADDON_LOADED", "CatQuest335")
    G._FIRE("PLAYER_LOGIN")
    check("сообщение о загрузке", any("загружен" in l for l in log()))
    check("PlaySoundFile не используется", "PlaySoundFile!" not in log())

    print("== автозапуск при взятии")
    G._CLEAR()
    talk(6)
    G._FIRE("QUEST_DETAIL")
    G._TICK(0.1)
    check("играет 6_desc", music() == ["PlayMusic 6_desc"], music())
    check("громкость голоса подставлена", G._CVARS.Sound_MusicVolume == "1", G._CVARS.Sound_MusicVolume)
    check("портрет = npc, камера лица", G.CatQuest335Frame.portrait._unit == "npc" and G.CatQuest335Frame.portrait._cam == 0)

    print("== очередь: второй квест ждёт первый")
    G._CLEAR()
    talk(7)
    G._FIRE("QUEST_DETAIL")
    G._TICK(0.2)
    G._FIRE("QUEST_DETAIL")  # повторное открытие того же квеста — без дубля
    G._TICK(0.2)
    check("первый не прерван", music() == [], music())
    check("в очереди 1", len(G.CatQuest335.queue) == 1, len(G.CatQuest335.queue))
    check("счётчик очереди в окне", "в очереди: 1" in (G.CatQuest335Frame.sub._text or ""))
    W.npc = None  # отошли от NPC
    G._CLEAR()
    G._TICK(dur(6, "desc"))
    check("после конца 6 играет 7", music() == ["StopMusic", "PlayMusic 7_desc"], music())
    check("NPC ушёл -> значок вместо лица", G.CatQuest335Frame.icon._shown and not G.CatQuest335Frame.portrait._shown)

    print("== Повтор прерывает и играет заново сразу")
    G._CLEAR()
    G._TICK(1.0)
    G.CQ_Repeat()
    G._TICK(0.15)
    check("7_desc заново", music() == ["StopMusic", "PlayMusic 7_desc"], music())

    print("== сдача из журнала встаёт в очередь, Далее переключает")
    G._CLEAR()
    W.log = lua.table_from([lua.table_from({"title": M[6].title, "id": 6})])
    talk(6)
    G._FIRE("QUEST_COMPLETE")
    G._TICK(0.1)
    check("сдача в очереди", len(G.CatQuest335.queue) == 1 and music() == [], (len(G.CatQuest335.queue), music()))
    G.CQ_Next()
    G._TICK(0.15)
    check("Далее -> 6_comp", music() == ["StopMusic", "PlayMusic 6_comp"], music())

    print("== Стоп: тишина, очередь пуста, музыка игрока вернулась")
    talk(7)
    G._FIRE("QUEST_DETAIL")
    G._TICK(0.1)
    G._CLEAR()
    G.CQ_Stop(True)
    G._TICK(0.3)
    check("оборвано и ничего не запущено", music() == ["StopMusic"], music())
    check("очередь пуста", len(G.CatQuest335.queue) == 0)
    check("настройки музыки вернулись", G._CVARS.Sound_EnableMusic == "1" and G._CVARS.Sound_MusicVolume == "0.1",
          (G._CVARS.Sound_EnableMusic, G._CVARS.Sound_MusicVolume))
    check("окно скрыто", not G.CatQuest335Frame._shown)

    print("== Стоп, потом Повтор — один голос")
    G._CLEAR()
    G.CQ_Repeat()
    G._TICK(0.2)
    # последней звучала 6_comp (7_desc стояла в очереди и была снята Стопом)
    check("ровно один запуск последней звучавшей", music() == ["PlayMusic 6_comp"], music())

    print("== естественный конец: музыка игрока возвращается")
    G._CLEAR()
    G._TICK(dur(6, "comp") + 0.5)
    check("конец без нового запуска", music() == ["StopMusic"], music())
    check("настройки музыки вернулись", G._CVARS.Sound_MusicVolume == "0.1")

    print("== окно квеста не готово в момент события — повторная попытка")
    G._CLEAR()
    W.title = ""
    W.npc = "Маршал Мак-Брайд"
    G._FIRE("QUEST_DETAIL")
    G._TICK(0.1)
    W.title = M[7].title
    W.obj = M[7].obj
    G._TICK(0.2)
    check("сыграл после повторной попытки", music() == ["PlayMusic 7_desc"], music())
    G.CQ_Stop(True); G._TICK(0.2)

    print("== квест без озвучки — одно серое сообщение")
    G._CLEAR()
    W.title = "Несуществующий квест"
    G._FIRE("QUEST_DETAIL")
    G._TICK(0.6)
    check("ничего не играет", music() == [], music())

    print("== женский персонаж получает _f вариант")
    G._CLEAR()
    W.sex = 3
    fq = next((k for k in M.keys() if M[k].v.desc_f), None)
    talk(fq)
    G._FIRE("QUEST_DETAIL")
    G._TICK(0.1)
    check(f"играет {fq}_desc_f", music() == [f"PlayMusic {fq}_desc_f"], music())
    G.CQ_Stop(True); G._TICK(0.2); W.sex = 2

    print("== /cq queue off -> новая реплика прерывает")
    G.SlashCmdList.CQ("queue off")
    G._CLEAR()
    talk(6); G._FIRE("QUEST_DETAIL"); G._TICK(0.1)
    talk(7); G._FIRE("QUEST_DETAIL"); G._TICK(0.15)
    check("6 прервано, играет 7", music() == ["PlayMusic 6_desc", "StopMusic", "PlayMusic 7_desc"], music())
    G.SlashCmdList.CQ("queue on")
    G.CQ_Stop(True); G._TICK(0.2)

    print("== /cq auto off -> без автозапуска")
    G.SlashCmdList.CQ("auto off")
    G._CLEAR()
    talk(6); G._FIRE("QUEST_DETAIL"); G._TICK(0.3)
    check("тишина", music() == [], music())
    G.SlashCmdList.CQ("auto on")

    print("== выход посреди реплики — настройки музыки возвращаются")
    talk(6); G._FIRE("QUEST_DETAIL"); G._TICK(0.1)
    G._FIRE("PLAYER_LOGOUT")
    check("музыка игрока", G._CVARS.Sound_MusicVolume == "0.1" and G.CatQuest335DB.savedMusic is None)

    print()
    print("ВСЕ ПРОВЕРКИ ПРОШЛИ" if not fails else f"ПРОВАЛЕНО: {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
