# 机台模板配置

机台差异必须通过 `templates/<machine_id>/config.yaml` 管理。产品规格解析、R_form、槽宽、导轨厚度等产品计算逻辑不得按机台重复硬编码。

## 配置字段

每台机台至少包含：

- `machine_id`
- `machine_name`
- `guide_length`
- `wheel_positions`
- `guide_sections`
- `side_fixed_spans`
- `section_template`
- `side_template`
- `layout`

`side_fixed_spans` 的总和必须等于 `guide_length`。

## 机台清单

| machine_id | machine_name | guide_length | wheel_positions | guide_sections |
| --- | --- | ---: | --- | ---: |
| `bed_618` | 618磨床 | 300 | `["上"]` | 1 |
| `double_head_up_down` | 双头机（上下） | 435 | `["上", "下"]` | 1 |
| `double_head_up_up` | 双头机（上上） | 435 | `["上", "上"]` | 1 |
| `triple_single_down_up` | 三头机单导轨（下上） | 379 | `["下", "上"]` | 1 |
| `triple_single_up_up` | 三头机单导轨（上上） | 379 | `["上", "上"]` | 1 |
| `triple_double_down_up_up` | 三头机双导轨（下、上、上） | 590 | `["下", "上", "上"]` | 2 |
| `triple_double_up_up_up` | 三头机双导轨（上、上、上） | 590 | `["上", "上", "上"]` | 2 |

当前已接入 release 验证的机台以 `templates/` 下真实存在的 `config.yaml` 和 DXF 模板为准。新增机台时必须先放入干净模板，再启用 release 输出。

618磨床使用独立模板：

- `guide_length = 300.0`
- `side_fixed_spans = [170.0, 130.0]`
- `wheel_positions = ["上"]`
- 单导轨，单上砂轮
- 截面外宽 `section_outer_width = 40.0`
- 截面上口固定开口 `section_center_opening = 2.0`
- 导轨型腔下沿高度 `section_slot_base_height = 20.9` 为固定数值
- 侧面投影保留面端 `R15` 上料缺口和一个上砂轮 `R80` 缺口
- 618机型为磨较小产品，退刀槽按 `D0.5` 方式；默认避空仍按项目通用 `4-1`
- 侧面投影中型腔下沿按固定 `20.9` 输出，不套用普通瓦型的 `slot_base_height + 0.50`
- 侧面型腔投影线使用绿色虚线；上砂轮吃入按成型磨前厚度中值的 `0.6` 倍计算

双头机（上下）的方块磨前侧视图只保留型腔上下两条绿色虚线；每条虚线在对应 R80 砂轮处断开，不得复制为带偏移的重影线。上下 R80 均按成型磨前厚度中值的 `0.6` 倍吃入，圆心和两条型腔边界随当前导轨厚度同步更新。

三头机单导轨（上上）使用独立模板：

- `guide_length = 379.0`
- `side_fixed_spans = [99.0, 180.0, 100.0]`
- `wheel_positions = ["上", "上"]`
- 方块截面外宽 `block_outer_width = 40.0`
- 方块截面上口余量 `block_fixed_top_gap = 3.0` 固定；槽底高度随导轨厚度变化
- 两个砂轮同在上侧，属于磨单边；方块厚度间隙默认 `block_thickness_clearance_mid = 0.09`

三头机单导轨（下上）使用独立模板：

- `guide_length = 379.0`
- `side_fixed_spans = [99.0, 180.0, 100.0]`
- `wheel_positions = ["下", "上"]`
- 截面外宽 `section_outer_width = 40.0`
- 该机型支持“瓦型成品 + 方块成型磨前产品”和“馒头形成品 + 方块成型磨前产品”；输入必须同时包含成品规格和成型磨前方块规格
- 截面上口固定开口 `section_center_opening = 2.0`
- 型腔下沿高度 `section_slot_base_height = 12.0`
- 五段瓦型规格走 `block_to_tile`：R 面与第一砂轮同侧，另一面为平面，R 取成品两个 R 中的较大值；本机第一砂轮在下，因此为下 R、上平面
- 四段馒头形规格 `R*长度*宽度*厚度` 且磨前为方块时走 `block_to_bread_rectangular`：截面按磨前方块生成矩形槽；成品单 R 不进入导轨截面
- 模板类型仍为 `triple_single_down_up_flat_arc`，具体上下表面由工艺分支参数化重建
- 槽宽按成型磨前方块宽度及宽度公差计算
- 导轨厚度按 `成型磨前方块厚度中值 + 0.12` 计算
- 侧面投影为下上专用规则：`12.0` 为固定型腔下沿；上下砂轮 R80 均按 `成型磨前方块厚度中值 * 0.6` 吃进型腔，下砂轮料腔内部投影线缺口开口还必须小于产品长度
- 上砂轮吃进比例由 `layout.tile_upper_wheel_cut_in_ratio = 0.6` 配置，R80 圆弧、型腔槽顶线断口和 R80 半径标注必须同步更新
- 生成时删除旧槽口后按当前工艺重建同 R 双圆弧槽口、第一砂轮同侧的大 R 槽口或单 R 成品对应的矩形槽，并更新模板原有 `DIMENSION` 标注及真实定义点
- 截面避空拓扑必须继承归档标准图的 `4-1 + 2-0.5`：四处侧部过渡加两处中心上口固定 R0.5 过渡，不得只生成随槽宽外移的四个槽角
- `block_to_tile` 与 `block_to_bread_rectangular` 的中心两处 R0.5 的 X 位置只由 `section_center_opening` 与固定 R0.5 决定，不得随槽宽变化
- 方块磨前的侧视图必须使用该机台 `config.yaml` 的 `block_side_mode`；禁止依赖跨机型默认投影高度。三头机单导轨（下上）的方块单 R 分支固定以 `section_slot_base_height = 12.0` 为槽底基准。
- release 必须包含五个参数化尺寸角色：`section_center_opening`、`lower_wheel_notch_opening`、`lower_wheel_key_process_height`、`upper_wheel_key_process_height`、`upper_wheel_local_cut_in_depth`
- 五个尺寸必须按当前最终几何重算，不得照抄标准样本中的 `13.8`、`12.6`、`13.5`、`1.26`
- 成型磨前方块厚度只作为工艺计算输入，不在 release 中单独标注

