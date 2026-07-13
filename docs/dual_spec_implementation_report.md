# 双规格驱动实施报告

## 完成范围

- 新增纯业务层 `src/groove_profile.py`，集中完成形状标准化、单/双 R
  分类、槽型、尺寸来源、第一砂轮对立侧和人工确认决策。
- `src/guide_design_input.py` 支持规范字段并兼容旧字段；面包型四段规格可
  结合磨前长宽自动消歧，不再把实例 3 判为长度变化或一分二。
- 双 R 方块磨的 `flat_arc_groove` 选择写入
  `templates/triple_single_down_up/config.yaml`。
- `report.json` 新增 release 强制门禁 `dual_spec_validation`。
- 修复 `4-∅1.00` 直径 DIMENSION 定义点绑定，正式 release 不再因把
  直径端点误作圆心而失败。
- 三份用户参考 DXF 已固化到 `tests/reference_drawings/`，并新增可重复的
  几何/尺寸对比工具和自动测试。

## 三个实例结果

| 实例 | 分类 | 当前槽宽 | 当前导轨厚度 | 当前弧面 | 参考截面 |
|---|---|---:|---:|---:|---|
| 1 | 方块 + 双 R 瓦型 | 5.02 | 2.37 | 下部 R16.3、上部平面 | 下部 R16.3、上部平面 |
| 2 | 方块 + 单 R 面包型 | 8.56 | 2.22 | 矩形槽 | 矩形槽 |
| 3 | 方块 + 单 R 面包型 | 12.14 | 2.22 | 矩形槽 | 矩形槽，槽宽 12.15 |

三个实例的槽型、R 方向和固定中心上口现已与生产图一致。导轨厚度继续按
QG 的方块 `+0.12 mm` 规则，实例 3 槽宽继续按 QG 得到 12.14 mm；这些与
历史图纸的数值差异标记为 `APPROVED_RULE_OVERRIDE`，参考对比状态为
`PASS`。

## 已落实的工艺裁决

1. 三份参考图均为有效生产图纸。
2. 双 R 产品且磨前为方块或瓦型时，导轨 R 面与第一砂轮同侧；圆心在
   对侧。所有单、双导轨机台均有自动测试。
3. 单 R 面包型产品且磨前为方块时，导轨按矩形槽生成。
4. 槽宽和导轨厚度继续执行 QG 38012。
5. `first_wheel_side` 必须与 `wheel_sequence` 第一项一致，否则拒绝生成。

## 验证命令

```bash
python3 -m pytest -q
python3 -m src.generate_machine --machine-id triple_single_down_up \
  --input-json examples/dual_spec/example_1.json \
  --output-dir output/dual_spec_examples --name example_1
python3 -m src.reference_dxf_audit \
  --reference tests/reference_drawings/instance_1_reference.dxf \
  --report output/dual_spec_examples/triple_single_down_up/reports/example_1_report.json \
  --output output/dual_spec_examples/triple_single_down_up/reference_comparison/example_1.json
```
