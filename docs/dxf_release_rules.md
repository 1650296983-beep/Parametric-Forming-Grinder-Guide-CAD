# DXF Release 规则

release DXF 是给厂家加工的正式图纸。任何校验失败时都不得输出或保留正式图纸。

Web 任务通过全部 release DXF 校验后，可额外生成 AutoCAD 2007/LT 2007
`*.dwg`。DWG 必须由 AutoCAD Core Console 从已晋级的 release DXF 转换，且
文件头必须为 `AC1021`；转换完成后必须由 AutoCAD Core Console 重新打开
DWG，审计模型空间实体数。转换用 DXF 与重开 DWG 的模型空间实体数必须
相等且大于零；禁止只修改扩展名、仅检查文件大小或仅检查文件头。
DWG 转换失败不改变 DXF 的校验结论，但必须在 `report.json.dwg_export` 中记录。
空白、实体丢失、无法重开或无法完成审计的 DWG 必须删除，且不得出现在前端
可保存文件列表中。

Core Console 的输入 DXF 必须与用户端 AutoCAD 版本兼容。AutoCAD 2014 只允许
读取到 AutoCAD 2013 DXF（`AC1027`）；当 release DXF 为 AutoCAD 2018 DXF
（`AC1032`）时，转换器必须先重建 `AC1027` 中间文件，再执行 `SAVEAS 2007`。
不得把 `AC1032` 直接交给 AutoCAD 2014，否则 AutoCAD 会丢弃输入图形，并可能
把默认空白数据库保存成看似合法的 `AC1021` DWG。

兼容重建时不得简单修改 `$ACADVER`。所有普通模型空间图元必须复制到对应旧版
DXF 文档；可见 `ACAD_PROXY_ENTITY` 必须展开成旧版可读取的原生图元。无法解析
或无法完整展开的可见代理图元必须使转换失败，禁止输出可能缺图的 DWG。

显式双规格任务的正式文件名固定为 `成品规格（型腔参数）机台类型.dxf`。
括号内参数必须直接取最终校验几何，不得重复解析输入字符串：

- 无主弧型腔：`槽宽×导轨厚度`，例如 `8.89×2.07`；
- 单弧型腔：`R成型×槽宽×导轨厚度`，例如 `R32.95×6.81×2.82`；
- 双弧型腔：`2-R成型×槽宽×导轨厚度`，例如 `2-R32.95×6.81×2.82`。

计算尺寸统一保留两位小数。公差仍保留在输入、DXF 尺寸和校验报告中。
为兼容 macOS 和 Windows 文件系统，规格内的 `*` 输出为 `×`。

## 输出流程

正式 release 必须通过候选文件晋级：

1. 写入以正式文件名为基准、附带“调试”标识的 DXF；
2. 写入附带“正式候选”标识的候选 DXF；
3. 渲染同名 PNG 预览；
4. 检查候选 DXF；
5. 写入 `report.json`；
6. 全部检查通过后，将候选文件晋级为正式文件名；
7. 任一检查失败时删除候选文件，不生成正式 release。
8. release DXF 通过后，记录 AutoCAD 读取到的模型空间实体数；
9. 按已安装 AutoCAD 版本生成兼容转换用 DXF；
10. 转换同名 AutoCAD 2007 DWG，检查 `AC1021` 文件头；
11. 使用 AutoCAD 重新打开 DWG，复核模型空间实体数与转换用 DXF 一致后才允许交付。

DWG 审计通过时，`report.json.dwg_export` 至少包含：

- `generated: true`
- `dwg_version: "AC1021"`
- `source_modelspace_entity_count`
- `dwg_modelspace_entity_count`
- `modelspace_entity_count_matches: true`
- `release_dxf_version`
- `conversion_dxf_version`
- `release_modelspace_entity_count`
- `legacy_dxf_compatibility_mode`
- `expanded_proxy_graphic_entity_count`
- `autocad_version`
- `core_console_path`

其中 `source_modelspace_entity_count` 表示 AutoCAD 实际读取的转换用 DXF 实体数。
代理图元展开时，该值可能大于 `release_modelspace_entity_count`；最终 DWG 必须
与前者一致。

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
