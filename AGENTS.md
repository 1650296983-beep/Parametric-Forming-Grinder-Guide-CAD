# AGENTS.md

本项目是“成型磨导轨 CAD 参数化生成器”。目标不是自然语言任意 CAD，而是基于公司工艺规则、产品规格、公差和机台模板，稳定生成可加工的导轨 DXF 图纸。

成品形态与成型磨前形态必须独立建模：成品可为瓦型、面包型等，成型磨前产品可为同心 R、方块等。不得只根据成品形态推断导轨型腔；槽宽、导轨厚度、型腔轮廓和砂轮吃进量应由成型磨前形态、成型磨前尺寸及机台配置共同确定。

## 项目主线

1. 使用 Python + ezdxf。
2. 产品规格、工艺参数、机台差异、模板路径全部由代码和配置驱动。
3. 模板 DXF 只能用于图框、标题栏、图层、字体、固定说明和固定机台结构。
4. 产品轮廓、导轨槽口、侧面派生几何和关键标注必须通过参数化几何重新生成。
5. 所有尺寸单位均为 mm。

## 禁止事项

1. 禁止只修改尺寸文字而不修改真实几何。
2. 禁止 release 图中残留旧规格槽口。
3. 禁止把旧模板中的参数化槽口当作固定图元保留。
4. 禁止通过拉伸、缩放或改模板旧线段长度生成新槽口。
5. 禁止把成品异 R 轮廓直接用于成型磨导轨设计。
6. 禁止在机台分支里重复硬编码产品计算逻辑。
7. 禁止让 debug points、control lines、formula text、REFERENCE_PROFILE 出现在 release 输出中。
8. 禁止在校验失败时输出或保留正式 release.dxf。

## 必须满足

1. release 图纸必须通过几何校验和 DXF 检查。
2. 机台差异必须通过 `templates/<machine_id>/config.yaml` 管理。
3. 产品计算逻辑应在规格解析、几何计算和校验模块中统一实现，不得按机台复制。
4. 尺寸显示值、尺寸定义点、几何实测值必须一致。
5. 相邻图元端点距离误差不得大于 0.001 mm。
6. 闭合轮廓必须严格闭合。
7. 所有规则变更必须同步更新 `docs/` 和 `tests/`。
8. 修改几何计算逻辑后必须运行 tests；测试失败时不得继续生成正式图纸。

## 生成工作流

每次生成必须按以下顺序执行：

1. `read_config`
2. `parse_product_spec`
3. `derive_process_parameters`
4. `load_machine_template`
5. `remove_old_parametric_geometry`
6. `rebuild_parametric_slot`
7. `rebuild_dimensions`
8. `generate_debug_dxf`
9. `generate_release_dxf_candidate`
10. `render_preview_png`
11. `run_validation`
12. `write_report_json`
13. `promote_release_dxf_after_validation`

正式 `release.dxf` 只能由通过校验的 release 候选文件晋级生成。

## 输出要求

每次生成至少输出：

- `debug.dxf`
- `release.dxf`
- `preview.png`
- `report.json`
- `dimension_definition_point_audit.json`

`report.json` 必须包含机台信息、产品规格解析、槽宽计算、R_form 计算、导轨厚度计算、侧面派生尺寸、固定模板尺寸、图层检查、旧图元残留检查、尺寸一致性检查和 release 是否允许输出。

## 通用画图规范

1. 截面图中心线必须为红色点画线：`SECTION_CENTER`，颜色 `1`，线型 `CENTER`。
2. 侧面投影图中心线必须为红色点画线：`SIDE_CENTER`，颜色 `1`，线型 `CENTER`。
3. 既有单导轨机型继续按各自模板规则使用 `SIDE_DERIVED`；机型专用例外必须写入对应 config、docs 和 tests。
4. 双导轨机型的机台外轮廓必须放在 `SIDE_TEMPLATE`，颜色 `7`，线型 `Continuous`；导轨型腔投影线必须放在 `SIDE_CAVITY`，颜色 `3`，线型 `DASHED`。隐藏辅助线或 debug 线放在 `SIDE_DEBUG`，线型 `DASHED`。
5. 所有机台的侧视型腔投影线数量只由成型磨前形状决定：方块 `2` 条、面包型 `3` 条、瓦型 `4` 条；成品形状不得参与判断。
6. 所有机台及所有磨前形状的砂轮目标吃入量统一为 `preform_thickness_mid * 0.6`；若自然开口大于 `product_length * 0.6`，必须移动砂轮圆心限制开口，机台配置不得覆盖该公共规则。
7. 厚度间隙默认按磨前形状统一计算；仅当输入显式勾选“磨单边/高要求”时使用 `0.09 mm`，不得根据机台砂轮排列自动推断。
8. 砂轮半径为任务级显式参数，默认 `R80`；砂轮身份必须由机台位置角色识别，不得依赖半径值识别。
9. 截面槽口统一使用四处可调避空圆弧和中心固定 `2-R0.50` 六圆弧拓扑；所有正式尺寸文字统一保留小数点后两位。

