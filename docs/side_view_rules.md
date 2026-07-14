# 侧面投影规则

侧面投影图与截面图一起输出在 DXF 和 PNG 预览中。侧面固定结构来自机台 `side_template.dxf` 和 `config.yaml`，派生尺寸来自当前产品导轨参数。

## 固定模板

固定模板尺寸由机台配置控制：

- `guide_length`
- `side_fixed_spans`
- `wheel_positions`
- `guide_sections`
- `layout`

对于双头机 435 mm 模板，固定分段为：

```text
90 + 200 + 145 = 435
```

对于三头机单导轨（上上）379 mm 模板，固定分段为：

```text
99 + 180 + 100 = 379
```

三头机单导轨（下上）379 mm 模板同样使用：

```text
99 + 180 + 100 = 379
```

砂轮位置为 `["下", "上"]`，侧面模板必须保留下砂轮、上砂轮各一个 R80 缺口。

三头机单导轨（下上）的侧面投影不得套用普通瓦型的 `slot_base_height + 0.50` 规则：

```text
slot_base_height = 12.0  # 截面型腔下沿固定值
slot_top_height = slot_base_height + guide_thickness
preform_block_thickness_mid = preform_thickness + (upper_tol + lower_tol) / 2
lower_requested_cut_in_depth = machine.block_to_tile_lower_wheel_cut_in
upper_requested_cut_in_depth = machine.block_to_tile_upper_wheel_cut_in
natural_opening = 2 * sqrt(80^2 - (80 - requested_cut_in_depth)^2)
opening_limit = product_length - 0.2
lower_cavity_notch_opening = min(natural_opening, opening_limit)
upper_cavity_notch_opening = min(upper_natural_opening, opening_limit)
effective_lower_cut_in_depth = 80 - sqrt(80^2 - (lower_cavity_notch_opening / 2)^2)
effective_upper_cut_in_depth = 80 - sqrt(80^2 - (upper_cavity_notch_opening / 2)^2)
effective_notch_top_height = slot_base_height + effective_lower_cut_in_depth
```

下砂轮 R80 圆心：

```text
center_y = lower_y + effective_notch_top_height - 80
```

上砂轮 R80 圆心：

```text
center_y = slot_top_y - effective_upper_cut_in_depth + 80
```

上砂轮圆弧必须与导轨上表面和型腔槽顶投影线真实相交，槽顶投影线断口端点必须落在 R80 弧上。上下两处 R80 半径标注的圆心定义点和箭头目标点必须跟随重算后的圆弧。

“缺口开口”必须分别对下、上砂轮计算。每一侧先按该机台配置的吃入量求 R80 自然开口；若开口超过 `product_length - 0.2`，则移动对应 R80 圆心并重算有效吃入量。因而 `lower_cavity_notch_opening` 与 `upper_cavity_notch_opening` 均必须严格小于产品长度，且不大于 `product_length - 0.2`。该约束适用于所有机台、所有含对应砂轮的位置，不能只覆盖下砂轮。

release 校验必须从 DXF 几何实体直接测量上下 R80 的最终开口，并要求每个实测值不大于 `product_length - 0.2`、与报告值误差小于 `0.01 mm`。

固定 R80 砂轮投影必须保留为 R80，但位置可根据当前导轨派生尺寸更新。

对于 618 磨床 300 mm 模板，固定分段为：

```text
170 + 130 = 300
```

618 砂轮位置为 `["上"]`，侧面模板必须保留一个上砂轮 `R80` 缺口，并保留面端 `R15` 上料缺口。618 的导轨型腔下沿高度为固定 `20.9`，侧面投影中该内部槽线必须放在 `SIDE_DERIVED` 层；槽顶线按当前导轨厚度派生：

```text
side_projected_slot_height = 20.9
side_slot_top_height = 20.9 + guide_thickness
side_clearance_height = guide_outer_height - 20.9 - guide_thickness + wheel_cut_allowance
```

618 不套用普通瓦型的 `slot_base_height + 0.50` 作为型腔下沿投影高度。

既有单导轨模板继续按各自规则使用 `SIDE_DERIVED`，型腔投影线统一继承绿色 `3` 和 `DASHED`。双导轨机型的机台外轮廓放在 `SIDE_TEMPLATE`，颜色 `7`、线型 `Continuous`；型腔投影线放在 `SIDE_CAVITY`，颜色 `3`、线型 `DASHED`；中心线使用 `SIDE_CENTER`。隐藏辅助线或 debug 线单独放在 `SIDE_DEBUG` 层并使用 `DASHED`。