双头机（上上）同样属于磨单边，方块厚度间隙默认 `block_thickness_clearance_mid = 0.09`。该规则只适用于两个砂轮在同一边的上上模板，不得同步到上下砂轮模板。侧面型腔投影线必须继承绿色 `3` 和 `DASHED`，不得保留模板图元的显式青色。

三头机双导轨完整图纸中包含两套局部导轨节和一套 590 mm 合并投影视图：
三头机双导轨使用 `DualGuideTemplateEngine` 生成，`dual_section_mode = synchronized`，不得在两节导轨之间使用不同的产品参数或截面参数。

- `triple_double_down_up_up` 使用 `guide_length = 590.0`，`wheel_positions = ["下", "上", "上"]`，`guide_sections = 2`
- `triple_double_down_up_up` 支持 `rectangular_block`、`bread_big_r_block_preform` 和 `same_r_tile` 三种截面。
- `triple_double_up_up_up` 使用 `guide_length = 590.0`，`wheel_positions = ["上", "上", "上"]`，`guide_sections = 2`
- 两种双导轨机型的外轮廓均为白色实线，型腔投影线均为绿色虚线
- `triple_double_up_up_up` 的 R80 圆弧端点必须连接外轮廓，冠点按有效吃入量进入型腔，不得把型腔虚线误作圆弧端点
- 两种双导轨机型的 R80 半径标注必须以圆心和真实弧顶为定义点；关键高度与吃入量标注必须以真实弧顶和同 X 基准点为定义点
- 双导轨侧视图不得保留端点完全相同的重复 `SIDE_CAVITY` 线
- 590 mm 合并固定分段为 `99 + 90 + 90 + 180 + 131`
- `section_1` 局部分段为 `99 + 90 = 189`
- `section_2` 局部分段为 `90 + 180 + 131 = 401`
- 当前阶段 `dual_product_mode = false`；同一机台同一张双导轨图纸中，`section_1` 和 `section_2` 必须复用同一套产品参数，包括 `R_form`、`slot_width`、`guide_thickness` 和 `relief`
- 两个导轨节的截面中心线间距作为固定模板参数写入 `guide_section_spacing`

三头机双导轨（下上上）使用 `6）R23.57XR21.53X6.56X13.73X2.04（R23.57X6.6X2.4)三机头双导轨砂轮下、上、上.dxf` 作为标准干净模板。项目内 `templates/triple_double_down_up_up/full_template.dxf` 必须与该模板一致。文件名和旧模板标注中的 `R23.57` 只是该模板历史产品规格，不是机台永久固定参数，release 不得强制保留或生成 `R23.57`。

输入必须显式提供 `finished_product_spec`、`pre_grinding_spec`、`finished_product_shape`、`pre_grinding_shape` 和 `guide_profile_source`，不得按规格字符串中的 R 数量推断工艺。馒头状成品加方块成型磨前走矩形槽；瓦型成品加方块成型磨前走第一砂轮同侧的大 R、对侧平面；同 R 型腔仅由显式 `same_r_tile` 输入触发。

规范字段现为 `finished_spec`、`pre_grinding_spec`、
`product_shape_after`、`product_shape_before`；上一段旧字段继续兼容。
`guide_profile_source` 由集中式槽型决策生成，不再要求新调用方手工填写。

`triple_single_down_up/config.yaml` 必须显式包含：

```yaml
block_to_tile_groove_profile: flat_arc_groove
block_to_bread_groove_profile: rectangular_groove
flat_arc_surface_side: lower
flat_surface_side: upper
flat_arc_center_side: upper
```

这些字段记录该模板的方块磨双 R 方向和单 R 矩形槽规则。所有机台均执行
“双 R 的 R 面跟随第一砂轮、单 R 面包成品加方块磨前使用矩形槽”；机台
配置负责模板坐标、固定尺寸和局部拓扑。

`section_1` 与 `section_2` 必须同步更新 `slot_width`、`guide_thickness`、`relief` 和当前产品对应的截面生成参数。

上下砂轮 R80 侧面缺口均按三头机单导轨（下上）的规则处理：

- `natural_cut_in_depth = preform_thickness_mid * 0.6`
- `opening_limit = product_length - 0.2`
- `lower_cavity_notch_opening = min(natural_opening, opening_limit)`
- `upper_cavity_notch_opening = min(upper_natural_opening, opening_limit)`
- 若任一自然缺口开口不小于产品长度，必须移动对应 R80 圆心并同步更新连接线和尺寸标注
- release 校验必须检查上下开口均不大于 `product_length - 0.2`

## 目录结构

目标结构：

```text
templates/
  <machine_id>/
    section_template.dxf
    side_template.dxf
    config.yaml
```

禁止用其他机台模板冒充新机台模板。模板路径不存在时，校验必须失败。

## 校验要求

`report.json` 必须输出：

- machine 信息；
- guide length；
- wheel positions；
- guide sections；
- side fixed spans；
- section/side template 路径；
- 模板路径是否存在；
- fixed span 总和是否匹配 guide length。
