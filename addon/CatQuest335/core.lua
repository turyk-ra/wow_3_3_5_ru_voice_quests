-- CatQuest335 core.lua (WoW 3.3.5a, interface 30300)
-- QuestID-based voiceover: voices live in CatQuest335_Voices/<questID>_desc.mp3 / <questID>_comp.mp3
-- No TalkingHead in 3.3.5, so we emulate: small frame with portrait + subtitles + queue.

CatQuest335 = CatQuest335 or {}
CatQuest335DB = CatQuest335DB or { enabled = true, volume = true }
local CQ = CatQuest335
CQ.queue = {}
CQ.playing = false
CQ.history = {}

-- manifest.lua defines: CatQuest335Manifest = { [questID] = { title="...", has_desc=true, has_comp=true }, ... }
-- voice path: Interface\AddOns\CatQuest335_Voices\<questID>_desc.mp3

local VOICE_DIR = "Interface\\AddOns\\CatQuest335_Voices\\"

local function Print(msg) DEFAULT_CHAT_FRAME:AddMessage("|cff88ff88[CatQuest335]|r " .. tostring(msg)) end

local function GetQuestIDFromLogByTitle(title)
  if not title then return nil end
  local n = GetNumQuestLogEntries()
  for i = 1, n do
    local t, _, _, _, _, _, _, qid = GetQuestLogTitle(i)
    if t == title then return qid end
  end
  return nil
end

-- 3.3.5 has no reliable GetQuestID() on QUEST_DETAIL in all builds, try several ways
local function GetCurrentQuestID(context)
  -- 1) modern backports expose GetQuestID
  if GetQuestID then
    local ok, qid = pcall(GetQuestID)
    if ok and qid and qid ~= 0 then return qid end
  end
  -- 2) quest log selection
  if GetQuestLogSelection then
    local idx = GetQuestLogSelection()
    if idx and idx > 0 then
      local _, _, _, _, _, _, _, qid = GetQuestLogTitle(idx)
      if qid and qid ~= 0 then return qid end
    end
  end
  -- 3) by title text
  if GetTitleText then
    local title = GetTitleText()
    local qid = GetQuestIDFromLogByTitle(title)
    if qid then return qid end
  end
  return nil
end

local function VoicePath(qid, kind)
  -- kind: "desc" | "comp"
  return VOICE_DIR .. tostring(qid) .. "_" .. kind .. ".mp3"
end

local function HasVoice(qid, kind)
  if not (CatQuest335Manifest and qid) then return false end
  local e = CatQuest335Manifest[qid]
  if not e then return false end
  if kind == "desc" then return e.has_desc end
  if kind == "comp" then return e.has_comp end
  return false
end

-- Simple frame: portrait + title + subtitle line + Stop/Repeat
local frame
local function EnsureFrame()
  if frame then return frame end
  frame = CreateFrame("Frame", "CatQuest335Frame", UIParent)
  frame:SetWidth(360) frame:SetHeight(110)
  frame:SetPoint("TOP", UIParent, "TOP", 0, -120)
  frame:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background", edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 16, insets = { left = 8, right = 8, top = 8, bottom = 8 } })
  frame:SetMovable(true) frame:EnableMouse(true) frame:RegisterForDrag("LeftButton") frame:SetScript("OnDragStart", function() frame:StartMoving() end) frame:SetScript("OnDragStop", function() frame:StopMovingOrSizing() end)
  frame.portrait = CreateFrame("PlayerModel", nil, frame)
  frame.portrait:SetWidth(80) frame.portrait:SetHeight(80)
  frame.portrait:SetPoint("LEFT", frame, "LEFT", 12, 0)
  frame.title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  frame.title:SetPoint("TOPLEFT", frame, "TOPLEFT", 100, -12)
  frame.title:SetWidth(245) frame.title:SetJustifyH("LEFT")
  frame.sub = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  frame.sub:SetPoint("TOPLEFT", frame.title, "BOTTOMLEFT", 0, -6)
  frame.sub:SetWidth(245) frame.sub:SetHeight(50) frame.sub:SetJustifyH("LEFT") frame.sub:SetJustifyV("TOP")
  local stop = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  stop:SetWidth(80) stop:SetHeight(20) stop:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -10, 10)
  stop:SetText("Стоп")
  stop:SetScript("OnClick", function() CQ_Stop() end)
  frame:Hide()
  return frame
end

function CQ_Play(qid, kind, npcName)
  if not CatQuest335DB.enabled then return end
  if not HasVoice(qid, kind) then
    DEFAULT_CHAT_FRAME:AddMessage("|cff88ff88[CatQuest335]|r нет файла: " .. tostring(qid) .. "_" .. kind .. " (пропуск)")
    return
  end
  table.insert(CQ.queue, { qid = qid, kind = kind, npc = npcName })
  CQ_Pump()
end

