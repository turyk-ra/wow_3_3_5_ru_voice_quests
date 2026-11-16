-- CatQuest335 core.lua (WoW 3.3.5a, interface 30300)
-- QuestID-based voiceover: Interface\AddOns\CatQuest335_Voices\<questID>_<kind>.mp3
--   kind: desc / desc_f (взятие, женский вариант) / comp / comp_f (сдача)
-- Манифест (manifest.lua) генерируется tools/make_manifest.py по реально существующим файлам:
--   CatQuest335Manifest[qid] = { title=, races=, classes=, obj=, v = { desc=23.4, comp=6.1, ... } }
--   CatQuest335TitleToID[title] = { qid1, qid2, ... }
--
-- Ограничения клиента 3.3.5:
--   * звук PlaySoundFile нельзя остановить, поэтому голос играет через PlayMusic/StopMusic
--     (на время реплики музыка зоны молчит);
--   * о конце файла клиент не сообщает — длительность берем из манифеста;
--   * новые mp3 клиент видит только после полного перезапуска игры (не /reload).

CatQuest335 = CatQuest335 or {}
local CQ = CatQuest335
CQ.history = {}

local VOICE_DIR = "Interface\\AddOns\\CatQuest335_Voices\\"

local function Print(msg) DEFAULT_CHAT_FRAME:AddMessage("|cff88ff88[CatQuest335]|r " .. tostring(msg)) end
local function Debug(msg) if CatQuest335DB and CatQuest335DB.debug then Print("|cff999999" .. tostring(msg) .. "|r") end end

------------------------------------------------------------------------
-- Нормализация строк
------------------------------------------------------------------------
local function NormWS(s)
  if not s then return nil end
  s = tostring(s):gsub("^%s+", ""):gsub("%s+$", ""):gsub("%s+", " ")
  return s
end

-- трим + схлопывание пробелов + ё->е (UTF-8: ё=D1 91, Ё=D0 81, е=D0 B5, Е=D0 95)
local function NormTitle(s)
  s = NormWS(s)
  if not s then return nil end
  s = s:gsub("\209\145", "\208\181"):gsub("\208\129", "\208\149")
  return s
end

local NormMap
local function BuildNormMap()
  NormMap = {}
  for title, ids in pairs(CatQuest335TitleToID or {}) do
    NormMap[NormTitle(title)] = ids
  end
end

------------------------------------------------------------------------
-- Определение QuestID
------------------------------------------------------------------------
local RACE_ID = { Human = 1, Orc = 2, Dwarf = 3, NightElf = 4, Scourge = 5, Tauren = 6,
                  Gnome = 7, Troll = 8, BloodElf = 10, Draenei = 11 }
local CLASS_ID = { WARRIOR = 1, PALADIN = 2, HUNTER = 3, ROGUE = 4, PRIEST = 5, DEATHKNIGHT = 6,
                   SHAMAN = 7, MAGE = 8, WARLOCK = 9, DRUID = 11 }

local function MaskAllows(mask, id)
  if not mask or mask <= 0 or not id then return true end
  return bit.band(mask, 2 ^ (id - 1)) ~= 0
end

local function PlayerFits(e)
  local _, race = UnitRace("player")
  local _, class = UnitClass("player")
  return MaskAllows(e.races, RACE_ID[race]) and MaskAllows(e.classes, CLASS_ID[class])
end

-- В 3.3.5 GetQuestLogTitle возвращает questID ДЕВЯТЫМ значением:
-- title, level, tag, suggestedGroup, isHeader, isCollapsed, isComplete, isDaily, questID
local function GetQuestIDFromLogByTitle(title)
  local nt = NormTitle(title)
  if not nt then return nil end
  for i = 1, GetNumQuestLogEntries() do
    local t, _, _, _, isHeader, _, _, _, qid = GetQuestLogTitle(i)
    if not isHeader and qid and NormTitle(t) == nt then return qid end
  end
  return nil
end

