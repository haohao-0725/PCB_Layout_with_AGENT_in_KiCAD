# Regional notes: ordering PCBs from Taiwan

Read this file only when Part A (A16) or the user says the board is ordered from Taiwan. The
general order spec is in [checks-and-delivery.md](checks-and-delivery.md) §4. This adds the
local details.

## Local shops and marketplace sellers (e.g. Shopee 蝦皮)

- **Layer count.** Many listings only make 1–2 layer boards. For 4+ layers, ask first.
- **Who makes the board.** Ask whether they manufacture in-house or forward the order (代下單).
  If they forward it, ask which factory makes it and where it ships from; it affects lead time
  and customs.
- **Invoice.** Labs and companies often need a 統一編號 on the invoice. Ask if they can issue
  one.
- **Engineering approval.** Ask for 工程確認檔 (engineering confirmation files) before
  production, and check the layer order in them.

### Message template (Traditional Chinese)

```text
您好，想詢問 N 層 PCB 打樣報價，Gerber 壓縮檔如附件：
- 板材 FR-4、N 層、板厚 1.6 mm
- 尺寸 W × H mm、數量 5 片、不拼板
- 銅厚：外層 1 oz、內層 0.5 oz（內層 1 oz 也可以，請一併報價）
- 疊層順序：L1 = <檔名>、L2 = <檔名>、L3 = <檔名>、L4 = <檔名>
- 最小線寬 X mm、最小間距 Y mm、最小孔 Z mm（via 防焊蓋孔）
- 綠油白字、有鉛噴錫（或無鉛噴錫）
- 無阻抗控制、無金手指、無半孔；只要空板，不需要上件
想確認：交期、含運總價、是否可開統編發票、生產前能否提供工程確認檔。謝謝！
```

Fill the layer order from `gerber_readback.py`, never from file extensions.

## Ordering directly from an overseas online fab

- **Customs.** Express parcels into Taiwan need the recipient's real-name verification in the
  customs **EZ WAY (易利委)** app. Have the user complete it before the parcel arrives, or
  clearance stalls.
- **Order form.** Fill it as in checks-and-delivery.md §4.4. After upload, check the layers,
  outline, silkscreen and drills in the fab's online Gerber viewer.