function CQ_Pump()
  if CQ.playing then return end
  local item = table.remove(CQ.queue, 1)
  if not item then if frame then frame:Hide() end return end
  CQ.playing = true
  local path = VoicePath(item.qid, item.kind)
  -- PlaySoundFile returns 1/nil in 3.3.5; use willPlay check
  local ok = PlaySoundFile(path, "Master")
  local e = CatQuest335Manifest[item.qid]
  local f = EnsureFrame()
  f.title:SetText((e and e.title or ("Квест " .. item.qid)) .. (item.kind == "comp" and " — сдача" or ""))
  f.sub:SetText("Озвучка: " .. item.qid .. "_" .. item.kind .. (item.npc and (" · " .. item.npc) or ""))
  -- target portrait if NPC shown
  if UnitExists("npc") then f.portrait:SetUnit("npc") else f.portrait:SetUnit("player") end
  f:Show()
  table.insert(CQ.history, 1, item)
  if #CQ.history > 30 then table.remove(CQ.history) end
  -- poor-man's end detection: poll file length? we approximate 1s per 15 chars of subtitle if known
  local approx = 8
  if e and e.dur and e.dur[item.kind] then approx = e.dur[item.kind] end
  CQ.playTimer = approx
  CQ.playElapsed = 0
  CQ.currentPath = path
  if not ok then Print("не смог проиграть " .. path .. " — проверь mp3 и рестарт клиента (не /reload)") end
end

-- ticker via OnUpdate on hidden frame
local ticker = CreateFrame("Frame")
ticker:SetScript("OnUpdate", function(_, el)
  if not CQ.playing then return end
  CQ.playElapsed = (CQ.playElapsed or 0) + el
  if (CQ.playElapsed or 0) >= (CQ.playTimer or 8) then
    if StopSound then pcall(StopSound) end
    CQ.playing = false
    CQ_Pump()
  end
end)

function CQ_Stop()
  CQ.queue = {}
  CQ.playing = false
  if frame then frame:Hide() end
  -- 3.3.5 has no StopSoundFile; StopMusic/Sound best effort
  if StopMusic then pcall(StopMusic) end
  Print("остановлено. /cq повтор — переслушать, /cq q — история")
end

function CQ_Repeat()
  local h = CQ.history[1]
  if not h then Print("история пуста") return end
  CQ_Play(h.qid, h.kind, h.npc)
end

-- Events
local ev = CreateFrame("Frame")
ev:RegisterEvent("ADDON_LOADED")
ev:RegisterEvent("QUEST_DETAIL")    -- взятка: описание
ev:RegisterEvent("QUEST_PROGRESS")  -- диалог сдачи
ev:RegisterEvent("QUEST_COMPLETE")  -- награда
ev:RegisterEvent("GOSSIP_SHOW")

ev:SetScript("OnEvent", function(_, event, ...)
  if event == "ADDON_LOADED" then
    local name = ...
    if name == "CatQuest335" then
      local count = 0
      if CatQuest335Manifest then for _ in pairs(CatQuest335Manifest) do count = count + 1 end end
      Print("загружен. Квестов с голосом: " .. count .. ". /cq help")
    end
    return
  end
  if not CatQuest335DB.enabled then return end
  if event == "QUEST_DETAIL" then
    local qid = GetCurrentQuestID("detail")
    if qid then CQ_Play(qid, "desc", UnitName("npc")) end
  elseif event == "QUEST_PROGRESS" then
    -- промежуточный текст, читаем desc повторно только если нет comp? пропускаем чтобы не спамить
  elseif event == "QUEST_COMPLETE" then
    local qid = GetCurrentQuestID("complete")
    if qid then CQ_Play(qid, "comp", UnitName("npc")) end
  elseif event == "GOSSIP_SHOW" then
    -- gossip-озвучка опционально: пропускаем в прототипе
  end
end)

-- Add Play buttons to Blizzard quest frame (minimal)
local function AddButtons()
  if not QuestFrameDetailPanel then return end
  local b = CreateFrame("Button", "CatQuest335PlayBtn", QuestFrameDetailPanel, "UIPanelButtonTemplate")
  b:SetWidth(90) b:SetHeight(20) b:SetPoint("BOTTOMRIGHT", QuestFrameDetailPanel, "BOTTOMRIGHT", -10, 8)
  b:SetText("Читать")
  b:SetScript("OnClick", function()
    local qid = GetCurrentQuestID("button")
    if qid then CQ_Play(qid, "desc", UnitName("npc")) else Print("не смог определить QuestID") end
  end)
end

local loader = CreateFrame("Frame")
loader:RegisterEvent("PLAYER_LOGIN")
loader:SetScript("OnEvent", function() pcall(AddButtons) end)

SLASH_CQ1 = "/cq"
SlashCmdList["CQ"] = function(msg)
  msg = string.lower(msg or "")
  if msg == "стоп" or msg == "stop" then CQ_Stop()
  elseif msg == "повтор" or msg == "repeat" then CQ_Repeat()
  elseif msg == "q" then
    Print("история (последние):")
    for i = 1, math.min(5, #CQ.history) do
      local h = CQ.history[i]
      DEFAULT_CHAT_FRAME:AddMessage(" " .. i .. ". " .. h.qid .. "_" .. h.kind)
    end
  elseif msg == "selftest" then
    local n, okc = 0, 0
    if CatQuest335Manifest then for qid, e in pairs(CatQuest335Manifest) do n = n + 1 if e.has_desc or e.has_comp then okc = okc + 1 end if n >= 5 then break end end end
    Print("selftest: manifest=" .. tostring(CatQuest335Manifest ~= nil) .. " enabled=" .. tostring(CatQuest335DB.enabled))
  elseif msg == "help" then
    Print("/cq повтор | /cq стоп | /cq q | /cq selftest")
  elseif msg == "on" then CatQuest335DB.enabled = true Print("вкл")
  elseif msg == "off" then CatQuest335DB.enabled = false CQ_Stop() Print("выкл")
  else Print("/cq help")
  end
end
