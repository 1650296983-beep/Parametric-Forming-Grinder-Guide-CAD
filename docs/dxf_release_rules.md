# DXF Release 规则

release DXF 是给厂家加工的正式图纸。任何校验失败时都不得输出或保留正式图纸。

显式双规格任务的正式文件名固定为 `成品规格（磨前规格）机台类型.dxf`，
且不包含规格公差。公差仍必须保留在输入、DXF 尺寸和校验报告中。为兼容
macOS 和 Windows 文件系统，规格内的 `*` 输出为 `×`。例如：
`R20.15×7×41×1.65（41×7×1.7）双头机（上下）.dxf`。

## 输出流程

正式 release 必须通过候选文件晋级：

1. 写入以正式文件名为基准、附带“调试”标识的 DXF；
2. 写入附带“正式候选”标识的候选 DXF；
3. 渲染同名 PNG 预览；
4. 检查候选 DXF；
5. 写入 `report.json`；
6. 全部检查通过后，将候选文件晋级为正式文件名；
7. 任一检查失败时删除候选文件，不生成正式 release。

## release 允许图层

release 模式允许：

- `FIXED_TEMPLATE`
- `SECTION_CENTER`
- `PARAM_SLOT`
- `DIMENSION`
- `TEXT_NOTE`
- `SIDE_TEMPLATE`
- `SIDE_DERIVED`
- `SIDE_DERIVED_RELEASE`
- `SIDE_CAVITY`
- `SIDE_DIMENSION`
- `SIDE_CENTER`

release 模式禁止：

- `DEBUG_CONTROL`
- `DEBUG_POINTS`
- `SIDE_DEBUG`
- `DIMENSION_TEXT_FALLBACK`
- `REFERENCE_PROFILE`
- 公式说明文字
- 旧规格槽口残留

## 模板使用

模板中的固定图框、标题栏、固定线、固定 R80 砂轮侧投影等可以保留。模板中的旧槽口、旧槽口尺寸、旧规格 R 或旧产品槽宽必须删除并由当前参数重新生成。

## 画图规范

通用图层规范：

- 截面图中心线必须使用红色点画线：`SECTION_CENTER`，颜色 `1`，线型 `CENTER`。
- 侧面投影图中心线必须使用红色点画线：`SIDE_CENTER`，颜色 `1`，线型 `CENTER`。
- 既有单导轨机型按各自模板规则使用 `SIDE_DERIVED`。
- 双导轨机型的机台外轮廓必须使用 `SIDE_TEMPLATE`，颜色 `7`，线型 `Continuous`；型腔投影线必须使用 `SIDE_CAVITY`，颜色 `3`，线型 `DASHED`。
- `SIDE_CAVITY` 中禁止存在端点完全相同的重复线；618 与双头机（上下）的型腔虚线禁止穿过 R80 砂轮弧。
- R80 半径尺寸必须定义到真实弧顶；吃入量和关键高度尺寸必须使用与弧顶同 X 的真实几何基准点。
- 该双导轨机型的隐藏辅助线和 debug 线使用 `SIDE_DEBUG`，线型 `DASHED`，不得作为正式 release 轮廓。

这些规范来自干净模板，适用于所有机型模板；复制模板时不得把中心线或内部槽线压成普通实线层。

## 尺寸规则

关键尺寸必须同时满足：

- 显示文字正确；
- DXF DIMENSION 定义点或实际测量值正确；
- 几何实测值正确。
- DIMENSION 定义点到对应真实几何的误差不大于 `0.01 mm`。

不得只改文字。

`triple_double_down_up_up` 每次生成必须写出 `dimension_definition_point_audit.json`，覆盖槽宽、R_form、导轨厚度、上下砂轮关键尺寸、下砂轮缺口开口以及 `590/99/90/180/131` 固定尺寸。任一角色缺失或未绑定真实几何时，不得晋级 `release.dxf`。
