# 用 AI Agent 在 KiCad 畫 PCB（`kicad-clean-pcb`）

[English](README.md)

這是一個給 **Claude Code 與 OpenAI Codex** 用的 **Agent Skill**。它帶著 agent 把一塊
**KiCad PCB** 從「能運作的原型」做到「可以下單的 **Gerber 與鑽孔檔**」，過程中使用者全程參與：

- 一開始先選版面風格，
- 每個附加電路都在 yes/no 清單裡由你決定，
- 擺放用 **1:1 列印確認之後才開始走線**。

它**不是自動繞線器**。它是一套流程、版面規則與檢查方法，讓 AI agent 像一位細心的 PCB 設計者那樣工作。適合手焊的控制板、馬達驅動板與模組載板。

## 為什麼做這個

起點是把一塊洞洞板原型做成四層載板。原型上有 MCU 開發板、步進驅動模組、編碼器接收器和電流量測模組。

agent 第一次用自動放置加格點繞線，DRC 全過，但結果是：

- 約一萬段鋸齒線，
- 四塊鋪銅，
- 整塊板沒有人看得懂。

重新整理後只剩約 600 段線和 30 個 via、一層 GND 平面，板子面積也少了約三分之一。

1:1 紙本比對太晚做（走線之後）。它抓到三個問題：USB 被排座擋住、保險絲座腳距和實物不符、模組本身已有的端子台在板上又做了一組。三個都得重新走線。

這個 skill 把解決這些問題的做法整理起來，讓下一塊板不再重蹈覆轍：

- **早一點、用文字決定。** 偏好和附加電路在原理圖之前就定案，記在雙方都看得到的檔案（`PCB_DECISIONS.md`）。
- **先擺放、列印、確認，再走線。** 機構錯誤在紙上就發現，不用等到走線之後。
- **依功能群逐一走線。** 只用直線和 45°、每層一個主方向、via 盡量少，每群走完跑 DRC。
- **不多加，也不偷偷少做。** 使用者沒同意的保護、buffer、測試點不加；使用者想要的保護也不會被默默省略。

## 內容

- **七個階段、四個確認點：** 需求與接線 → 零件與決策 → 原理圖 → 擺放（1:1 確認）→ 走線 → 驗證與製造檔 → 收尾。
- **三種預設風格，加上 17 個可調整的偏好項目：** 整齊易讀、精簡／最短路徑、電氣最高規格。偏好項目涵蓋疊層、via、鋪銅、保護策略、電流目標、溫升上限、組裝方式、絲印、確認頻率等。
- **`PCB_DECISIONS.md`：yes/no 交握範本。** 內容包括：
  - 範圍檢查（市電、超過 60 V、鋰電池、高速訊號、安全關鍵用途），
  - 使用者偏好，
  - 每一項可選的保護或附加電路一列，
  - 每一項可選的技術檢查一列，
  - 各確認點簽核與變更紀錄。

  **空白就代表「未同意」。**
