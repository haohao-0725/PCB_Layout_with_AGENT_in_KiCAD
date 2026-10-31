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
| MCU 開發板 | **NUCLEO-F446ZE**（Nucleo-144，70 × 133.34 mm，手邊有） | Raspberry Pi Pico / ESP32-DevKitC / Nucleo-32 / Blue Pill（以手邊有的為優先） |
| 步進驅動模組 | **TMC2209**（手邊的 MKS TMC2209 V2.0_001，18 腳：2×8 加 VREF／DIAG） | A4988 / DRV8825 / TMC2209（StepStick 尺寸） |
| 層數 | **4 層**（4L-S1） | 建議 2 層（便宜、好焊） |
| 5 V 來源 | **LM2596** 降壓模組 | MP1584 / LM2596 降壓模組 |
| 板廠 | **JLCPCB** | JLCPCB / PCBWay / 台灣在地 |
| 預設選項（Part A） | **照建議**：T 整齊風格、A1=a、A11=a（THT 手焊）、A16=b（JLCPCB）、A17=繁體中文 | 建議：T 整齊風格、A1=a、A11=a（THT 手焊）、A16=b（線上板廠）、A17=繁體中文 |
| 板子尺寸（2026-10-29 新增） | **A13=a**：保留走線通道的最小尺寸，擺完再定（估算約 115 × 145 mm；Nucleo-144 放不進原訂的 80 × 60 mm） | — |
| 實測資料來源（2026-10-29 新增） | **可以沿用**本機 `prpr_carrier` 專案的實測幾何（Nucleo 排母位置、MKS TMC2209 18P、端子台）。只抄尺寸數字重新產生 footprint，不複製原專案檔案、研究專屬接線或照片 | — |

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
  - 全 THT、手焊，約 80×60 mm（已依第 0 節改為 Nucleo-144 與 4 層，尺寸擺完再定）。
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

## 8. 進度紀錄

### Phase 0 結果（2026-10-29，本機 Windows 10）

- **分支：** `dev/tools-v0.2`，從 `claude/quirky-ride-lo2p11` 開出，不追蹤遠端。
- **KiCad：** 10.0.3（`C:/Program Files/KiCad/10.0`），編譯時 `KICAD_IPC_API=ON`。
  附帶 Python 3.11.5，SWIG `pcbnew` 仍可載入（舊腳本能跑）。
- **kicad-cli：** `pcb drc` 和 `sch erc` 都支援 `--format json`；`pcb drc` 有 `--schematic-parity`、`--refill-zones`。
- **系統 Python：** 3.10.8。`pdftoppm`（Poppler 25.07）在 PATH 上，PNG 預覽可用。
- **kicad-python：** PyPI 最新是 **0.8.0**（不是 §3 寫的 0.4.0），依賴 protobuf、pynng、jsonschema。
  在暫存 venv 安裝成功。它是對 KiCad 10.0.6 編的：`flip_items`、`get_layer_by_name` 等方法要 10.0.6 才有，
  `get_items_by_net`、`get_groups` 要 10.0.1。`kipy.schematic` 在 0.8.0 匯入會失敗（`PageSettings` 匯入錯誤），
  跟「KiCad 10 沒有原理圖指令」一致。`board_jobs`（輸出設定）有型別，但 `Board` 沒有對應方法。
  → Phase 4 前建議把 KiCad 升到 10.0.6。
- **IPC API server：** 目前關閉（`%APPDATA%/kicad/10.0/kicad_common.json` 的 `api.enable_server: false`）。
  Phase 4 前要在 KiCad 偏好設定裡打開，確切位置屆時再確認。
- **Footprint 庫：** 有 `Module:Pololu_Breakout-16_15.2x20.3mm`、`RaspberryPi_Pico_Common_THT`、`Arduino_Nano`；
  沒有 Nucleo-144 的 footprint。MKS TMC2209 V2.0 是 18 腳，`Pololu_Breakout-16` 不夠用，要自建。
- **測試：** 15 個測試在系統 Python 3.10 與 KiCad Python 3.11 都通過。

### Phase 1 結果（2026-10-29）