local function CandidatesByTitle(title)
  local ids = CatQuest335TitleToID and CatQuest335TitleToID[title]
  if not ids then
    if not NormMap then BuildNormMap() end
    ids = NormMap[NormTitle(title)]
  end
  return ids
end

-- entry собеседника из GUID. 3.3.5: "0xF130" + 6 hex entry + 6 hex счётчик
-- (F130 — существо, F110 — игровой объект, например доска объявлений).
local function NpcEntry()
  local guid = UnitGUID("npc")
  if not guid or #guid < 12 then return nil end
  local high = guid:sub(3, 6):upper()
  if high ~= "F130" and high ~= "F150" and high ~= "F110" then return nil end
  return tonumber(guid:sub(7, 12), 16)
end

local function Filter(ids, pred)
  local out = {}
  for _, qid in ipairs(ids) do
    if pred(qid) then table.insert(out, qid) end
  end
  return out
end

-- Из нескольких квестов с одинаковым названием выбираем: по NPC-собеседнику,
-- затем по расе/классу игрока, затем по началу текста цели (GetObjectiveText).
local function PickCandidate(ids)
  if not ids or #ids == 0 then return nil end
  if #ids == 1 then return ids[1] end
  local M = CatQuest335Manifest
  local fit = ids
  local entry = NpcEntry()
  if entry then
    local byNpc = Filter(fit, function(qid)
      for _, n in ipairs((M[qid] and M[qid].npc) or {}) do if n == entry then return true end end
      return false
    end)
    if #byNpc > 0 then fit = byNpc end
  end
  if #fit == 1 then return fit[1] end
  local byPlayer = Filter(fit, function(qid) return M[qid] and PlayerFits(M[qid]) end)
  if #byPlayer > 0 then fit = byPlayer end
  if #fit == 1 then return fit[1] end
  local obj = GetObjectiveText and NormWS(GetObjectiveText())
  if obj and obj ~= "" then
    for _, qid in ipairs(fit) do
      local p = M[qid] and M[qid].obj
      if p and p ~= "" and obj:sub(1, #p) == p then return qid end
    end
  end
  Debug("неоднозначное название, беру первый из " .. #fit)
  return fit[1]
end

-- context: "detail" (взятие) | "complete" (сдача)
local function GetCurrentQuestID(context)
  local apiID
  if GetQuestID then -- в чистом 3.3.5 нет, но есть в некоторых сборках
    local ok, qid = pcall(GetQuestID)
    if ok and qid and qid ~= 0 then
      apiID = qid
      -- верим API, только если такой квест есть в манифесте; иначе пробуем по названию
      if CatQuest335Manifest and CatQuest335Manifest[qid] then return qid end
    end
  end
  local title = GetTitleText and GetTitleText()
  if not title or title == "" then return apiID end
  CQ.lastTitle = title
  -- при сдаче квест уже в журнале — там точный ID, без угадывания по названию
  if context == "complete" then
    local qid = GetQuestIDFromLogByTitle(title)
    if qid and CatQuest335Manifest[qid] then return qid end
  end
  return PickCandidate(CandidatesByTitle(title)) or apiID
end

------------------------------------------------------------------------
-- Выбор файла
------------------------------------------------------------------------
local function PickFile(qid, kind)
  local e = CatQuest335Manifest and CatQuest335Manifest[qid]
  if not (e and e.v) then return nil end
  local female = UnitSex("player") == 3
  if female and e.v[kind .. "_f"] then return kind .. "_f", e.v[kind .. "_f"] end
  if e.v[kind] then return kind, e.v[kind] end
  if e.v[kind .. "_f"] then return kind .. "_f", e.v[kind .. "_f"] end
  return nil
end

------------------------------------------------------------------------
-- Окно субтитров
------------------------------------------------------------------------
local frame
local function EnsureFrame()
  if frame then return frame end
  frame = CreateFrame("Frame", "CatQuest335Frame", UIParent)
  frame:SetWidth(360) frame:SetHeight(100)
  frame:SetPoint("TOP", UIParent, "TOP", 0, -120)
  frame:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
                      edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
                      tile = true, tileSize = 32, edgeSize = 16,
                      insets = { left = 8, right = 8, top = 8, bottom = 8 } })
  frame:SetMovable(true) frame:EnableMouse(true) frame:RegisterForDrag("LeftButton")
  frame:SetClampedToScreen(true)
  frame:SetScript("OnDragStart", function() frame:StartMoving() end)
  frame:SetScript("OnDragStop", function() frame:StopMovingOrSizing() end)
  -- Лицо собеседника: 3D-модель с камерой портрета (SetCamera(0)), как в рамках персонажей.
  local holder = CreateFrame("Frame", nil, frame)
  holder:SetWidth(72) holder:SetHeight(72)
  holder:SetPoint("LEFT", frame, "LEFT", 14, 0)
  holder:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
                       edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
                       tile = true, tileSize = 16, edgeSize = 12,
                       insets = { left = 3, right = 3, top = 3, bottom = 3 } })
  holder:SetBackdropColor(0, 0, 0, 0.9)
  frame.portrait = CreateFrame("PlayerModel", nil, holder)
  frame.portrait:SetPoint("TOPLEFT", holder, "TOPLEFT", 4, -4)
  frame.portrait:SetPoint("BOTTOMRIGHT", holder, "BOTTOMRIGHT", -4, 4)
  -- если собеседника уже нет рядом (реплика из очереди) — значок квеста вместо лица
  frame.icon = holder:CreateTexture(nil, "ARTWORK")
  frame.icon:SetTexture("Interface\\GossipFrame\\AvailableQuestIcon")
  frame.icon:SetWidth(40) frame.icon:SetHeight(40)
  frame.icon:SetPoint("CENTER", holder, "CENTER", 0, 0)
  frame.title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  frame.title:SetPoint("TOPLEFT", frame, "TOPLEFT", 96, -14)
  frame.title:SetWidth(250) frame.title:SetJustifyH("LEFT")
  frame.sub = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  frame.sub:SetPoint("TOPLEFT", frame.title, "BOTTOMLEFT", 0, -6)
  frame.sub:SetWidth(250) frame.sub:SetJustifyH("LEFT")
  local stop = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  stop:SetWidth(70) stop:SetHeight(20) stop:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -12, 12)
  stop:SetText("Стоп")
  stop:SetScript("OnClick", function() CQ_Stop() end)
  local rep = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  rep:SetWidth(70) rep:SetHeight(20) rep:SetPoint("RIGHT", stop, "LEFT", -4, 0)
  rep:SetText("Повтор")
  rep:SetScript("OnClick", function() CQ_Repeat() end)
  local nxt = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  nxt:SetWidth(70) nxt:SetHeight(20) nxt:SetPoint("RIGHT", rep, "LEFT", -4, 0)
  nxt:SetText("Далее")
  nxt:SetScript("OnClick", function() CQ_Next() end)
  nxt:Hide()
  frame.next = nxt
  frame:Hide()
  return frame
