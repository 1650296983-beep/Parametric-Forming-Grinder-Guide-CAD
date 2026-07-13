# 尺寸识别规则

依据 `QG 38002 磁钢规格描述管理办法`，瓦型磁钢规格按以下结构识别：

```text
R外径 x R内径 x 角度（弦长） x 高 x 壁厚
```

本项目当前用于成型磨导轨 CAD 时，按以下落地规则执行：

1. 分隔符可识别 `*`、`x`、`X`、`×`，允许分隔符两侧有空格。
2. 瓦型前两项必须带 `R` 前缀，分别进入 `R_outer_finished` 与 `R_inner_finished`。
3. 第三项当前按弦宽 `chord_width` 识别；带 `°` 的角度规格暂不直接生成导轨槽宽，后续需按图纸规则换算成弦宽后再生成。
4. 第四项识别为产品长度 `length`。
5. 第五项识别为成品壁厚 `finished_thickness`，壁厚是独立字段。
6. 不再要求 `abs(R_outer_finished - R_inner_finished) == finished_thickness`；异心异 R 产品允许 R 差值与壁厚不同。
7. 成型磨仍按同 R 规则设计：`R_form = max(R_outer_finished, R_inner_finished)`。
8. forming_profile 的内外弧半径均取 `R_form`，厚度按显式 `finished_thickness`。
9. 第三项弦宽必须带上下公差，导轨槽宽按 `弦宽 + (上偏差 + 下偏差) / 2 + 标准间隙中间值` 计算原始值，再按机台 0.01 mm 精度半入进位。
10. 标准间隙中间值按 `QG 38012`：成型磨前宽度公差 `<= 0.02 mm` 时取 `0.04 mm`，`> 0.02 mm` 时取 `0.05 mm`；特殊对称度或大瓦片放宽必须显式输入工艺覆盖值。
11. 导轨厚度按 `product_thickness + thickness_clearance_mid`。方块默认 `0.12 mm`，方块磨单边默认 `0.09 mm`，小瓦默认 `0.18 mm`，相对大瓦默认 `0.25 mm`；特殊高要求必须显式输入覆盖值。

示例：

```text
R17.5*R15.7*6.00(-0.02/-0.04)*1.5*1.8
R17.5 x R15.7 x 6.00(-0.02/-0.04) x 1.5 x 1.8
R13.73*R17.13*4.50(-0.02/-0.05)*9.6*1.6
```

其中 `R13.73*R17.13*4.50(-0.02/-0.05)*9.6*1.6` 属于允许的异心异 R 输入：

- `R_form = 17.13`
- `product_preform_width_average = 4.465`
- `guide_slot_width = 4.52`
- `guide_thickness = 1.78`
- `finished_thickness = 1.60`