- **套件：** `skills/kicad-clean-pcb/kcp/`，只用標準函式庫（vermin 檢查最低 3.7，宣告 3.9+）。
  執行方式 `python <skill>/kcp <指令>`；`pyproject.toml` 可 `pip install`，提供 `kcp` 指令。
  `inspect` 模組命名為 `inspection.py`，避免蓋掉標準函式庫的 `inspect`；之後的 `trace.py` 也要改名（標準函式庫有 `trace`）。
- **指令：** `inspect`、`lint`、`decisions`、`drc`、`erc`。輸出 JSON 或 `--markdown`；結束碼 0／1（檢查失敗）／2（無法執行）。
- **解析驗證（CAD 已檢查）：** 用 KiCad 自己的 pcbnew 比對兩塊真實板子（prpr_carrier DRAFT-03、DRAFT-02），
  pad 位置、角度、net、文字位置誤差都是 0。文字寬度估算：KiCad 實際約 0.81–1.05 × 字數 × 字寬，取 0.9。
- **DRC：** kicad-cli 跑大板約 14 秒，所以 `inspect --drc` 是選用。DRC 預設在暫存複本上跑，因為 kicad-cli 會在板子旁產生 `.kicad_prl`。
- **lint 門檻校正：** DRAFT-03（整理過）整體 warn，只剩 11 個 S 形小折線；DRAFT-02（自動繞線）11 項 fail。
  「小折線」只算 S 形（轉過去再轉回來），寬線的 45° 倒角不算；signal via 上限以每條 pad 對 pad 連線計算。
- **測試：** 47 個測試（原有 15 個＋新增 32 個），系統 Python 3.10 與 KiCad Python 3.11 都通過。
  `tests/fixtures/lint_demo.kicad_pcb` 是手寫的 4 層小板，KiCad DRC 只報出刻意放的問題（懸空線、孤立鋪銅、絲印壓 pad）。

### Phase 2 結果（2026-10-29）

- 使用者 2026-10-29 指示「後面的 Phase 都直接依序執行完成」：Part B／C 由 agent 代填並標註「代填」；
  CP4（1:1 實物比對、LM2596 量測）與 CP6 標為 No，等使用者實物確認。
- `examples/stepper-carrier-2axis/`：126 × 146 mm、4L-S1、全 THT。`rebuild_stepper_carrier.py` 一次跑完，約 15 秒。
  ERC 0／0、netlist 與接線規劃一致、DRC 0、未連線 0、parity 0、via 0、lint（T）全 pass、回讀 PASS。
- 為了範例新增的 kcp 模組（Phase 3 再補 CLI 與測試）：`footprints`（從庫載入並放置）、`wiring`（接線規劃 →
  原理圖、讀回 KiCad netlist）、`board`（直接建板）、`route`（只准 0/45/90°、寫入前檢查間距）、`place`
  （移動、排列、fit check）、`previews`、`tracedrop`。
- 範例過程發現並修正：`kcp drc` 在暫存複本上跑時沒有帶 fp-lib-table；`gerber_readback.py` 在 cp950 主控台印 Ø 會當掉。
- C6 估算發現：每顆驅動器 100 µF 時，兩軸同時煞車可把 24 V 母線推到約 28 V（TMC2209 上限 29 V），改為 470 µF。

### Phase 3 結果（2026-10-29）

- CLI 新增：`place fit-check|move|row|edge`、`route path|cleanup|lane`、`previews`、`tracedrop`。
  `route.bus`（扇出、拒絕會交叉的順序）與 `route.lane_order`（playbook §3 的排序規則，回報交叉對）。
- `scripts/export_previews.py`、`trace_drop.py` 改成 kcp 的薄包裝，參數不變，任何 Python 3.9+ 可跑；
  `trace_drop.py` 在 DRAFT-03 實板上的輸出與舊 pcbnew 版逐字相同。
- 範例改用 `place.array`（兩個驅動器單元）與 `route.bus`（相線、DIR／STEP）重寫；
  `compare_gerbers.py` 比對 Phase 2 製造包：**幾何完全相同**。重建兩次，板檔逐位元組相同。
- 修正：`place.fit_check` 原本把重疊的矩形判成「相接」（間隙 0），改用分離軸測試；
  KiCad 會替沒有符號的安裝孔補上隨機 UUID 的欄位，改由 `place_footprint` 先寫好。