end

local function FormatTime(sec)
  sec = math.max(0, math.floor(sec + 0.5))
  return string.format("%d:%02d", math.floor(sec / 60), sec % 60)
end

------------------------------------------------------------------------
-- Проигрывание
------------------------------------------------------------------------
-- В 3.3.5 звук PlaySoundFile остановить нельзя ничем (нет StopSound, переключение
-- Sound_EnableAllSound его тоже не обрывает). Поэтому голос играет через музыкальный канал:
-- PlayMusic(mp3) + StopMusic() — это прерывается надёжно. На время реплики музыка зоны
-- замолкает, громкость/включение музыки подменяются и потом возвращаются как были.
-- PlayMusic зацикливает файл, поэтому в конце каждого mp3 есть ~0.6 с тишины, и мы
-- останавливаем его по длительности из манифеста, не давая начаться повтору.
--
-- Очередь: автоматические реплики (взятие/сдача) ждут, пока доиграет текущая.
-- Ручные («Читать», «Повтор», /cq test) играют сразу, прерывая текущую.
CQ.playing = false   -- сейчас звучит реплика
CQ.pending = nil     -- реплика, которая стартует на следующем кадре
CQ.queue = {}        -- ожидающие реплики
CQ.cutFrame = false  -- на этом кадре музыку только что оборвали — ждём кадр
CQ.restore = false   -- вернуть настройки музыки игрока на следующем кадре
local QUEUE_MAX = 10

