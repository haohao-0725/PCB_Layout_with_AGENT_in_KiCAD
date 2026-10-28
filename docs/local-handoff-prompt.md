# 交接 Prompt：提升 `kicad-clean-pcb` 的實用度與能力

> **給人看的使用方式**
> 1. 先填好下面「0. 待填決策」。沒填的項目，agent 會在開始前先問你。
> 2. 在本地 repo 打開 Claude Code，輸入：「請讀 `docs/local-handoff-prompt.md` 並照著做」。
>    或者把「──── 以下貼給 Claude Code ────」之後的內容整段貼上。
> 3. 這份規劃整理於 2026-10-28。技術事實請 agent 在本地再驗證一次。

──── 以下貼給 Claude Code ────

你要協助我改進這個 repo 裡的 Agent Skill `kicad-clean-pcb`（KiCad PCB 工作流程 skill）。請用**繁體中文**跟我溝通，
程式碼、註解、commit 訊息用英文。每個 Phase 結束時先回報結果，**等我確認後才進下一個 Phase**。

## 0. 待填決策（空白的項目請先用 AskUserQuestion 問我）

| 項目 | 我的決定 | 參考選項 |
|---|---|---|
| MCU 開發板 | | Raspberry Pi Pico / ESP32-DevKitC / Nucleo-32 / Blue Pill（以手邊有的為優先） |
| 步進驅動模組 | | A4988 / DRV8825 / TMC2209（StepStick 尺寸） |
| 層數 | | 建議 2 層（便宜、好焊） |
| 5 V 來源 | | MP1584 / LM2596 降壓模組 |
| 板廠 | | JLCPCB / PCBWay / 台灣在地 |
| 預設選項（Part A） | | 建議：T 整齊風格、A1=a、A11=a（THT 手焊）、A16=b（線上板廠）、A17=繁體中文 |

## 1. 背景：repo 現況

- Repo：`haohao-0725/PCB_Layout_with_AGENT_in_KiCAD`，v0.1.0，MIT。
- 結構：
  - `skills/kicad-clean-pcb/SKILL.md`：7 個階段、4 個確認點（CP0／CP1-2／CP4／CP6）。
  - `references/`：preferences、layout-rules、circuit-policy、routing-playbook、checks-and-delivery、kicad-scripting、ordering-taiwan。
  - `assets/`：`PCB_DECISIONS.template.md`、`PROJECT_BRIEF.template.md`。
  - `scripts/`：
    - `export_previews.py`、`trace_drop.py`：用舊的 SWIG `pcbnew`。
    - `gerber_readback.py`、`compare_gerbers.py`、`gerberlib.py`：只用標準函式庫。
  - `.claude-plugin/`：`plugin.json`、`marketplace.json`。
  - `tests/test_scripts.py`：15 個測試全過，執行方式 `python -m unittest discover -s tests -v`。
- 只在 Windows 10 + KiCad 10.0.x 測試過。

## 2. 評估結論：為什麼要改、改的方向

- **核心問題：** 擺放和走線沒有現成工具。`references/kicad-scripting.md` 只有一個 `Router` 草圖，
  agent 每次都要自己寫 place/route 腳本，所以結果很依賴當下模型的表現。
- **原則：AI 負責決定，程式負責幾何。** LLM 不擅長座標計算、間距、記住大量 pad 位置、安排線的順序避免交叉，這些交給確定性的工具。
- **定位：** 「整齊、好讀、有人把關」。不要做成通用 KiCad MCP，也不要自己寫自動繞線器。這兩塊已經有
  kicad-mcp（529★）、kicad-mcp-pro（153★）、kicad-happy（1.5k★）等，正面競爭很難贏。工具集保持小而專（約 10～15 個）。
- **差異點：** 把「整齊度」量化。同類 repo 大多做電氣或製程（DFM）檢查，量化「好不好讀」的很少。
- **流程不改。** 7 個階段和 4 個確認點都保留，只加預設值和工具。

## 3. 已查到的技術事實（截至 2026-10-28，動手前請在本地驗證）

- KiCad 10.0.0 於 2026 年 3 月發佈，7 月已更新到 10.0.5。KiCad 11 推估在 2027 年左右。
- **SWIG `pcbnew`：** 從 KiCad 9 開始棄用，官方計畫在 KiCad 11 移除。開發版（10.99）已經移除，也不再附帶 Python。
  → **新程式碼不准用 SWIG。**
- **IPC API**（PyPI 套件 `kicad-python` 0.4.0，模組名 `kipy`，需要 Python ≥ 3.9，依賴 protobuf、pynng）：
  - 必須開著 KiCad 圖形介面，並在偏好設定中啟用 API server（確切位置請在本地確認）。不開介面的模式預計 KiCad 11 才有。
  - `Board` 有的方法：`create_items`、`update_items`、`remove_items`、`get_tracks/vias/pads/footprints/zones/nets/shapes`、
    `get_netclass_for_nets`、`begin_commit`／`push_commit`／`drop_commit`（每次修改可以 Ctrl+Z 復原）、`refill_zones`、
    `get_pad_shapes_as_polygons`、`hit_test`、`get_stackup`、`interactive_move`、`save`／`save_as`、`get_selection`。
  - KiCad 10 做不到：
    - 原理圖指令：只有型別定義，沒有指令。
    - 輸出檔案：要改用 `kicad-cli`。
    - 從零件庫載入 footprint：沒找到對應指令。footprint 要靠「從原理圖更新 PCB」（F8）或檔案後端放進板子。
