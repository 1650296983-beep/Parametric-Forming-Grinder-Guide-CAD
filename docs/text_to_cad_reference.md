# text-to-cad 借鉴说明

参考项目：

```text
https://github.com/earthtojake/text-to-cad
```

## 借鉴内容

本项目只借鉴其工程工作流思想，不迁移为通用 text-to-cad：

1. 项目级 `AGENTS.md` 明确边界和禁止事项。
2. 源规则优先，生成物作为可复现派生产物管理。
3. 修改源规则后显式 regenerate。
4. 每次生成后自动 inspect。
5. CAD 输出和校验报告一起保存。
6. preview/review 是生成闭环的一部分。
7. report 中记录几何事实、派生参数和检查结果。
8. 为后续多格式预览保留明确的 preview/inspection/report 模块边界。

## 不采用内容

以下内容不适用于当前项目：

1. 不采用自然语言任意 CAD 生成模式。
2. 不把 STEP/build123d 作为主输出。
3. 不改写为通用 CAD skill。
4. 不用 `@cad[...]` 引用驱动导轨设计。
5. 不在当前阶段增加 3D、STL、STEP、URDF 或 Web CAD Explorer 依赖。

## 本项目固化后的流程

当前流程固定为：

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

正式 release 只能从通过校验的候选文件晋级。

## 当前定位

当前项目仍保持：

- Python + ezdxf；
- 公司产品规格解析；
- 成型磨导轨工艺规则；
- 多机台 `config.yaml`；
- DXF 干净模板读取；
- 参数化几何重建；
- debug/release 双输出；
- PNG 预览；
- `report.json` 校验报告；
- 尺寸一致性校验。
