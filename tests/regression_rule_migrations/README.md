# 2026-10-20 approved rule migration

The 42 original `tests/regression/**/expected_*` artifacts remain frozen.
`20261020_opening_and_wheels.json` records a bounded compatibility overlay for
the seven existing `case_001` fixtures. It does not replace or regenerate those
artifacts, and is not used for other cases.

The user approved two rules: use 30% of slot width, floored to two decimals,
with each machine's original opening cap; apply the existing `product_length *
0.6` wheel-opening limit to every true cavity projection, including curved
cavity crowns, and recalculate wheel placement. Approval covers these rules;
the manifest does not claim that the user reviewed individual golden values.

| Fixture | Approved geometric effect |
| --- | --- |
| bed_618 | Opening 2.00 → 1.86; upper clearance 4.405255 → 4.127689; remove one obsolete side projection segment |
| double_head_up_down | Opening 1.50 → 1.35; upper clearance 13.271857 → 13.123447; remove one obsolete side projection segment |
| double_head_up_up | No geometric change; add opening rule/cap report fields |
| triple_single_down_up | Opening 2.00 → 1.68 and the corresponding dimension definition points |
| triple_single_up_up | No geometric change; add opening rule/cap report fields |
| triple_double_down_up_up | Recalculate four upper wheels in the second section and assembly; clearance 12.70 → 11.926594 and corresponding radius/height definition points |
| triple_double_up_up_up | No change |

Every manifest entry binds all original fixture artifacts and the input by
SHA-256. Each change names one exact path with its old and new value. The
comparison fails if a bound source changes, if a source leaf does not match,
or if any non-migrated field changes. There are no wildcard paths, skipped
dimensions, skipped layers, or ignored opening checks. Original 0.01 mm
regression numeric tolerance is retained.

The original JSON dimension sorting used display text and could reorder rows
when a dimension changed from 12.70 to 11.93. The migration compares all real
DXF dimensions in original modelspace order, retaining their values, labels
and every definition point. It re-reads actual release/debug DXFs rather than
trusting the persisted summary. Fixed template geometry and machine/product
values remain compared.

Both actual DXFs must independently pass DXF validity, real definition-point
binding, closed section contours and real wheel projections/cut-in checks.
The release also passes its complete release inspection. Failed physical
audits cannot be waived by the overlay or by a persisted passed report.

`tests/test_approved_regression_rule_migration.py` generates all seven cases in
a temporary directory and confirms that changing a fixed dimension, moving a
wheel in release/debug, detaching an opening definition point, or modifying a
frozen source is rejected. It checks that all original fixture hashes survive
generation and comparison unchanged.