- **Claude Code plugin 可以附帶 MCP server：** 在 plugin 根目錄放 `.mcp.json`，或在 `plugin.json` 裡寫 `mcpServers`。路徑可以用 `${CLAUDE_PLUGIN_ROOT}`。
- **Freerouting** 有指令列模式（`-de in.dsn -do out.ses`），但不開介面執行過去有問題。只能當選配。

## 4. 目標架構

```
skills/kicad-clean-pcb/
  kcp/                      # 新的 Python 套件（放在 skill 資料夾內，直接複製資料夾安裝也能用）
    sexpr.py                # .kicad_pcb / .kicad_sch s-expression 讀寫
    model.py                # 板子模型：footprint、pad、net、track、via、zone、板框（純 Python）
    backends/file.py        # 檔案後端：直接讀寫 .kicad_pcb；有 ~*.lck（KiCad 開著）就拒絕寫入
    backends/ipc.py         # 即時後端（Phase 4，用 kipy）
    kicad_cli.py            # 包裝 kicad-cli：drc / erc / gerbers / drill / pdf（DRC 用 JSON 報告）
    inspect.py  lint.py  decisions.py  place.py  route.py  wiring.py  previews.py  trace.py
    cli.py                  # `python -m kcp <子指令>`，輸出 JSON（加 --markdown 輸出表格）
    mcp_server.py           # Phase 4：薄薄一層包裝
pyproject.toml              # repo 根目錄；之後發佈 PyPI / uvx 用
```

- **核心只用標準函式庫**（跟現有的 Gerber 工具一樣），任何 Python 3.9+ 都能跑。`kipy`、`mcp` 是選用相依套件。
- 每個工具：輸出 JSON；失敗時回傳非 0；不需要 KiCad 就能跑的單元測試要用手寫的小型 fixture 檔。
  需要 `kicad-cli` 的整合測試，在沒裝 KiCad 時自動跳過。
- 套件放的位置是我的建議。如果你認為放 repo 根目錄的 `src/` 比較好，先說明取捨再決定。

## 5. 工作計畫

### Phase 0：環境確認（不改程式碼）
1. 讀 `README.md`、`SKILL.md`、`references/`、`assets/`、`scripts/`、`tests/`。
2. 確認 `kicad-cli version` 是 10.0.x，找到 KiCad 附帶的 Python
   （Windows：`C:/Program Files/KiCad/10.0/bin/python.exe`，並設定 `PYTHONUTF8=1`）。確認 `kicad-python` 能不能安裝。
3. 跑現有測試。
4. 從目前分支開一個工作分支（例如 `dev/tools-v0.2`）。
5. 回報環境狀況，並確認第 0 節的決策。

### Phase 1：「眼睛」工具，加上預設值
- **`inspect`：** 把板子讀成 JSON。內容包括：
  - 板框尺寸、各層與疊層；
  - footprint：ref、value、lib id、x/y/rot、正反面、courtyard 外框，以及每個 pad 的編號、net、座標、形狀、尺寸、鑽孔；
  - net：名稱、netclass、pad 數、是否已走線；
  - 走線、via、鋪銅的統計；
  - 未連線數（取自 `kicad-cli pcb drc` 的 JSON 報告）。
- **`lint` 整齊度評分**：輸出 JSON 和 Markdown 表格，依 T／C／R 門檻判定 pass／warn／fail（門檻寫在 preset 檔，不要寫死）：
  - 總線段數、每個 net 的線段數、每 mm 走線長的線段數；
  - 非 0°／45°／90° 的線段；
  - 鋸齒：每 10 mm 的轉向次數，以及短於 2 倍線寬的小折線；
  - via：總數、每個 net 的數量；電源和大電流 netclass 的 via（T 的目標是 0）；signal 每條 ≤ 1；
  - 各層主方向符合率：輸入 layer plan JSON，計算沿主方向的長度百分比；
  - GND 平面層上的走線（4L-S1 的目標是 0）；
  - 鋪銅數量與 net（T：只能有 GND）；
  - 懸空的線頭（端點沒接到 pad 或 via）；
  - 絲印壓到 pad（可用外框近似）；
  - 同功能電阻排的對齊偏差（同前綴、同角度的零件群組）。
- **`decisions`：** 解析 `PCB_DECISIONS.md` 的表格，列出各 Part 的空白欄位。`--checkpoint CP2` 時若有必填欄位空白就回傳 1。
- **預設值：** 在 `examples/` 放一份 Part A 預設檔範例，並在 README 說明如何從 CLAUDE.md／AGENTS.md 指向它
  （依 `preferences.md` §4，不要把使用者的預設值寫進 skill 資料夾）。
- 在 `SKILL.md` 補上「哪個階段呼叫哪個工具」。