local function SaveMusicCVars()
  if not CatQuest335DB.savedMusic then
    CatQuest335DB.savedMusic = { enable = GetCVar("Sound_EnableMusic"), vol = GetCVar("Sound_MusicVolume") }
  end
end

local function RestoreMusicCVars()
  local s = CatQuest335DB and CatQuest335DB.savedMusic
  if not s then return end
  SetCVar("Sound_MusicVolume", s.vol or "0.4")
  SetCVar("Sound_EnableMusic", s.enable or "1")
  CatQuest335DB.savedMusic = nil
end

-- Обрываем голос немедленно: StopMusic может плавно затухать, а выключение музыки режет сразу.
local function HardCut()
  StopMusic()
  SetCVar("Sound_EnableMusic", "0")
  CQ.cutFrame = true
end

local function SameItem(a, b)
  return a and b and a.qid == b.qid and a.kind == b.kind
end

local function UpdateSubtitle()
  if not (frame and frame:IsShown() and CQ.current) then return end
  local q = #CQ.queue
  frame.sub:SetText((CQ.current.npc or "") .. "  |cff999999"
    .. FormatTime(CQ.playElapsed or 0) .. " / " .. FormatTime(CQ.current.dur) .. "|r"
    .. (q > 0 and ("  |cffffd200в очереди: " .. q .. "|r") or ""))
  if q > 0 then frame.next:Show() else frame.next:Hide() end
end