## 三头机双导轨（下上上）

1. `triple_double_down_up_up` 必须复用 `DualGuideTemplateEngine`，不得重新开发双导轨逻辑。
2. 机型固定为 `guide_length = 590`、`guide_sections = 2`、`dual_section_mode = synchronized`、`wheel_positions = ["下", "上", "上"]`。
3. 标准模板为 `6）R23.57XR21.53X6.56X13.73X2.04（R23.57X6.6X2.4)三机头双导轨砂轮下、上、上.dxf`；项目内 `templates/triple_double_down_up_up/full_template.dxf` 必须与该模板一致。
4. 标准模板文件名中的 `R23.57` 只是该模板历史产品规格，不是机台永久固定导轨规则；不得强制要求 release 中出现 `R23.57`。
5. 输入必须显式区分 `finished_product_spec`、`pre_grinding_spec`、`finished_product_shape`、`pre_grinding_shape`、`guide_profile_source`，禁止仅凭规格字符串是否出现 `R*R` 判断 `same_r_tile`。
6. 成品为馒头状/单 R 且成型磨前为方块时，导轨按成型磨前方块规格生成。
7. 成品为瓦型/双 R 且成型磨前为方块时，导轨截面生成一平一弧，`R_form = max(成品两个 R)`；R 面必须与第一砂轮同侧，平面和圆心位于对侧。该方向规则适用于所有机台。
8. 同 R 成型磨前瓦型仅在 `pre_grinding_shape = same_r_tile` 且 `guide_profile_source = pre_grinding_spec` 时生成上下同 R 型腔。
9. `section_1` 和 `section_2` 必须同步更新 `slot_width`、`guide_thickness`、`relief` 和截面生成参数，禁止左右导轨出现不同参数。
10. 下砂轮 R80 侧面缺口必须按三头机单导轨（下上）规则控制，料腔内部缺口开口不得大于 `product_length * 0.6`。
11. release 必须通过所有 DIMENSION 定义点审计，`point_error <= 0.01 mm`；任一尺寸未绑定真实几何时禁止 release。

## 三头机单导轨（下上）方块成型磨前

1. `triple_single_down_up` 输入必须同时包含成品规格和成型磨前方块规格。
2. 五段瓦型规格走 `block_to_tile`：导轨 R 面必须与第一砂轮同侧，另一面为平面，R 取成品两个 R 中的较大值；例如砂轮顺序“下、上”时必须为“下 R、上平面”。该方向规则适用于所有机台。
3. 四段馒头形规格 `R*长度*宽度*厚度` 且成型磨前为方块时走 `block_to_bread_rectangular`：导轨截面按磨前方块生成矩形槽；成品单 R 只作为磨后目标轮廓，不得写入导轨截面，也不得按厚度补造第二个 R。
4. 槽宽按成型磨前方块宽度及其上下公差计算。
5. 导轨厚度按 `成型磨前方块厚度中值 + 0.12` 计算。
6. 截面上口固定开口为 `2.0 mm`，型腔下沿固定高度为 `12.0 mm`。
7. 上下砂轮吃进量均以成型磨前方块厚度中值为基准，按 `preform_block_thickness_mid * 0.6` 计算。
8. 下砂轮料腔内部缺口仍必须满足 `lower_cavity_notch_opening <= product_length * 0.6`。
9. release 必须包含五个参数化尺寸角色：上口、下砂轮缺口开口、下砂轮关键高度、上砂轮关键高度、上砂轮局部吃刀深度；任一缺失或与最终几何不一致时禁止 release。
10. 成型磨前方块厚度仅用于导轨厚度与砂轮吃进量计算，不在 release 图纸中单独标注。
11. 截面避空必须按归档标准 CAD 的 `4-1 + 2-0.5` 六圆弧拓扑生成：四处侧部过渡由槽边和当前型面决定，中心两处固定 R0.5 由 `section_center_opening` 和相邻上平面决定，不得只生成随槽宽外移的四个槽角。
12. `block_to_tile` 的主 R 面跟随第一砂轮侧；`block_to_bread_rectangular` 不生成主 R。两者中心两处 R0.5 均不得随槽宽外移。
13. 成型磨前为同 R 瓦型时，允许直接输入 `R*R*弦宽公差*长度*厚度公差`；导轨上下型腔均取该同 R，厚度按成型磨前厚度中值计算。

## 核心规则文档

- 导轨槽宽和间隙规则以 `QG 38012《成型磨导轨设计方法》` 和 `docs/slot_width_rules.md` 为准；槽宽输入必须带上下公差。
- 多机型、多导轨类型的结构参数必须沉淀到 `templates/<machine_id>/config.yaml`，不得只写在 agent 对话或代码分支里。
- `docs/guide_rail_rules.md`
- `docs/slot_width_rules.md`
- `docs/machine_templates.md`
- `docs/dxf_release_rules.md`
- `docs/validation_rules.md`
- `docs/side_view_rules.md`
- `docs/text_to_cad_reference.md`