### Phase 2：範例專案（照 skill 自己的流程做，由我審查）
- 位置：`examples/stepper-carrier-2axis/`（板子規格依第 0 節）。內容：
  - MCU 開發板（插在排母上）、2 個 StepStick；
  - 12–24 V 端子 → 保險絲 → 反接保護 → 每顆驅動器各自的大電容；
  - 5 V 降壓模組；
  - 2 路限位開關輸入（RC 濾波加上拉電阻）；
  - 全 THT、手焊，約 80×60 mm。
- **完全照 `SKILL.md` 的 Stage 0～6 執行。** 在 CP0、CP1-2、CP4、CP6 一定要停下來等我審查，我就是使用者。
- 用 `kicad-scripting.md` 描述的生成腳本結構（`build_*`／`place_*`／`route_*`／`validate_*`／`rebuild_*`）。
  **改用檔案後端，不用 SWIG。** 這些腳本是 Phase 3 工具的原型。
- footprint 優先用 KiCad 官方庫（例如 StepStick 可用 `Module:Pololu_Breakout-16_15.2x20.3mm`，請先確認本地 KiCad 10 有這個）。
  需要實測的尺寸記在 `PCB_DECISIONS.md`。
- **產出：**
  - 填好的 `PCB_DECISIONS.md` 和 `PROJECT_BRIEF.md`；
  - 原理圖、板子檔；
  - 預覽 PNG、1:1 試合 PDF；
  - ERC／DRC／parity 全部歸零的報告；
  - Gerber＋鑽孔 zip、回讀 Markdown；
  - lint 報告；
  - 範例專屬的 README。
- **選做（成本低才做）：** 同一個擺放用自動繞線或粗略走線做一版「之前」，產生對比圖和 lint 數字給主 README 用。
- 不准下單、付款或上傳到板廠。

### Phase 3：抽出擺放／走線工具，移植 SWIG 腳本
- **`place`：**
  - 排成一列：refs、起點、間距、角度；
  - 重複單元陣列：模板、數量、偏移；
  - 靠板邊：連接器朝外；
  - 試合檢查：courtyard 重疊、離板邊距離、模組下方禁區。
- **`route`：**
  - `path`：net、layer、width、起點 pad → 轉折點 → 終點 pad，只允許 0／45／90°。
    寫入前檢查與其他 net 銅的間距（線段對線段、線段對 pad），有衝突就回報衝突清單、不寫入。
  - `bus`／`lane`：把 `routing-playbook.md` §3 的 lane 排序規則寫成程式。
  - `cleanup`：合併共線線段、刪除零長度線段、標出鋸齒。
- 把 `export_previews.py`、`trace_drop.py` 改成檔案後端加 `kicad-cli`，指令參數維持相容。
- 範例專案的腳本改用套件重寫，並用 `compare_gerbers.py` 證明輸出幾何不變。
- 更新 `SKILL.md`／`references/`：工具已經強制的規則，就把文字改成「呼叫哪個工具」。

### Phase 4：MCP server 與 IPC 即時後端
- 用 `mcp` Python SDK（FastMCP），stdio 模式。工具和 CLI 子指令一對一，輸入輸出都是 JSON。
- IPC 後端：每個 agent 操作包成一筆 commit，附上訊息（例如 `kcp: route group power`），讓我能在 KiCad 裡用 Ctrl+Z 撤銷。
- plugin 根目錄加 `.mcp.json`。README 補上 Codex 和其他工具的設定方式，以及如何在 KiCad 10 啟用 IPC API。
- 準備好 PyPI 發佈設定，但發佈由我自己來（帳號憑證不經過你）。

### Phase 5：實際組裝（由我主導）
- 你準備下單規格。我下單、組裝、量測。
- 你把學到的教訓寫回 `references/` 和範例 README，照片放進主 README。

### 並行：曝光
- 我在 GitHub 上做：設定 topics（kicad、kicad-pcb、pcb-design、pcb-layout、claude-code、claude-skills、agent-skills、codex、gerber、hardware-design、electronics），
  發 release，設定 social preview 圖。
- 你負責：README 開頭寫一句話說明賣點，放對比圖和範例連結；更新 CHANGELOG 和 plugin 版本號。

## 6. 規則

- 不改 7 階段流程；新程式碼不准用 SWIG；現有 15 個測試要持續通過。
- skill 規則保持通用，不寫入專案專屬數字（依 README 的貢獻規則）。
- 每個階段或 Phase 至少 commit 一次。不准直接 push 到 `main`；沒有我同意不准開 PR。
- 回報時先講結果，再講需要我決定的事。數字要帶單位，每個結論標明是「CAD 已檢查」、「估算」還是「需要實板驗證」。
- 同一個問題試了三次還卡住就停下來，回報卡住的地方和需要我做的決定，不要一直換方法硬修。
- Windows 注意事項：設定 `PYTHONUTF8=1`、處理含空白的路徑；檔案後端寫入前，KiCad 必須關掉這個專案。

## 7. 現在請開始

執行 Phase 0。完成後用繁體中文回報環境狀況、確認第 0 節的決策，然後等我確認再進 Phase 1。
