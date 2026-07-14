# 校验规则

校验分为几何校验、DXF 检查、机台配置检查、尺寸一致性检查和报告完整性检查。

## 几何校验

1. 相邻图元端点距离误差必须小于 0.001 mm。
2. 闭合轮廓必须严格闭合。
3. forming profile 内外 R 必须相等，且均为 `R_form`。
4. 弦宽实测必须等于对应参数。
5. 导轨厚度实测必须等于 `preform_thickness_mid + thickness_clearance_mid`，其中厚度间隙中间值按成型磨前产品类型取 `0.12/0.18/0.25 mm`，特殊高要求可显式覆盖。
6. 五段同 R 成型磨前规格若带第五项厚度公差，`preform_thickness_mid` 必须使用厚度上下公差平均值计算。

## 槽宽校验

槽宽输入必须带上下公差，不能再用无公差槽宽沿用历史规则。

```text
preform_width_max = nominal_chord_width + preform_upper_tol
preform_width_min = nominal_chord_width + preform_lower_tol
preform_width_tolerance_range = preform_width_max - preform_width_min
slot_clearance_mid = 0.04 if preform_width_tolerance_range <= 0.02
slot_clearance_mid = 0.05 if preform_width_tolerance_range > 0.02
slot_width_raw = nominal_chord_width + (preform_upper_tol + preform_lower_tol) / 2 + slot_clearance_mid
slot_width = slot_width_raw rounded half-up to 0.01 mm
```

机台最小精度为 0.01 mm。对称度要求特别高可显式覆盖为 `0.03 mm`；大瓦片可显式覆盖为 `0.08 mm`。

## 侧面尺寸校验

```text
side_projected_slot_height = slot_base_height + side_cut_in_allowance
side_clearance_height = guide_outer_height - slot_base_height - guide_thickness + wheel_cut_allowance
```

默认：

- `side_cut_in_allowance = 0.50`
- `wheel_cut_allowance = 0.20`

## 旧图元残留校验

release 中不得残留旧规格参数化槽口图元。检查对象包括：

- 固定模板层中位于槽口工作区的旧槽口圆弧；
- 固定模板层中位于槽口工作区的旧槽口线段；
- 旧规格尺寸文本；
- debug/reference 图层。

## 尺寸一致性校验

关键尺寸：

- `R_form`
- `slot_width`
- `guide_thickness`
- `side_projected_slot_height`
- `side_clearance_height`

每个关键尺寸必须检查：

- 显示文字；
- DIMENSION 定义点或 `actual_measurement`；
- 几何实测值。

三者误差不得超过 0.001 mm。带公差槽宽必须先按标准文件公式计算原始值，再按 0.01 mm 机台精度输出，例如 `4.50(-0.02/-0.05)` 输出 `4.52±0.01`。

## 双规格自检

显式双规格输入的 `report.json` 必须包含 `dual_spec_validation`，且以下
检查全部通过后才允许晋级 release：

1. 磨前规格与成品规格独立存在；
2. 槽宽名义值和上下公差来自磨前规格；
3. 导轨基础厚度来自磨前厚度中值；
4. 需要导轨主 R 时该 R 来自成品规格；单 R 矩形槽仍须在报告中保留成品目标 R；
5. 单 R 面包型成品且磨前为方块时，导轨生成矩形槽，不得把成品 R 写入导轨截面；
6. 双 R 成品且磨前为方块时，导轨 R 面必须与第一砂轮同侧，圆心和平面在对侧；
7. 双 R 保持瓦型分类，不被标为面包型；
8. 弧面圆心侧与第一砂轮侧相反；
9. 模板旋转/镜像后的方向向量仍互为反向；
10. 成品宽度不得覆盖磨前宽度；
11. 不得存在未解决 warning。

模板直径标注必须按直径两端点和真实圆心审计。`4-∅1.00` 的几何半径
为 0.50 mm；不得把直径 DIMENSION 的一个端点误当圆心。

`triple_double_down_up_up` 还必须审计 release 中全部 DIMENSION 的定义点，并输出 `dimension_definition_point_audit.json`。每项必须包含 `dimension_role`、`measurement`、`display_text`、`defpoint2`、`defpoint3`、两个预期几何点、`point_error` 和 `bound_to_geometry`；`point_error > 0.01 mm` 时禁止 release。

双导轨机型的 `release_allowed = true` 必须同时满足：显式输入规则正确、机台外轮廓为白色 Continuous、型腔投影线为绿色 DASHED、全部尺寸定义点绑定真实几何、上下砂轮缺口安全规则通过、双导轨两节参数同步。

所有方块磨前机型的砂轮目标吃入量为 `preform_block_thickness_mid * 0.6`。若由此得到的 R80 自然开口大于 `product_length - 0.2`，校验必须确认生成器通过移动圆心限制开口，并使报告值、圆心、圆弧端点和相关 DIMENSION 定义点一致。

618 和双头机（上下）必须校验两条型腔边界都在相应砂轮开口内断开；双头机（上下）还必须校验侧视图只有两个型腔高度，不得出现四线重影。双导轨机型必须拒绝端点完全相同的重复 `SIDE_CAVITY` 线，并分别审计 R80 半径标注的目标点、吃入量和关键高度标注的弧顶定义点及同 X 基准点。

## report.json

`report.json` 中的 `release_allowed` 只有在所有检查通过时才允许为 `true`。正式 `release.dxf` 只能在 `release_allowed = true` 后生成。
## 三头机下上方块磨瓦尺寸链

`triple_single_down_up` 的瓦型/馒头型参数化 release 必须包含以下带持久化角色标识的参数化 `DIMENSION`：

- `section_center_opening`
- `lower_wheel_notch_opening`
- `lower_wheel_key_process_height`
- `upper_wheel_key_process_height`
- `upper_wheel_local_cut_in_depth`

每个角色必须且只能出现一次，并同时满足：

1. `DIMENSION.get_measurement()` 与最终几何计算值误差不大于 `0.001 mm`。
2. 显示文字与当前参数格式化结果一致。
3. 定义点绑定最终槽口、外框或安全调整后的 R80 圆弧几何。
4. report 中输出 `expected_value`、`actual_dimension_measurement`、`display_text`、`definition_points`、`bound_to_geometry` 和 `status`。

任一角色缺失、重复、测量不一致或未绑定几何时，禁止 release。三头机单导轨（下上）截面顶部开口实际为 `2.0 mm`，若仍存在旧 `4.0 mm` 上口尺寸，同样禁止 release。

成型磨前方块厚度仍作为导轨厚度和砂轮吃进量计算参数，但不在 release 图纸中单独标注。
