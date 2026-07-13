# 回归测试与模板版本管理

当前阶段停止新增机台和功能开发，回归测试与模板版本管理是后续修改的准入基础。

## 回归测试库

回归用例位于 `tests/regression/<machine_id>/case_001/`。每个 case 至少包含：

- `input.json`
- `expected_report.json`
- `expected_release.dxf`
- `expected_debug.dxf`
- `expected_preview.png`
- `expected_audit.json`

运行全量回归：

```bash
python3 scripts/run_regression_tests.py
```

脚本会为每个 case 生成：

- `actual_release.dxf`
- `actual_debug.dxf`
- `actual_report.json`
- `actual_preview.png`
- `actual_audit.json`

默认模式只比较，不覆盖 `expected_*` baseline。失败时会在 `tests/regression/regression_summary.json` 中输出 expected vs actual 差异。

## 对比规则

脚本禁止逐字节比较 DXF，改为解析后比较：

- `LINE`、`ARC`、`DIMENSION` 数量
- 关键 ARC 半径分布
- DIMENSION measurement 和定义点
- 图层列表
- 外框 extents
- `PARAM_SLOT` 数量
- `SIDE_DERIVED` 数量

几何数值容差为 `0.01 mm`。报告级检查覆盖：

- `machine_id`
- `guide_length`
- `guide_sections`
- `wheel_positions`
- `slot_width`
- `guide_thickness`
- `R_form`
- `lower_cavity_notch_opening`
- 固定模板尺寸
- release 图层
- DIMENSION 实测值和定义点
- 下砂轮安全规则

含下砂轮机型必须满足：

```text
lower_cavity_notch_opening <= product_length - 0.2
```

## 模板版本管理

每个 `templates/<machine_id>/` 目录必须包含：

- `config.yaml`
- 模板 DXF 文件
- `template_meta.json`

`template_meta.json` 字段：

```json
{
  "machine_id": "",
  "template_version": "v1.0.0",
  "source_template_file": "",
  "sha256": "",
  "change_reason": "",
  "approved_by": "",
  "approved_date": ""
}
```

普通代码修改不得更新 baseline。若 regression fail，默认处理方式是修代码。

标准模板确认变更后，才允许显式更新单个机台 baseline：

```bash
python3 scripts/run_regression_tests.py \
  --update-baseline \
  --machine <machine_id> \
  --change-reason "<变更原因>"
```

脚本会生成 `template_change_report.json`，包含：

- `old_template_sha256`
- `new_template_sha256`
- `old_geometry_summary`
- `new_geometry_summary`
- `changed_dimensions`
- `changed_layers`
- `changed_entity_counts`
- `changed_extents`
- 是否影响 `PARAM_SLOT`
- 是否影响固定模板尺寸
- 是否影响 release 输出

## 风险分级

以下变化标记为 `high_risk_change`：

- `guide_length`
- `guide_sections`
- `wheel_positions`
- 固定尺寸或关键半径涉及 `27`、`40`、`300`、`379`、`435`、`590`、`R80`
- 下砂轮缺口安全规则输出变化

高风险变更禁止默认更新 baseline，必须人工审核后显式加：

```bash
--approve-high-risk
```

标注位置微调、文字位置微调、图层整理、辅助线调整、PNG 预览优化等可标记为 `low_risk_change`，允许按上述 `--update-baseline` 流程更新。