## 派生尺寸

瓦型导轨侧面尺寸：

```text
side_projected_slot_height = slot_base_height + side_cut_in_allowance
side_clearance_height = guide_outer_height - slot_base_height - guide_thickness + wheel_cut_allowance
```

方块导轨侧面砂轮吃入统一使用成型磨前厚度中值：

```text
requested_cut_in_depth = preform_block_thickness_mid * 0.6
natural_opening = 2 * sqrt(80^2 - (80 - requested_cut_in_depth)^2)
opening_limit = product_length - 0.2
actual_opening = min(natural_opening, opening_limit)
effective_cut_in_depth = 80 - sqrt(80^2 - (actual_opening / 2)^2)
```

当自然开口未超限时，`effective_cut_in_depth` 必须等于 `preform_block_thickness_mid * 0.6`；超限时不得修改目标吃入公式，而应移动 R80 圆心，使最终开口不大于 `product_length - 0.2`。`block_side_projected_slot_height` 仍由机台模板配置控制，双头机上上默认为 `18.0`。

双头机（上下）方块磨前侧视图只保留型腔上下两条虚线。下边界在下 R80 处断开，上边界在上 R80 处断开；不得保留模板中的平行偏移副本形成重影。下、上 R80 的冠点分别进入型腔 `effective_cut_in_depth`，两条边界随当前导轨厚度同步重建。

618 的型腔上下两条绿色虚线均必须在 R80 缺口范围内断开，任何 `SIDE_DERIVED` 线段不得穿过砂轮弧。

R80 相关尺寸的定义点规则：半径标注为“圆心 → 真实弧顶”；吃入量和关键高度为“同 X 基准点 → 真实弧顶”。文字位置允许为避让而偏移，但 `defpoint2`、`defpoint3` 或半径目标点不得落在圆弧肩点、切点或历史模板坐标。

三头机单导轨（上上）不同：截面中的 `3` 为固定上口余量，不固定型腔底部高度：

```text
side_projected_slot_height = guide_outer_height - block_fixed_top_gap - guide_thickness
block_fixed_top_gap = 3.0
```

默认：

- `slot_base_height = 12.0`
- `side_cut_in_allowance = 0.50`
- `guide_outer_height = 27.0`
- `wheel_cut_allowance = 0.20`

示例：

```text
finished_thickness = 1.65
guide_thickness = 1.83
side_projected_slot_height = 12.0 + 0.50 = 12.50
side_clearance_height = 27.0 - 12.0 - 1.83 + 0.20 = 13.37
```

## 输出要求

## 方块磨前的机台固定基准

方块磨前产品的侧视图不得使用跨机型默认尺寸。`block_side_mode` 必须由
`templates/<machine_id>/config.yaml` 显式定义；缺失模式或其必需参数时，生成必须失败，
不得回退到其他机台的 `18.0 mm` 投影高度。

机台固定槽底基准由 `section_slot_base_height` 控制，产品形态不得改写它。产品只可影响
导轨厚度、砂轮吃入和由这些量派生的 R80 圆弧。

三头机单导轨（下上）的 `block_to_bread_rectangular` 使用：

```text
slot_base_height = section_slot_base_height = 12.0
lower_wheel_key_height = slot_base_height + block_lower_wheel_cut_in
upper_wheel_key_height = outer_height - slot_base_height - guide_thickness
                         + block_upper_wheel_cut_in
```

上下吃入均按 `preform_block_thickness_mid * 0.6` 计算。下、上 R80 圆心必须分别从上述两项关键高度派生；release 同时校验槽底基准、R80 圆心、关键高度和对应 DIMENSION 定义点。

`preview.png` 是供生成结果页快速复核的截面预览，应能看到：

- 仅导轨截面图，不绘制侧面投影图；
- 槽口；
- `R_form`；
- `slot_width`；
- `guide_thickness`；
- 上口、型腔下沿、导轨外形和避空等关键截面尺寸标注。

侧面投影及其 `side_projected_slot_height`、`side_clearance_height` 仍是 release
DXF 的受控派生几何和校验项，但不进入 PNG 预览，避免缩小截面和干扰操作员复核。

release DXF 中侧面派生尺寸的显示文字、DIMENSION 定义点和几何实测值必须一致。