local function StartItem(item)
  SaveMusicCVars()
  SetCVar("Sound_EnableMusic", "1")
  SetCVar("Sound_MusicVolume", tostring(CatQuest335DB.voiceVolume or 1))
  PlayMusic(VOICE_DIR .. item.qid .. "_" .. item.file .. ".mp3")
  CQ.playing = true
  CQ.current = item
  CQ.playElapsed = 0
  -- dur включает хвост тишины; останавливаем в нём, до начала повтора
  CQ.playTimer = math.max(0.5, item.dur - 0.2)
  local e = CatQuest335Manifest[item.qid]
  local f = EnsureFrame()
  f.title:SetText((e and e.title or ("Квест " .. item.qid)) .. ((item.kind == "comp") and " — сдача" or ""))
  local unit
  if item.npc then
    if UnitExists("npc") and UnitName("npc") == item.npc then unit = "npc"
    elseif UnitExists("target") and UnitName("target") == item.npc then unit = "target" end
  end
  if unit then
    f.icon:Hide()
    f.portrait:Show()
    f.portrait:SetUnit(unit)
    f.portrait:SetCamera(0)
    CQ.camFix = 10 -- модель грузится асинхронно: повторяем SetCamera(0) несколько кадров
  else
    f.portrait:Hide()
    f.icon:Show()
  end
  f:Show()
  UpdateSubtitle()
  if not item.fromHistory then
    table.insert(CQ.history, 1, item)
    if #CQ.history > 30 then table.remove(CQ.history) end
  end
  Debug("play " .. item.qid .. "_" .. item.file .. " (" .. item.dur .. "s), в очереди " .. #CQ.queue)
end

-- now=true: сыграть сразу (прервать текущую). now=false: в очередь, если что-то уже звучит.
local function Enqueue(item, now)
  local busy = CQ.playing or CQ.pending
  if not now and busy and CatQuest335DB.queue ~= false then
    if SameItem(item, CQ.current) and CQ.playing or SameItem(item, CQ.pending) then return end
    for _, it in ipairs(CQ.queue) do if SameItem(it, item) then return end end
    if #CQ.queue >= QUEUE_MAX then table.remove(CQ.queue, 1) end
    table.insert(CQ.queue, item)
    UpdateSubtitle()
    return
  end
  if CQ.playing then HardCut() end
  CQ.playing = false
  CQ.restore = false -- настройки вернём, когда закончится уже новая реплика
  CQ.pending = item
end

local function MakeItem(qid, kind, npcName)
  local file, dur = PickFile(qid, kind)
  if not file then return nil end
  return { qid = qid, kind = kind, file = file, dur = dur, npc = npcName }
end

-- now: true — ручной запуск (сразу), иначе автоматический (в очередь)
function CQ_Play(qid, kind, npcName, now)
  if not CatQuest335DB.enabled then return end
  local item = MakeItem(qid, kind, npcName)
  if not item then
    Debug("нет озвучки для " .. tostring(qid) .. " " .. kind)
    return
  end
  Enqueue(item, now)
end

-- Закончить текущую: следующая из очереди или возврат настроек музыки.
local function Finish()
  if CQ.playing then HardCut() end
  CQ.playing = false
  local nxt = table.remove(CQ.queue, 1)
  if nxt then
    CQ.pending = nxt
  else
    CQ.restore = true
    CQ.current = nil
    if frame then frame:Hide() end
  end
end

function CQ_Next()
  if CQ.playing then Finish() end
end

function CQ_Stop(silent)
  CQ.pending = nil
  CQ.queue = {}
  Finish()
  if not silent then Print("остановлено. /cq повтор — переслушать") end
end

function CQ_Repeat()
  local h = (CQ.playing and CQ.current) or CQ.history[1]
  if not h then Print("история пуста") return end
  if not CatQuest335DB.enabled then return end
  Enqueue({ qid = h.qid, kind = h.kind, file = h.file, dur = h.dur, npc = h.npc, fromHistory = true }, true)
end

-- Автозапуск: определяем квест сразу на событии, а если окно ещё не готово —
-- повторяем несколько кадров подряд (до ~0.5 с).
CQ.resolve = nil
CQ.reported = {}

local function TryResolve(r)
  local qid = GetCurrentQuestID(r.context)
  if not qid then return false end
  CQ.lastID = CQ.lastID or {}
  CQ.lastID[r.context] = qid
  local kind = (r.context == "detail") and "desc" or "comp"
  if PickFile(qid, kind) then
    CQ_Play(qid, kind, r.npc, false)
  elseif not CQ.reported[qid .. kind] and CatQuest335DB.notify ~= false then
    CQ.reported[qid .. kind] = true
    local e = CatQuest335Manifest[qid]
    Print("|cff999999нет озвучки: " .. tostring((e and e.title) or CQ.lastTitle or "?") .. " (" .. qid
      .. (kind == "comp" and ", сдача" or "") .. ")|r")
  end
  return true
end

local function StartResolve(context)
  local r = { context = context, npc = UnitName("npc"), tries = 0, t = 0 }
  if not TryResolve(r) then CQ.resolve = r end
end

local ticker = CreateFrame("Frame")
ticker:SetScript("OnUpdate", function(_, el)
  local r = CQ.resolve
  if r then
    r.t = r.t + el
    if r.t >= 0.05 then
      r.t = 0
      r.tries = r.tries + 1
      if TryResolve(r) then
        CQ.resolve = nil
      elseif r.tries >= 10 then
        CQ.resolve = nil
        Debug("не смог определить QuestID (" .. r.context .. "): [" .. tostring(CQ.lastTitle) .. "]")
      end
    end
  end
  if CQ.cutFrame then
    CQ.cutFrame = false
    return -- даём клиенту кадр, чтобы обрыв музыки применился
  end
  if CQ.pending then
    local item = CQ.pending
    CQ.pending = nil
    StartItem(item)
    return
  end
  if CQ.restore then
    CQ.restore = false
    RestoreMusicCVars()
  end
  if CQ.camFix and CQ.camFix > 0 and frame then
    CQ.camFix = CQ.camFix - 1
    frame.portrait:SetCamera(0)
  end
  if not CQ.playing then return end
  CQ.playElapsed = CQ.playElapsed + el
  UpdateSubtitle()
  if CQ.playElapsed >= CQ.playTimer then
    Finish()
  end
end)

------------------------------------------------------------------------
-- События
------------------------------------------------------------------------
local ev = CreateFrame("Frame")
ev:RegisterEvent("ADDON_LOADED")
ev:RegisterEvent("PLAYER_LOGIN")
ev:RegisterEvent("PLAYER_LOGOUT")
ev:RegisterEvent("QUEST_DETAIL")    -- взятие: описание
ev:RegisterEvent("QUEST_COMPLETE")  -- окно награды: реплика сдачи

local function CountManifest()
  local q, f = 0, 0
  for _, e in pairs(CatQuest335Manifest or {}) do
    q = q + 1
    for _ in pairs(e.v or {}) do f = f + 1 end
  end
  return q, f
end

local AddButtons -- объявлена ниже

ev:SetScript("OnEvent", function(_, event, ...)
  if event == "ADDON_LOADED" then
    if ... == "CatQuest335" then
      CatQuest335DB = CatQuest335DB or {}
      if CatQuest335DB.enabled == nil then CatQuest335DB.enabled = true end
    end
    return
  elseif event == "PLAYER_LOGOUT" then
    -- выход/перезагрузка посреди реплики: вернуть игроку его настройки музыки
    if CQ.playing then StopMusic() end
    RestoreMusicCVars()
    return
  elseif event == "PLAYER_LOGIN" then
    RestoreMusicCVars() -- если прошлый сеанс завершился вылетом посреди реплики
    pcall(AddButtons)
    local q, f = CountManifest()
    Print("загружен. Квестов с голосом: " .. q .. " (файлов " .. f .. "). /cq help")
    return
  end
  if not CatQuest335DB.enabled or CatQuest335DB.auto == false then return end
  StartResolve((event == "QUEST_DETAIL") and "detail" or "complete")
end)

-- Кнопка «Читать» между «Принять»/«Отказаться» и между «Завершить»/«Отмена»
local function MakeReadButton(name, parent, anchor, context, kind)
  if not (parent and anchor) then return end
  local b = CreateFrame("Button", name, parent, "UIPanelButtonTemplate")
  b:SetWidth(76) b:SetHeight(22)
  b:SetPoint("LEFT", anchor, "RIGHT", 8, 0)
  b:SetText("Читать")
  b:SetScript("OnClick", function()
    local qid = (CQ.lastID and CQ.lastID[context]) or GetCurrentQuestID(context)
    if not qid then Print("не смог определить квест — /cq debug") return end
    if not PickFile(qid, kind) then Print("для этого квеста нет озвучки") return end
    local saved = CatQuest335DB.enabled
    CatQuest335DB.enabled = true
    CQ_Play(qid, kind, UnitName("npc"), true)
    CatQuest335DB.enabled = saved
  end)
end

AddButtons = function()
  MakeReadButton("CatQuest335ReadDetail", QuestFrameDetailPanel, QuestFrameAcceptButton, "detail", "desc")
  MakeReadButton("CatQuest335ReadReward", QuestFrameRewardPanel, QuestFrameCompleteQuestButton, "complete", "comp")
end

------------------------------------------------------------------------
-- Слэш-команды
------------------------------------------------------------------------
SLASH_CQ1 = "/cq"
SlashCmdList["CQ"] = function(msg)
  msg = NormWS(msg or "") or ""
  local cmd, arg = msg:match("^(%S*)%s*(.*)$")
  cmd = string.lower(cmd or "")
  if cmd == "стоп" or cmd == "stop" then CQ_Stop()
  elseif cmd == "повтор" or cmd == "repeat" then CQ_Repeat()
  elseif cmd == "q" then
    Print("история (последние):")
    for i = 1, math.min(5, #CQ.history) do
      local h = CQ.history[i]
      DEFAULT_CHAT_FRAME:AddMessage(" " .. i .. ". " .. h.qid .. "_" .. h.file)
    end
  elseif cmd == "test" then
    local qid = tonumber(arg)
    if not qid then
      for id in pairs(CatQuest335Manifest or {}) do qid = id break end
    end
    local kind = qid and ((PickFile(qid, "desc") and "desc") or (PickFile(qid, "comp") and "comp"))
    if not kind then Print("нет озвучки для " .. tostring(qid)) return end
    Print("тест: квест " .. qid .. " (" .. kind .. ")")
    CQ_Play(qid, kind, nil, true)
  elseif cmd == "selftest" then
    local q, f = CountManifest()
    local _, race = UnitRace("player")
    local _, class = UnitClass("player")
    Print("манифест: квестов " .. q .. ", файлов " .. f .. "; включено=" .. tostring(CatQuest335DB.enabled)
      .. " автозапуск=" .. tostring(CatQuest335DB.auto ~= false) .. " очередь=" .. tostring(CatQuest335DB.queue ~= false)
      .. " GetQuestID=" .. tostring(GetQuestID ~= nil))
    Print("звук: AllSound=" .. tostring(GetCVar("Sound_EnableAllSound")) .. " Master=" .. tostring(GetCVar("Sound_MasterVolume"))
      .. " музыка=" .. tostring(GetCVar("Sound_EnableMusic")) .. "/" .. tostring(GetCVar("Sound_MusicVolume"))
      .. " громкость голоса=" .. tostring(CatQuest335DB.voiceVolume or 1))
    Print("персонаж: " .. tostring(race) .. "/" .. tostring(class) .. " пол=" .. tostring(UnitSex("player")))
    Print("проверка звука: /cq test (если тишина — полный перезапуск игры, не /reload)")
  elseif cmd == "debug" then
    CatQuest335DB.debug = not CatQuest335DB.debug
    Print("отладка " .. (CatQuest335DB.debug and "вкл" or "выкл"))
    local title = GetTitleText and GetTitleText()
    if title and title ~= "" then
      BuildNormMap()
      local ids = CandidatesByTitle(title)
      Print("NPC entry: " .. tostring(NpcEntry()) .. " GUID: " .. tostring(UnitGUID("npc")))
      Print("окно квеста: [" .. title .. "] кандидаты: " .. (ids and table.concat(ids, ",") or "нет")
        .. " выбран: " .. tostring(PickCandidate(ids)) .. " в журнале: " .. tostring(GetQuestIDFromLogByTitle(title)))
    end
  elseif cmd == "vol" or cmd == "громкость" then
    local v = tonumber(((arg or ""):gsub(",", ".")))
    if v and v > 1 then v = v / 100 end
    if not v or v < 0 then Print("громкость голоса: " .. (CatQuest335DB.voiceVolume or 1) .. "  (/cq vol 0.8 или /cq vol 80)") return end
    CatQuest335DB.voiceVolume = math.min(1, v)
    if CQ.playing then SetCVar("Sound_MusicVolume", tostring(CatQuest335DB.voiceVolume)) end
    Print("громкость голоса: " .. CatQuest335DB.voiceVolume)
  elseif cmd == "далее" or cmd == "next" or cmd == "skip" then CQ_Next()
  elseif cmd == "auto" or cmd == "queue" or cmd == "notify" then
    -- переключатели: auto — автозапуск при взятии/сдаче, queue — очередь вместо прерывания,
    -- notify — сообщать в чат о квестах без озвучки
    local names = { auto = "автозапуск", queue = "очередь", notify = "сообщения о квестах без озвучки" }
    local a = string.lower(arg or "")
    if a == "on" or a == "вкл" then CatQuest335DB[cmd] = true
    elseif a == "off" or a == "выкл" then CatQuest335DB[cmd] = false
    else CatQuest335DB[cmd] = (CatQuest335DB[cmd] == false) end
    Print(names[cmd] .. ": " .. ((CatQuest335DB[cmd] ~= false) and "вкл" or "выкл"))
  elseif cmd == "on" then CatQuest335DB.enabled = true Print("вкл")
  elseif cmd == "off" then CatQuest335DB.enabled = false CQ_Stop(true) Print("выкл")
  else
    Print("/cq повтор | далее | стоп | vol 0-100 | auto | queue | notify | q (история) | test [questID] | selftest | debug | on | off")
  end
end