- **參考文件：** 各風格的版面規則；電路原則（附加電路 A–D 分類、額定、反接保護選項、馬達回生能量）；含疊層選項的走線手冊；驗證與下單規格範本；KiCad 10 腳本注意事項；台灣下單注意事項。
- **板子工具（`kcp`）與四支腳本：** 見下方[工具與腳本](#工具與腳本)。`kcp` 直接讀 `.kicad_pcb`，
  其中的整齊度評分（lint）把「這塊板好不好讀」變成數字：每 mm 線段數、鋸齒轉折、非 0／45／90° 線段、
  電源 net 上的 via、各層主方向、GND 以外的鋪銅、電阻排對齊。

## 適不適合你

**適合**

- 手上有能運作的原型（洞洞板、麵包板、杜邦線、開發板與模組），想做成正式 PCB。
- 中低速電路：MCU I/O、馬達驅動、感測器、編碼器、RS-422／RS-485、I²C／SPI／UART。
- 使用 Claude Code、Codex 或其他支援 Agent Skills 的 agent，而且想自己確認重要決定。

**不適合**

- RF、DDR、USB 高速等需要阻抗控制的設計；接市電或隔離電源；電池充電；超過 60 V DC；安全關鍵或醫療用途。skill 的範圍檢查會直接說明不適用。
- 想要「什麼都不問就把整塊板畫完」。這個 skill 會刻意在四個確認點停下來問你。

## 版本需求與注意事項

| | 已測試 | 說明 |
|---|---|---|
| KiCad | **10.0.x** | `kicad-cli` 參數和 Gerber 檔名會隨版本改變。skill 會先查 `--help`，並用 X2 屬性辨識 Gerber 層別，不靠副檔名 |
| 作業系統 | Windows 10 | macOS／Linux 應可使用，但文件中的路徑以 Windows 為主，未實測 |
| `kcp` 與板子腳本的 Python | 3.9 以上（只用標準函式庫） | 直接讀寫 KiCad 檔案，完全不用 `pcbnew`（已棄用，KiCad 11 移除）。DRC、ERC、netlist、預覽與製造檔交給 `kicad-cli` |
| Gerber 工具的 Python | 3.8 以上（只用標準函式庫） | `gerber_readback.py` 與 `compare_gerbers.py` 不需要 KiCad |
| Agent | Claude Code、Codex | 能讀取 `SKILL.md` 資料夾（Agent Skills 格式）的 agent 都應可使用 |

## 安裝

### Claude Code：plugin marketplace（建議）

在 Claude Code 對話中輸入：

```text
/plugin marketplace add haohao-0725/PCB_Layout_with_AGENT_in_KiCAD
/plugin install kicad-clean-pcb@pcb-layout-with-agent
```

### Claude Code：直接複製資料夾

```bash
git clone https://github.com/haohao-0725/PCB_Layout_with_AGENT_in_KiCAD.git
cp -r PCB_Layout_with_AGENT_in_KiCAD/skills/kicad-clean-pcb ~/.claude/skills/
```

只想在單一專案使用時，改放 `<專案>/.claude/skills/`。

### Codex

```bash
cp -r PCB_Layout_with_AGENT_in_KiCAD/skills/kicad-clean-pcb ~/.agents/skills/
```

只想在單一 repo 使用時，改放 `<repo>/.agents/skills/`。舊版 Codex 讀取的是 `~/.codex/skills/`。安裝後請重新啟動 Codex。

## 開始使用

直接描述你的板子，例如：

- 「把我的洞洞板步進控制器做成 PCB，腳位表、BOM 和照片在這裡。」
- 「這是我的 KiCad 原理圖，幫我擺放並走出看得懂的線。」
- 「下單前幫我檢查這些 Gerber。」

agent 會先做範圍檢查、請你選預設風格，然後在專案裡建立 `PCB_DECISIONS.md`。之後每個確認點，它都會用一則訊息列出所有需要你回答的事項。

## 預設風格

| | T · 整齊易讀 | C · 精簡／最短路徑 | R · 電氣最高規格 |
|---|---|---|---|
| 目標 | 一眼看懂、好焊好改 | 板子最小、連線最短、成本最低 | 訊號完整性、散熱裕度、故障容忍度最好 |
| 走線 | 直線＋45°、每層一個主方向、通道排序 | 最短 45° 路徑 | 同 T，再加回流路徑規則 |
| 四層疊層 | 訊號／GND／GND／訊號 | 訊號／GND／電源／訊號 | 訊號／GND／GND／訊號 |
| 附加電路 | 精簡（以原型為準） | 精簡 | 外部接口全面保護 |
| 電流目標／溫升上限 | 實測 2 倍／20 °C | 實測 2 倍／20 °C | 最壞情況／10 °C |

各項目可以混搭，例如整齊版面配全面保護。不管選哪一種，都保留：1:1 試合、實物量測封裝、原生檢查歸零、附層序對照表的 Gerber 回讀。

## 流程

| 階段 | 產出 | 你確認 |
|---|---|---|
| 0. 範圍、風格、偏好 | `PCB_DECISIONS.md` Part A | ✔ |
| 1. 硬體清單、需求、接線規劃 | 專案 brief | ✔ |
| 2. 缺料、附加電路決策 | BOM、實測尺寸、yes/no 清單全部作答 | ✔ |
| 3. 原理圖 | ERC 歸零、netlist 與接線表比對 | 有疑點才問 |
| 4. 擺放 | 預覽圖與 **1:1 試合 PDF** | ✔ **通過前不走線** |
| 5. 走線 | 分群走線、每群跑 DRC | 完成後一次確認 |
| 6. 驗證與製造檔 | DRC／parity 歸零、Gerber＋鑽孔＋回讀、下單規格 | ✔ |
| 7. 收尾 | 單一重建入口、舊檔封存、交接文件 | — |

## 工具與腳本

### 板子工具：`kcp`

任何 Python 3.9 以上都能跑；除了 `drc`、`erc` 以外不需要 KiCad。每個指令輸出 JSON，加 `--markdown`
改輸出表格。結束碼 1 代表檢查沒過，2 代表工具無法執行。

| 指令 | 用途 |
|---|---|
| `inspect` | 把板子讀成 JSON：板框尺寸、層與疊層、footprint 的位置／角度／正反面／courtyard 與 pad、net 的 netclass 與走線統計、走線／via／鋪銅。加 `--drc` 會附上各 net 的未連線數 |
| `lint` | 依預設風格（T、C、R）評整齊度，每項給 pass／warn／fail。門檻在 `kcp/presets/lint.json`，要改請複製一份再用 `--thresholds` 指定。給它 layer plan（`examples/layer-plans/`）就會檢查各層主方向 |
| `decisions` | 列出 `PCB_DECISIONS.md` 的空白列，中英文都可以。`--checkpoint CP2` 在 CP2 需要的項目還有空白時回傳 1 |
| `drc`、`erc` | 把 kicad-cli 的 DRC／ERC 依類型彙整，並列出各 net 的未連線數。DRC 在暫存複本上跑，不會在你的板子旁邊產生檔案 |
| `place` | `fit-check`（courtyard 重疊、離板邊距離、禁區）、`move`、`row`、`edge`。KiCad 開著專案時拒絕寫入 |
| `route` | `path`：焊盤 → 轉折點 → 焊盤，每段都是 0／45／90° 且符合 netclass 間距才寫入，否則列出衝突。`lane`：通道內不交叉的排序。`cleanup`：合併共線線段 |
| `previews`、`tracedrop` | 審查用 PDF／PNG 與 1:1 試合頁；某個 net 的壓降與溫升 |

```bash
python skills/kicad-clean-pcb/kcp inspect board.kicad_pcb --summary --markdown
python skills/kicad-clean-pcb/kcp lint board.kicad_pcb --preset T --layer-plan examples/layer-plans/4L-S1.json --markdown
python skills/kicad-clean-pcb/kcp decisions PCB_DECISIONS.md --checkpoint CP2
python skills/kicad-clean-pcb/kcp drc board.kicad_pcb --refill
```

用這個 skill 起源的那塊板子比較，lint 能清楚分出兩個版本：

| 項目 | 自動繞線草稿 | 重新整理後 |
|---|---:|---:|
| 每 mm 走線的線段數 | 1.00 | 0.09 |
| 每 10 mm 轉折數（鋸齒） | 8.8 | 0.5 |
| 非 0／45／90° 線段 | 79 | 0 |
| 電源／相線上的 via | 24 | 0 |
| GND 以外的鋪銅 | 3 | 0 |
| 電阻排最大對齊偏差 | 1.35 mm | 0 mm |
| 結果（T 預設） | 11 項 fail | warn（11 個短 S 形小折線待確認） |

### 腳本

| 腳本 | 用途 | 執行環境 |
|---|---|---|
| `export_previews.py` | 走線、裝件、內層預覽（PDF＋PNG）與 A4／A3 的 1:1 試合 PDF（同 `kcp previews`） | Python 3.9 以上 |
| `trace_drop.py` | 沿某個 net 的走線估算到各負載的壓降與 IPC-2221 溫升（同 `kcp tracedrop`） | Python 3.9 以上 |
| `gerber_readback.py` | 從 X2 屬性讀出各層用途與銅層順序、板框尺寸、PTH／NPTH 孔與槽孔數，可比對預期值 | Python 3.8 以上 |
| `compare_gerbers.py` | 比對兩包 Gerber／鑽孔檔的幾何（直線、圓弧、焊盤、區域、孔、槽孔） | Python 3.8 以上 |

在 Windows 上執行時請設定 `PYTHONUTF8=1`。單元測試（不需要 KiCad；有一個整合測試只在裝了 `kicad-cli` 時執行）：

```bash
python -m unittest discover -s tests -v
```

## 儲存你的預設值

如果你每次都用同一組偏好開始，可以把填好的 Part A 存成自己的檔案，放在 skill 安裝資料夾**以外**的地方
（更新 skill 會覆蓋那個資料夾）。可以從
[`examples/defaults/PCB_PART_A_DEFAULTS.md`](examples/defaults/PCB_PART_A_DEFAULTS.md) 開始改，
再在全域說明檔（Claude Code 用 `~/.claude/CLAUDE.md`，Codex 用 `AGENTS.md`）裡指向它：

```markdown
## PCB 工作
使用 kicad-clean-pcb skill 時，我的 Part A 預設值在 ~/pcb-defaults/PCB_PART_A_DEFAULTS.md。
每個新專案的 PCB_DECISIONS.md 都先複製它，再請我確認一次。
```

在 stage 0，agent 會把它複製進專案，只請你確認一次，不必逐項回答。

## 限制與免責聲明

- **經驗法則，不是標準。** 規則來自手焊的中低速板。電流、溫升、間距等關鍵數值，請對照 datasheet、IPC 標準與板廠製程能力。
- **CAD 通過不等於硬體驗證。** DRC 通過不代表波形、溫度、實際插拔都沒問題，請用實板測試。
- **只是估算。** `trace_drop.py` 用 IPC-2221 公式，不計入鋪銅、焊盤與接頭。
- **Gerber 工具沒檢查的部分。** 不檢查 aperture macro 內容與 step-and-repeat 區塊。
- **agent 不會替你下單或付款。** 它只準備檔案與規格，下單由你自己進行。
- **不提供任何保證。** 依 MIT 授權「現狀」提供，製作的板子由使用者自行負責。

## 授權

[MIT](LICENSE)
