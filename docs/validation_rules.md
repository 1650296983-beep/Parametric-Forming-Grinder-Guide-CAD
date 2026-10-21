# 校验规则

校验分为几何校验、DXF 检查、机台配置检查、尺寸一致性检查和报告完整性检查。

## 矩形槽避空前置检查

参数计算阶段必须检查 `guide_thickness > relief_size`，以及
`slot_width > center_opening + max(2 * relief_size, 2 * 0.50 + relief_size)`。
前者和宽度第一项保留生成器已有必要条件；第二项确保槽顶平面有正长度，避免
侧部外避空与中心固定 R0.50 圆弧相交。`relief_size` 为四处侧部避空的直径，
中心固定 R0.50 保持不变。计算与画图调用同一检查函数；输入不满足时
返回中文 HTTP 422，说明当前槽宽、开口、避空直径/半径和限制值，不启动子进程，
不创建图纸任务或正式 DXF。检查通过后仍须执行完整几何和正式图校验。

开口先按 `min(slot_width * 0.30, machine.section_center_opening)` 向下取两位小数，
其中机台原固定开口值作为该机台上限保留。例如槽宽 3.03 mm、上限 2.00 mm 时，
实际开口为 0.90 mm；`4-1` 要求槽宽大于 2.90 mm，同时导轨厚度必须大于
1.00 mm。槽宽 2.53 mm 时，实际开口 0.75 mm，`4-1` 要求槽宽大于
2.75 mm，仍须在输入阶段拒绝。不得通过自动减小避空或修改槽宽绕过检查。
直接调用冻结生成器遇到同类参数错误时必须正常返回失败，不得触发
PyInstaller 未处理异常弹窗。不得因尺寸定义点审计通过而忽略圆弧相交。

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
side_clearance_height = guide_outer_height - slot_base_height - guide_thickness - upper_cavity_sagitta + wheel_cut_allowance
```

侧视型腔投影厚度必须独立对照截面真实导轨厚度。禁止使用同一个派生值同时
生成投影和校验投影，否则错误厚度会自洽地通过检查。

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

`R_form` 原生半径标注数量必须由最终成型磨前型腔拓扑决定，而不是由机台或成品 R 数量决定：矩形槽为 `0`，一平一弧为 `1`，上下同 R 型腔为 `2`。每个 `R_form` 标注的定义点必须绑定对应的真实主圆弧。模板 `DIMENSION` 只可复用样式和文字布局；复制前必须移除旧 `DIMASSOC` 关联，再以最终几何重新建立定义点，禁止继承模板历史关联。

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

方块磨前矩形槽的截面下沿高度标注，必须按其外框底边到槽底的几何关系识别，
不得只按模板文字 `18` 查找；模板中的尺寸文字允许为空。槽宽或槽底高度变化后，
型腔内的旧定义点必须重绑到当前槽底与侧部避空的真实切点，另一端绑定外框底角；
既有外框投影式标注保留外框竖边上的基准 X，并更新槽底高度 Y。
必须重新渲染标注块，使引出线、显示值、定义点和实测高度一致。上部间距标注同样
必须跟随当前槽顶更新，不得沿用历史 `6.85` 等尺寸的旧取点。

`triple_double_down_up_up` 还必须审计 release 中全部 DIMENSION 的定义点，并输出 `dimension_definition_point_audit.json`。每项必须包含 `dimension_role`、`measurement`、`display_text`、`defpoint2`、`defpoint3`、两个预期几何点、`point_error` 和 `bound_to_geometry`；`point_error > 0.01 mm` 时禁止 release。

模板中的小尺寸（导轨厚度、固定台阶）不得按“距新槽边固定 5 mm”识别。槽宽变化后该阈值会改变命中对象，未被选中的旧厚度尺寸会残留在 release 中（例如遗留 `2.10`）。识别顺序固定为：上端点落在当前槽顶、尺寸 X 位于当前槽宽内、距槽中心最近；不得以槽宽相关的距离作为首条件。

弧面槽底的机台固定型腔下沿（例如 `12.0 mm`）是到名义弦线的基准，不是弧面上的实体点。审计允许一个端点绑定真实几何、另一端点位于名义弦线，且该虚拟端点偏离弧面的距离不超过当前槽宽对应的弓高；其他尺寸仍须两端绑定真实几何。`R_form` 引出点必须落在侧部避空保留后的主弧范围内；窄槽小 R 时按 `asin(half_slot / R) - acos(1 - r² / (2R²))` 限制水平偏移，不得落在被避空切除的弧段上。

双导轨机型的 `release_allowed = true` 必须同时满足：显式输入规则正确、机台外轮廓为白色 Continuous、型腔投影线为绿色 DASHED、全部尺寸定义点绑定真实几何、上下砂轮缺口安全规则通过、双导轨两节参数同步。

所有机台及所有磨前形状的砂轮目标吃入量均为 `preform_thickness_mid * 0.6`。若由此得到的 R80 自然开口大于 `product_length * 0.6`，校验必须确认生成器通过移动圆心限制开口，并使报告值、圆心、圆弧端点和相关 DIMENSION 定义点一致；机台配置不得用固定吃入量覆盖该公共规则。

release 必须按最终 DXF 实体审计截面型腔：`PARAM_SLOT` 每一节只能形成一条连续腔体链，链内相邻端点误差不得大于 `0.001 mm`，两个腔口端点必须各自与重建后的 `FIXED_TEMPLATE` 顶边精确相接，且顶边不得跨过腔口。任一断点、分叉、重复桥接或节数不符都必须禁止 release。

截面型腔 `PARAM_SLOT` 的有效颜色必须为白色 `7`；截面中心线 `SECTION_CENTER` 必须为红色 `1`、线型 `CENTER`。样式审计失败时不得输出正式图。

侧视投影必须校验“磨前方块 `2` 条、磨前面包型 `3` 条、磨前瓦型 `4` 条”，不得使用成品形状决定线数。618 和双头机（上下）还必须校验对应型腔投影线在实际砂轮开口内断开；合法的弧端线与弧顶线不得作为重影删除。双导轨机型必须拒绝端点完全相同的重复 `SIDE_CAVITY` 实体，并分别审计 R80 半径标注的目标点、吃入量和关键高度标注的弧顶定义点及同 X 基准点。

所有 `block_to_tile` release 还必须审计截面避空拓扑：每一节导轨均应有
`4-1 + 2-R0.50` 六处避空圆弧；中心两处圆心 X 坐标只由中心开口和固定
R0.50 决定，不得随槽宽外移；主 R 的实际圆心必须位于 `arc_side` 的对侧，
并与对应的中心/侧部避空切点连续。该审计覆盖全部单导轨和双导轨机台，
防止上 R 的瓦型截面误走面包型构造分支。

四处 `4-*` 侧部避空另须通过外弧段审计：每段扫角大于 `180°`，左侧弧的
中点 X 必须在左槽边外、右侧弧的中点 X 必须在右槽边外。任一短内弧、扫角
反向或只有部分避空被修正时，禁止 release。双导轨的两节必须分别通过。

所有机台 release 均必须执行：参数图元重复审计、完整 DIMENSION 定义点审计、关键尺寸角色审计和两位小数显示审计。任一失败不得晋级正式 `release.dxf`。砂轮半径审计使用任务输入值，默认 `R80`。

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

任一角色缺失、重复、测量不一致或未绑定几何时，禁止 release。三头机单导轨（下上）截面顶部开口按 30% 比例计算、上限为 `2.0 mm`；标注必须与当前实际开口一致，若仍存在旧 `4.0 mm` 上口尺寸，同样禁止 release。

## 双导轨砂轮真实切入校验

两节局部视图及总装视图的每个砂轮按位置角色独立检查，不能只验证尺寸是否
绑定某段圆弧。`wheel_notch_geometry_audit` 必须记录当前型腔基准、目标与实测
吃入量、目标与实测缺口宽度、产品长度限制及外轮廓连接情况。下上上机型
上砂轮基准取当前最高型腔投影线；上砂轮关键高度由外框顶部至实际弧顶重算，
不得固定为模板的 12.70 mm。每个砂轮的深度、开口误差与外轮廓端点间距均
不得大于 0.001 mm；任一缺失、未切到型腔或超过限制时，禁止输出正式图纸。

成型磨前方块厚度仍作为导轨厚度和砂轮吃进量计算参数，但不在 release 图纸中单独标注。

## 上砂轮真实投影开口门禁

所有 7 种机台的上轮限宽以真实型腔最高投影层为基准，瓦型包含上弧顶矢高。
`cavity_projection.audit_wheel_projection_openings` 从最终 DXF 圆弧与每个投影高度
求真实交点，输出 `projection_levels`、逐层 `opening` 和 `within_limit`。
单导轨 `upper_wheel_notch_safety.projection_opening_audits` 与双导轨
`wheel_notch_geometry_audit.wheels[*].projection_opening_audit` 必须全部通过；
缺失砂轮、最高层无真实交点、最高层开口与报告不一致，或任一层开口超过
`product_length * 0.6` 均禁止 release。非控制内侧层无交点时记录 null，不视为缺陷。

跨机台回归覆盖 7 机台 × 3 磨前/成品路径 × 2 组长度及砂轮半径，并逐机注入
“只按上弧端点限宽”的旧缺陷，确认弧顶超限能被门禁拒绝。
