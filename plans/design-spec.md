# Workbench visual implementation spec

Working concept selected within the user's authorized redesign scope. No further design approval is required. Image generated with the built-in Image Gen tool, inspected with `view_image`, source at `output/ui-workbench/concept.png` (1536×1024). Preserve this UI chrome, composition, hierarchy and palette. The prompt requested a readable industrial CAD workbench, all existing nav, three steps, parameter rail/right CAD canvas/bottom actions and exact opening/relief fields. No bitmap UI is shipped.

## Authoritative data exception

The CAD illustration inside the generated concept is **not engineering input**. It has invented holes and an illustrative outer profile; these must NEVER be reproduced. The user explicitly requires parameterized actual CAD geometry and independent validation. Replace that entire illustrative drawing with the backend's real DXF-derived scene, including native dimensions, six relief arcs and actual side views. The concept's example slot8.57 is also illustrative: the actual sample is8.56, so display backend8.56. These are required correctness deviations, not a license to change the layout.

## Composition and containers

At1536×1024 the nav is225px, header82px, step strip64px, bottom bar84px. Work area starts atx233/y146; left rail371px; gap10; right canvas918px. At1440px use nav208px, rail348px, gap10, main padding10; at1280px use nav176px, rail320px and the remaining canvas. Header76px; step strip56px; bottom actions72px. Work area should fill remaining viewport height; rail content scrolls independently, bottom actions stay visible. Canvas min-width0 and fits available space, never stretches CAD ratio. At1280×720 show compact heading/rail spacing without hiding primary fields behind an unreachable footer.

No nested cards around every field. One white bordered left rail (radius6), one canvas region (radius6), one toolbar/header/footer. Rail rows separated by thin rules; measured numbers and original specs are the focus. Step strip is plain lines/circles with current/complete colors. Native white footer across workbench width, right-aligned secondary and primary actions. Main shell nav and header remain stable for other pages.

## Color lock and type

- App background cool pale gray `#f3f5f8`; panels/header/footer true white `#ffffff`, no warm tints.
- Sidebar `#14283e`, selected nav `#234a7a`, active marker `#367cf5`.
- Text `#102033`, muted `#60718a`, border `#d8e1ec`, primary button `#193e7b`, primary hover `#244e92`.
- Canvas `#192b38`, grid `#29404e` at low opacity; outline `#eef5fa`, cavity `#40ce85`, dimension `#51e0e8`, center `#f14b53`.
- Success `#20b978`, error `#b62b38`, attention `#94651b`; semantic colors need text/icon too.
- Keep existing system Chinese font stack. Body/controls14px, labels13px, primary page heading24px/600, rail heading22px/600, muted helper12px with line-height1.5. Numerical body15–16px monospace, primary slot value28px; avoid giant data cards.
- Spacing scale4/8/12/16/20/24; rail padding20desktop,16compact; row12–16px vertical. Form inputs36–40px high; action buttons40px high. Corner radius6px, thin borders, minimal shadow only drawer.

## Visible copy and components

Brand: `成型磨导轨`, `参数化生成器`. Existing small CAD square may become a simple outlined guide glyph; no generated logo asset required. Navigation EXACT labels: `导轨工作台`, `历史任务`, `机台模板`, `规则与说明`, `设置与更新`. Sidebar bottom `本地引擎已连接` or honest offline status. Use uniform20px outline icons stroke1.6 (cube/workbench, clock/history, document/template, book/rules, gear/settings), code-native inlineSVG, no emoji replacement.

Header: `导轨工作台`; subtitle `依据磨前规格，生成可复核的加工图纸`; right `本地任务`, secondary `新建任务`. Retain safe existing new-task/reset behavior, with request invalidation. Page-specific headings retained for other nav.

Steps: `输入参数` / `确认计算` / `生成结果`. Review rail `计算结果`, `当前输入已解析`. Machine and snapshot rows `机台`, `成品`, `磨前`. Values from API only. Calculation rows `槽宽`, `导轨厚度`, `入丝口`, `侧部避空`, `中心过渡`, `砂轮半径`; further R source/direction only when applicable (required workflow data). Opening helper `槽宽 × 30%，机台上限 {actualcap} mm`; show actual floor-rounded value. Side relief `4 × Ø{diameter} mm / R{radius}` separate from center `2 × R0.50`. Review footnote `正式图纸仍需通过完整几何校验。` Backend warnings retain actual text.

Canvas toolbar view buttons from actual scene: default `截面图`, actual dual section tabs, actual side/assembly when available; unavailable side choice must be disabled honestly (optional hidden until available). Right zoom-minus icon, current percentage, zoom-plus icon, four-corners `适应画布`. Outline16–18px icons. Canvas source note `参数预览` / `候选图纸` / `正式图纸` based on backend source, with task identity after generation. Bottom legend `轮廓` / `尺寸` / `中心线`; hint `拖动平移 · 滚轮缩放`.

Review bottom: left successcheck + `当前输入计算通过 · 尚未生成正式图纸`; right `返回修改`, navy `生成并校验图纸 →`. Input same region with `确认计算 →`; generation current true stage and elapsed independent; result primary `打开图纸`/`另存副本` use existing desktop controls, secondary new-task/back review as useful. Labels may expand for actual success/failure/reconnect but no invented product sections.

## State inventory in the same system

- Input rail replaces calculation rows with existing machine/spec/form fields, no new panel arrangement. Right canvas honest blank/drafting state; no pretend CAD before calculation. Empty-state copy explains calculating will display actual geometry.
- Review uses selected image. Raw specs can wrap, remain selectable and never truncate critical tolerances without accessible fulltext.
- Generation replaces left rows with actual stage list and snapshot summary. Keep canvas stable and display new actual groups as emitted by backend; fast stages may arrive together and final appears immediately. Retain existing completed linework, no erase loop. No fake percentage.
- Result replaces rail with status, key values, formal drawing actions, secondary reports/debug disclosure. Final canvas reads actual promoted release. Failure shows actualstage/error, no formal action, preserves input and focuses correction on return.
- History keeps list/filter/delete conventions, drawer restyled in same system and `复制为新任务` action. Focus trap/Escape/return focus, no automatic destructive action.
- Narrow<1000px: compact nav becomes horizontal visible labels or72px iconrail with accessible names, rail and canvas stack, footer wraps. At390px page width remains390; task history may have an intentionally scrollable table region but no body overflow. Canvas min-height320. All controls keyboard accessible. Use no new imagery/assets beyond SVGicons.

## Motion and acceptance

Use exact tokens/constraints in002. No external motion dependency. Content state changes immediate; short CSS opacity explains new groups, controls never wait. Reduced motion removes movement, keeps color/opacity feedback. Pan/zoom are immediate.

Fidelity ledger after implementation must compare concept and latest screenshot with `view_image`: (1) nav/header/step composition, (2) rail/canvas/footer positions and relative widths, (3) typography/numeric hierarchy, (4) exact white/gray/navy/canvas palette, (5) row spacing/borders/icon family, (6) visible copy above fold. Only intentional differences are actual CAD/data, necessary source/status/task information and actual native viewport adaptation. Repair material differences before handoff.
