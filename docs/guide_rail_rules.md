# 成型磨导轨规则

本项目生成瓦型、面包型等产品的成型磨导轨 CAD，不生成任意 CAD、砂轮图纸、3D STEP 或 UI。当前已实现的具体产品与工艺组合以机台配置和回归测试为准。

## 产品形态与成型磨前形态

成品形态和成型磨前形态是两个独立维度，不得混为一谈：

- 成品形态可为瓦型、面包型等。
- 成型磨前形态可为同心 R、方块等。
- 同一种成品形态可能对应不同的成型磨前形态。
- 不能仅根据“成品是瓦型”推断导轨型腔必须为上下同 R。

参数模型应分别记录：

```text
finished_shape       # 成品形态，例如 tile、bread
preform_shape        # 成型磨前形态，例如 concentric_r、block
finished_spec        # 成品尺寸与最终轮廓
preform_spec         # 成型磨前尺寸及公差
```

当前规范 JSON 字段为：

```text
pre_grinding_spec
finished_spec
product_shape_before
product_shape_after
machine_type
guide_rail_type
wheel_sequence
first_wheel_side
template_coordinate_system
tolerance
```

旧字段 `finished_product_spec`、`pre_grinding_shape`、
`finished_product_shape` 仅作为兼容别名保留。槽型由
`src/groove_profile.py::determine_groove_profile` 集中决策，绘图函数不得
自行按 R 数量重复判断。返回结果至少包含 `groove_profile`、`flat_side`、
`arc_side`、`arc_radius`、`arc_center_side`、`dimension_source`、
`confidence` 和 `warnings`。

导轨槽宽、导轨控制厚度、型腔轮廓和砂轮吃进量原则上由 `preform_shape + preform_spec + machine_config` 决定；成品规格用于提供最终产品目标轮廓，以及方块磨瓦等工艺所需的成品外弧 R。

当前三头机单导轨（下上）属于：

```text
preform_shape = block
finished_shape = tile  -> process_type = block_to_tile
finished_shape = bread -> process_type = block_to_bread_rectangular
```

方块成型磨前按成品类型分流：

- `block_to_tile`：生成一平一弧，R 取成品两个 R 中的较大值；R 面必须与
  第一砂轮同侧，平面和圆心位于对侧。该方向规则适用于所有机台。
- `block_to_bread_rectangular`：导轨截面完全按磨前方块包络生成矩形槽；
  成品单 R 只记录为磨后目标，不进入导轨截面。

双 R 的圆心侧由第一砂轮侧的对立关系确定：上→下、下→上、左→右、
右→左；R 面本身与第一砂轮同侧。方向随后通过模板旋转/镜像参数得到真实
坐标向量，逻辑方向和屏幕显示方向不得混用。`first_wheel_side` 必须与机台
`wheel_positions` 的第一项一致，否则禁止 release。

## 产品规格

公司瓦型成品规格为：

```text
R外弧 * R内弧 * 弦宽 * 长度 * 成品厚度
```

示例：

```text
R16*R14.3*5.00(-0.02/-0.04)*14*1.7
```

解析为：

- `R_outer_finished = 16.00`
- `R_inner_finished = 14.30`
- `nominal_chord_width = 5.00`
- `preform_upper_tol = -0.02`
- `preform_lower_tol = -0.04`
- `product_length = 14.00`
- `finished_thickness = 1.70`

弦宽表示左右端点之间的直线距离，不是弧长。

当五段规格直接描述同 R 成型磨前产品时，第五项厚度允许带上下公差：

```text
R30*R30*17.4(+0/-0.02)*23.5*3.95(+0.02/-0.02)
```

此时 `preform_thickness_mid = 3.95 + (0.02 - 0.02) / 2 = 3.95 mm`，导轨上下型腔均使用 `R30`。

公司馒头形/面包形成品规格为四段：

```text
R * 长度 * 宽度 * 成品厚度
```

例如 `R40.75*30*22*3.3` 必须解析为单 R 馒头形产品：

- `finished_shape = bread`
- `R_finished = 40.75`
- `length = 30`
- `width = 22`
- `finished_thickness = 3.3`

禁止按 `R外弧 * R内弧 * 宽度 * 长度 * 厚度` 解释四段规格，也禁止通过 `R - thickness` 补造第二个半径。

- `preform_shape = concentric_r` 且没有独立 `preform_spec` 时，成品规格中的弦宽必须同时带成型磨前宽度上下公差。
- `preform_shape = block` 且已提供独立 `preform_spec` 时，槽宽和公差取方块成型磨前规格，成品弦宽不承担成型磨前宽度输入职责。

## 同心 R 成型磨

当 `preform_shape = concentric_r` 时，成品可以是异 R，但成型磨前轮廓按同心 R 处理：

```text
R_form = max(R_outer_finished, R_inner_finished)
```

该工艺的导轨槽口上下圆弧均使用 `R_form`。此规则不得套用于 `preform_shape = block` 的方块磨瓦工艺。

