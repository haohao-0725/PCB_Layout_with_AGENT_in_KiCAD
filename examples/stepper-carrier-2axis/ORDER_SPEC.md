# 下單規格：stepper_carrier rev A（JLCPCB）

所有數值取自實際板子與 `reports/readback.md`，不是沿用別塊板子。
**agent 不會上傳、下單或付款。** 下單前必須先完成 CP4（1:1 列印實物比對、量好 LM2596 模組）。

## 1. 規格表

| 項目 | 值 | 備註 |
|---|---|---|
| 板材／層數／板厚 | FR-4／4 層／1.6 mm | |
| 尺寸／數量 | 126 × 146 mm 矩形／5 片 | 板框線中心量測（CAD 已檢查） |
| 銅厚 | 外層 1 oz、內層 0.5 oz | 走線溫升以這組值估算（C2） |
| 疊層順序 | L1 = `stepper_carrier-F_Cu.gtl`、L2 = `stepper_carrier-In1_Cu.g1`、L3 = `stepper_carrier-In2_Cu.g2`、L4 = `stepper_carrier-B_Cu.gbl` | 由 X2 屬性回讀，**一定要寫給板廠** |
| 最小線寬／間距 | 0.25 mm／0.2 mm | 電源 1.5 mm、相線 1.0 mm |
| via | 無 | 全板 0 個 via，不需要塞孔 |
| 鑽孔 | PTH 222 孔：Ø0.8 × 20、Ø1.0 × 184、Ø1.3 × 4、Ø1.6 × 14；NPTH 4 孔：Ø3.2 | 回讀結果，PTH／NPTH 分檔 |
| 防焊／絲印 | 綠色／白色 | |
| 表面處理 | 有鉛噴錫（HASL）；需要 RoHS 時改無鉛噴錫 | 手焊 THT 不需要 ENIG |
| 其他 | 不拼板、無阻抗控制、無金手指、無半孔、只要空板 | |

## 2. JLCPCB 線上表單建議值

| 欄位 | 建議值 |
|---|---|
| Base Material | FR-4 |
| Layers | 4 |
| Dimensions | 126 × 146 mm |
| PCB Qty | 5 |
| PCB Thickness | 1.6 mm |
| PCB Color | Green |
| Silkscreen | White |
| Surface Finish | HASL (with lead)（或 LeadFree HASL） |
| Outer Copper Weight | 1 oz |
| Inner Copper Weight | 0.5 oz |
| Specify Stackup | 選預設疊層即可；依上表確認 L1–L4 檔名順序 |
| Via Covering | Tented（本板沒有 via，不影響） |
| Impedance Control | No |
| Confirm Production File | Yes（第一次做 4 層板） |
| Mark on PCB | 依需求：指定位置或付費移除訂單號 |
| Remove Order Number | 可放在左下角「kicad-clean-pcb example」文字旁的空白處 |

上傳 `fab/stepper_carrier_revA_fab.zip` 後，在 JLCPCB 的線上 Gerber 檢視器確認：
層數與順序、板框、絲印、鑽孔（4 個 Ø3.2 安裝孔是 NPTH）。

## 3. 詢價訊息（給代購或在地店家時使用）

```text
您好，想詢問 4 層 PCB 打樣報價，Gerber 壓縮檔如附件：
- 板材 FR-4、4 層、板厚 1.6 mm
- 尺寸 126 × 146 mm、數量 5 片、不拼板
- 銅厚：外層 1 oz、內層 0.5 oz
- 疊層順序：L1 = stepper_carrier-F_Cu.gtl、L2 = stepper_carrier-In1_Cu.g1、
  L3 = stepper_carrier-In2_Cu.g2、L4 = stepper_carrier-B_Cu.gbl
- 最小線寬 0.25 mm、最小間距 0.2 mm、最小孔 0.8 mm（沒有 via）
- 綠油白字、有鉛噴錫
- 無阻抗控制、無金手指、無半孔；只要空板，不需要上件
想確認：交期、含運總價、是否可開統編發票、生產前能否提供工程確認檔。謝謝！
```

## 4. 下單前的檢查清單

- [ ] CP4：列印 `review/stepper_carrier_fit_check_1to1_A4.pdf`（實際大小／100 %），先量板框 126 × 146 mm。
- [ ] 把 Nucleo、兩個 TMC2209 模組、端子台、保險絲座放上去核對孔位。
- [ ] 量 LM2596 模組的 4 個焊盤位置，和封裝 `LM2596_Module_43x21mm` 比對（目前是假設值）。
- [ ] 量 470 µF 電容直徑（封裝是 Ø10 mm）。
- [ ] 若有修改：執行 `rebuild_stepper_carrier.py`，再用 `compare_gerbers.py` 比對新舊製造包。
- [ ] 下單、付款由使用者自己進行。
- [ ] 收到板子後依 [BRINGUP.md](BRINGUP.md) 組裝、上電並記錄量測值。
