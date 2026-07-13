# 槽宽规则

## 输入格式

弦宽字段必须带成型磨前产品宽度上下公差：

```text
4.50(-0.02/-0.05)
6.20(-0.02/-0.04)
```

带公差时：

- `nominal_chord_width = 4.50`
- `preform_upper_tol = -0.02`
- `preform_lower_tol = -0.05`

不允许输入无公差槽宽。图纸示例中只显示 `6.20` 时，视为标注未完整表达；程序输入仍必须写明上下公差。

## 标准间隙

槽宽按 `QG 38012《成型磨导轨设计方法》` 的导轨宽度规则计算：

- 成型磨前宽度公差 `<= 0.02 mm`：间隙中间值留 `0.04 mm`。
- 对称度要求特别高：间隙中间值可缩小到 `0.03 mm`，必须由显式工艺参数覆盖。
- 成型磨前宽度公差 `> 0.02 mm`：间隙中间值留 `0.05 mm`。
- 大瓦片产品可适当放宽到 `0.08 mm`，必须由显式工艺参数覆盖。
- 大瓦片定义：瓦片宽度 `> 15 mm`。

## 槽宽计算

带公差输入必须按成型磨前产品宽度中值加标准间隙计算：

```text
preform_width_max = nominal_chord_width + preform_upper_tol
preform_width_min = nominal_chord_width + preform_lower_tol
preform_width_mid = (preform_width_max + preform_width_min) / 2
preform_width_tolerance_range = preform_width_max - preform_width_min
slot_clearance_mid = standard clearance from QG 38012
slot_width_raw = preform_width_mid + slot_clearance_mid
slot_width = slot_width_raw rounded half-up to 0.01 mm
```

默认标准间隙：

```text
slot_clearance_mid = 0.04 if preform_width_tolerance_range <= 0.02
slot_clearance_mid = 0.05 if preform_width_tolerance_range > 0.02
machine_precision = 0.01
```

等价公式：

```text
slot_width_raw = nominal_chord_width + (preform_upper_tol + preform_lower_tol) / 2 + slot_clearance_mid
slot_width = slot_width_raw rounded half-up to 0.01 mm
```

示例：

```text
4.50(-0.02/-0.05)
preform_width_max = 4.50 - 0.02 = 4.48
preform_width_min = 4.50 - 0.05 = 4.45
preform_width_mid = (4.48 + 4.45) / 2 = 4.465
preform_width_tolerance_range = 4.48 - 4.45 = 0.03
slot_clearance_mid = 0.05
slot_width_raw = 4.465 + 0.05 = 4.515
slot_width = 4.52
```

几何实测槽宽和尺寸显示均应为 `4.52` mm，因为机台最小精度为 0.01 mm。

示例：

```text
6.20(-0.02/-0.04)
preform_width_max = 6.20 - 0.02 = 6.18
preform_width_min = 6.20 - 0.04 = 6.16
preform_width_mid = (6.18 + 6.16) / 2 = 6.17
preform_width_tolerance_range = 6.18 - 6.16 = 0.02
slot_clearance_mid = 0.04
slot_width_raw = 6.17 + 0.04 = 6.21
slot_width = 6.21
```

## 报告要求

`report.json` 必须输出：

- 槽宽计算公式；
- `preform_width_max`；
- `preform_width_min`；
- `preform_width_mid`；
- `preform_width_tolerance_range`；
- `slot_clearance_mid`；
- `slot_width_raw`；
- `machine_precision`；
- rounding method；
- `slot_width`；
- 槽宽范围；
- 产品宽度范围；
- 总间隙范围；
- 单边间隙范围。