## 导轨厚度

导轨厚度不应默认等于成品厚度。应先确定成型磨前厚度中值：

```text
preform_thickness_mid = preform_thickness + (upper_tol + lower_tol) / 2
guide_thickness = preform_thickness_mid + thickness_clearance_mid
```

只有在未单独提供成型磨前厚度、且对应工艺规则明确允许时，才可使用成品厚度派生默认值；这属于工艺缺省计算，不应表述为“用户覆盖导轨厚度”。

厚度间隙中间值按 `QG 38012《成型磨导轨设计方法》5.2`：

- 成型磨前为方块产品：`thickness_clearance_mid = 0.12 mm`
- 方块磨单边或要求特别高：`thickness_clearance_mid = 0.09 mm`
- 成型磨前为小瓦产品：`thickness_clearance_mid = 0.18 mm`
- 成型磨前为相对大瓦产品：`thickness_clearance_mid = 0.25 mm`
- 大瓦片定义：瓦片宽度 `> 15 mm`

磨单边定义：两个砂轮在同一边，例如 `wheel_positions = ["上", "上"]`。当前 `double_head_up_up` 与 `triple_single_up_up` 对方块产品默认使用 `0.09 mm` 厚度间隙；不得同步到上下砂轮模板。三头机双导轨（下上上）为方块磨瓦片专用模板，也使用配置文件中的 `block_thickness_clearance_mid = 0.09`。

同心 R 小瓦示例：

```text
preform_thickness_mid = 1.65
guide_thickness = 1.65 + 0.18 = 1.83
```

方块磨瓦示例：

```text
finished_shape = tile
preform_shape = block
preform_thickness = 1.96(+0.01/-0.01)
preform_thickness_mid = 1.96
guide_thickness = 1.96 + 0.12 = 2.08
guide_profile = first_wheel_side_R(max(R_outer_finished, R_inner_finished)) + opposite_plane
```

方块磨馒头形示例：

```text
finished_spec = R40.75*30*22*3.3
preform_spec = 30*22(-0.10/-0.12)*3.35(+0.01/-0.01)
process_type = block_to_bread_rectangular
guide_profile = rectangular_pre_grinding_envelope
guide_thickness = 3.35 + 0.12 = 3.47
```

## 槽口和避空

导轨槽宽按 `docs/slot_width_rules.md` 执行。默认避空为 `4-1`：

- `relief_count = 4`
- `relief_size = 1.0`
- CAD 标注为 `4-r0.5`

用户输入 `4-0.6` 时应覆盖为四处 0.6 mm 避空，标注为 `4-r0.3`。

`triple_single_down_up` 不得把避空简化为四个槽口圆角。该机型以归档标准 CAD 为准，截面局部拓扑必须包含：

- `4-1`：槽左右两侧上下共四处局部过渡；默认半径为 `R0.5`，其侧边位置随真实槽宽变化。
- `2-0.5`：中心上口左右两处固定 `R0.5` 局部过渡；位置由 `section_center_opening + R0.5` 和相邻型面切线决定，不得由 `slot_width` 拉伸。
- `block_to_tile` 中，主 R 面位于第一砂轮侧；中心两处 R0.5 按机台模板的
  固定上口和平面拓扑生成。
- `block_to_bread_rectangular` 中不生成成品主 R，中心两处固定 R0.5 与矩形
  槽上口连接。
- 用户把四处避空改为 `4-0.6` 时，只改变 `4-*` 四处，中心 `2-0.5` 仍保持 R0.5。
- release 必须检测六个角色完整存在，否则禁止输出。

## 几何生成

1. 槽口所有控制点必须由参数计算。
2. 旧模板槽口必须删除后重建。
3. 相邻端点误差必须小于 0.001 mm。
4. 标注必须绑定真实几何或真实定义点。
5. release 图层不得包含 debug、参考轮廓或公式说明。

## 三头机双导轨下上上下砂轮缺口

`triple_double_down_up_up` 的标准模板文件名和旧标注中的 `R23.57` 只代表历史产品规格，不是机台固定导轨规则。生成时必须删除模板旧槽口和旧 `R23.57` 标注，按当前产品类型重建槽口：方块产品按方块槽规则，瓦型产品按产品规格计算 `R_form`。

该机型继承三头机单导轨（下上）的上下砂轮安全规则：

- `natural_cut_in_depth = product_thickness * 0.6`
- `opening_limit = product_length - 0.2`
- `lower_cavity_notch_opening = min(natural_opening, opening_limit)`
- `upper_cavity_notch_opening = min(upper_natural_opening, opening_limit)`
- 若任一自然缺口开口不小于产品长度，必须移动对应 R80 圆心，使该开口小于产品长度
- release 校验必须检查上下开口均不大于 `product_length - 0.2`
- report 必须输出两侧的自然切入深度、开口限制、实际开口和有效切入深度