- SKILL.md 與 references（layout-rules、routing-playbook、checks-and-delivery、kicad-scripting 全面改寫）
  改成「呼叫哪個工具」。測試共 67 個。

### Phase 4 結果（2026-10-29）

- `kcp mcp`：16 個 MCP 工具，與 CLI 子指令一對一，標註唯讀／會寫入。有官方 SDK 時用它
  （**mcp 2.x 已把 FastMCP 改名為 `MCPServer`**，1.x 仍是 FastMCP，兩者都支援）；沒有時用內建 stdio JSON-RPC server。
  由 `.claude-plugin/plugin.json` 的 `mcpServers` 自動註冊（2026-10-30 從根目錄 `.mcp.json` 搬過去：
  根目錄 `.mcp.json` 在直接打開這個 repo 時也會被當成專案設定讀取，`${CLAUDE_PLUGIN_ROOT}` 沒有值，server 啟動失敗）。
- 測到並修正：SDK 會在多個執行緒同時跑工具，原本用全域 stdout 轉向收結果，會互相換掉、還可能吞掉協定訊息；
  改成 `cli.run()` 以 thread-local 回傳結果，不碰 stdout。
- 即時後端 `backends/ipc.py`（kipy）：用 `Board.get_as_string()` 讀開著的板子，檢查沿用檔案後端；
  每次修改是一筆 commit（`kcp: route NET`），Ctrl+Z 一次復原。`inspect`、`lint`、`place fit-check`、
  `place move`、`route path` 可用 `live`。**尚未對執行中的 KiCad 實測**（API server 目前關閉，要由使用者開啟）；
  以假 kipy 測試，並確認呼叫的屬性在真 kipy 0.8.0 類別上都存在。
- PyPI：`python -m build` 與 `twine check` 通過；發佈步驟在 `docs/RELEASING.md`，由使用者執行。測試共 74 個。

### Phase 5 準備與曝光（2026-10-29）

- Phase 5 由使用者主導（下單、組裝、量測），agent 不下單。已準備：`ORDER_SPEC.md`（JLCPCB 表單值、層序、
  詢價訊息、下單前檢查）與 `BRINGUP.md`（CP4 實物比對、組裝順序、上電步驟、量測表、回饋方式）。
- 已寫回 references 的通用教訓：回生能量要看「離驅動器電壓上限的餘裕」（24 V 母線離 29–30 V 只有 5–6 V）；
  上拉電阻可放在串聯電阻任一側，放在電源幹線經過的那側。
- 曝光：README 開頭一句話賣點、前後對比圖（`docs/images/lint-comparison.svg`）、範例連結；
  CHANGELOG 0.2.0；plugin、SKILL.md、kcp、pyproject 版本改為 0.2.0。GitHub topics、release、social preview
  由使用者在 GitHub 上設定（步驟見 `docs/RELEASING.md`）。
- 待使用者：CP4 實物比對、量 LM2596 與 470 µF；KiCad 升到 10.0.6、開 API server 後實測即時模式；
  決定是否 push 分支、開 PR、發佈 PyPI。

### 2026-10-30 收尾

- 使用者以 1:1 列印比對，位置都正確（CP4 = Yes）。手邊 470 µF 實測 Ø7 mm，耐壓多半不夠 24 V，範例維持 50 V／Ø10 規格。
- 這塊板不下單（CP6 = No），範例只用來示範與增強 MCP 工具。
- MCP 設定從根目錄 `.mcp.json` 移到 `plugin.json`（根目錄的會被當成專案設定讀取而啟動失敗）。
- 使用者同意公開 prpr 的模組實測尺寸（TMC2209、AM26LS32、Nucleo F446ZE 等）與 README 的 lint 對比數字。
- 使用者同意合併回 main 並推上 GitHub；plugin 以使用者層級 settings.json 安裝（GitHub marketplace）。
- 即時模式（IPC）尚未實測，需使用者開啟 KiCad API server。

### 2026-10-30 冷啟動試跑與 0.3.0 修正

- 冷啟動試跑：另一個沒有開發脈絡的 session，只靠 skill 文件從零做出 `led4ch`（2 層、4 路 12 V LED 驅動，
  93.98 × 69.1 mm），ERC／DRC／parity 皆 0、Gerber 回讀通過。報告在分支 `claude/gallant-dirac-7ad866`
  的 `trials/cold-start-2026-10-30/TRIAL_REPORT.md`（未合併）。
- 依使用者指示修正報告建議的前 5 項（分支 `dev/trial-fixes`，版本 0.3.0）：
  1. 安裝說明（擇一安裝、刪掉舊的複製版、開新 session）、SKILL.md 版本自檢、CLI↔MCP 對照表。
  2. `tracedrop` 同號焊盤視為同一腳。
  3. 2 層板走線預覽頂層最後畫；外層有鋪銅時每個外層另出一頁。
  4. `place edge`／`fit-check` 納入絲印（KiCad 允許絲印碰到板邊、不允許超出）。
  5. `kcp new` 專案樣板、`kcp fab`（MCP `export_fab`）、`kcp drc --refill --save`、`kcp.project.write_project`。
- 範例改用新函式後重建：板子內容不變。測試 80 個，Python 3.10 與 KiCad 的 3.11 都通過。
- 報告第 6–13 項（絲印自動擺放、查庫 footprint 工具、CP4 閘門語意、circuit-policy 補充、lint 小修等）尚未處理。

### 2026-10-30 第二次冷啟動試跑與 0.4.0 修正

- 第二次冷啟動試跑（0.3.0）：從零做出 `sw3ch`（12 V、3 路低側開關，92 × 39 mm，2 層、0 via），
  ERC／DRC／parity 0、Gerber 回讀通過，lint 一項 warn（2L-a 頂層方向一致率 61.8 %，有說明）。
  卡關 20 處（0 卡死、5 拖慢、15 小問題），上次 25 處。報告在分支 `claude/strange-brattain-e086c7`
  的 `trials/cold-start-v0.3/TRIAL_REPORT.md`（未合併）。
- 依使用者指示修正 F1–F5（分支 `dev/trial2-fixes`，版本 0.4.0）：
  1. F1 `kcp doctor`（MCP `check_setup`）：列出這台電腦上每份 skill 與版本，指出過期的 plugin 和舊的複製資料夾；
     MCP 每個結果附 `kcp_version`；README 新增「更新」一節（第三方 marketplace 預設不自動更新）。
  2. F2 `kcp new` 的 `kcp_path.py` 記錄產生時的版本，跳過較舊的副本，找不到時列出找到的版本與解法。
  3. F3 `place edge --entry auto|left|right|top|bottom`：把連接器轉到線材從板外插入。方向表以 KiCad 10
     的 3D 渲染（前／後視圖）驗證；JST EH 與 PH／XH 方向相反。另讀 footprint 的「PCB Edge」標記並回報距離。
  4. F4 `kcp.place.to_edge` 與 `kcp new` 擺放樣板的 `EDGE` 表。
  5. F5 `kcp drc` 的 `details`：每一項的零件、項目與座標，用板檔 uuid 命名，不受 KiCad 介面語言影響。
- `kcp doctor` 在這台電腦上另外找到 `~/.codex/skills/kicad-clean-pcb`（無版本號的舊版）。
- 測試 87 個，Python 3.10 與 KiCad 的 3.11 都通過；範例重建後板子與 Gerber 幾何不變。

### 2026-11-01 桌面版更新方法（0.4.1）

- 0.4.0 已合併進 `main` 並推上 GitHub（2026-10-31）。使用者的 plugin 由 agent 用桌面版 app 內建的
  `claude.exe` 從 0.2.0 更新到 0.4.0：桌面版的 `claude` 不在 PATH，PowerShell 找不到。
- 0.4.1（分支 `dev/desktop-update`）：`kcp doctor` 在 PATH 找不到 `claude` 時，改用桌面版內建那份
  （Windows：`%APPDATA%\Claude\claude-code\<版本>\<build>\claude.exe`），更新建議附上 marketplace 與
  plugin 兩步和完整路徑；`--no-kicad` 時顯示「not checked」而不是「not found」；README 補上桌面版的
  更新方法與 PowerShell 指令（已在這台電腦驗證能找到程式）。測試 88 個，兩個 Python 版本都通過。
