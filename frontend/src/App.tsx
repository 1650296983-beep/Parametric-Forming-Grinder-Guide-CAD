import { useEffect, useMemo, useState } from "react";
import type { Dispatch, FormEvent, SetStateAction } from "react";
import { api } from "./api";
import type { DesignInput, GenerationResult, Machine, UserSession, ValidationResult } from "./types";

type Page = "workspace" | "history" | "templates" | "rules";
type Step = 1 | 2 | 3;

const initialDesign: DesignInput = {
  machine_type: "triple_single_down_up",
  guide_rail_type: "single_guide",
  wheel_sequence: ["下", "上"],
  first_wheel_side: "lower",
  template_coordinate_system: "section_xy_y_up",
  finished_spec: "R9.6*8.6*42.6*2.1",
  pre_grinding_spec: "42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)",
  product_shape_after: "bread_shape",
  product_shape_before: "rectangular_block",
  relief: "4-1",
  single_side_or_high_requirement: false,
  high_symmetry_requirement: false,
  large_tile_clearance: false,
  wheel_radius: 80,
};

const navItems: Array<{ id: Page; icon: string; label: string }> = [
  { id: "workspace", icon: "▣", label: "导轨工作台" },
  { id: "history", icon: "◷", label: "历史任务" },
  { id: "templates", icon: "◇", label: "机台模板" },
  { id: "rules", icon: "≡", label: "规则与说明" },
];

const machineFirstSide = (machine: Machine) =>
  ({ 上: "upper", 下: "lower", 左: "left", 右: "right" })[
    machine.wheel_positions[0]
  ] ?? "lower";

const formatProfile = (profile: string) =>
  ({
    rectangular_groove: "矩形槽",
    flat_arc_groove: "平面 + 圆弧槽",
    same_r_tile_groove: "上下同 R 型腔",
  })[profile] ?? profile;

export default function App() {
  const [page, setPage] = useState<Page>("workspace");
  const [isNewTask, setIsNewTask] = useState(false);
  const [step, setStep] = useState<Step>(1);
  const [machines, setMachines] = useState<Machine[]>([]);
  const [design, setDesign] = useState<DesignInput>(initialDesign);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [isServiceOnline, setIsServiceOnline] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationState, setGenerationState] = useState<"idle" | "passed" | "failed">("idle");
  const [generationResult, setGenerationResult] = useState<GenerationResult | null>(null);
  const [session, setSession] = useState<UserSession | null>(null);
  const [isAuthLoading, setIsAuthLoading] = useState(true);

  useEffect(() => {
    void api.health()
      .then(() => setIsServiceOnline(true))
      .catch(() => setIsServiceOnline(false));
    void api.me()
      .then((user) => { setSession(user); return loadMachines(setMachines, setDesign); })
      .catch(() => setSession(null))
      .finally(() => setIsAuthLoading(false));
  }, []);

  const login = async (username: string, password: string) => {
    setApiError(null);
    const user = await api.login(username, password);
    setSession(user);
    setIsServiceOnline(true);
    await loadMachines(setMachines, setDesign);
  };

  const logout = async () => {
    try { await api.logout(); } catch { /* Session is cleared locally even after an expired server session. */ }
    setSession(null);
    setMachines([]);
    setValidation(null);
    setGenerationResult(null);
    setGenerationState("idle");
    setStep(1);
  };

  const returnToDashboard = () => {
    resetWorkspace(setDesign, setStep, setValidation, setGenerationState, setApiError);
    setGenerationResult(null);
    setPage("workspace");
    setIsNewTask(false);
  };

  const selectedMachine = useMemo(
    () => machines.find((machine) => machine.id === design.machine_type) ?? null,
    [design.machine_type, machines],
  );

  const selectMachine = (machineId: string) => {
    const machine = machines.find((item) => item.id === machineId);
    if (!machine) return;
    applyMachine(machine, setDesign);
    setValidation(null);
    setGenerationState("idle");
    setGenerationResult(null);
    setApiError(null);
  };

  const update = <Key extends keyof DesignInput>(key: Key, value: DesignInput[Key]) => {
    setDesign((previous) => ({ ...previous, [key]: value }));
    setValidation(null);
    setGenerationState("idle");
    setGenerationResult(null);
  };

  const validate = async () => {
    setApiError(null);
    setIsValidating(true);
    try {
      const result = await api.validate(design);
      setValidation(result);
      setStep(2);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "规格校验失败。");
      setStep(1);
    } finally {
      setIsValidating(false);
    }
  };

  const generate = async () => {
    if (!validation) return;
    setApiError(null);
    setIsGenerating(true);
    setStep(3);
    try {
      const result = await api.generate(design);
      setGenerationResult(result);
      setGenerationState(result.ok && result.release_allowed ? "passed" : "failed");
      if (!result.ok || !result.release_allowed) {
        setApiError(result.stderr || "完整 DXF 校验未通过，release.dxf 未输出。");
      }
    } catch (error) {
      setGenerationState("failed");
      setApiError(error instanceof Error ? error.message : "生成任务失败。");
    } finally {
      setIsGenerating(false);
    }
  };

  if (isAuthLoading) return <div className="auth-loading">正在确认登录状态…</div>;
  if (!session) return <LoginPage isServiceOnline={isServiceOnline} onLogin={login} />;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark">CAD</div>
        <button className="brand-text" onClick={returnToDashboard} aria-label="返回导轨工作台首页">
          <strong>成型磨导轨</strong>
          <span>参数化生成器</span>
        </button>
        <nav>
          {navItems.map((item) => (
            <button
              className={`nav-item ${page === item.id ? "active" : ""}`}
              key={item.id}
              onClick={() => setPage(item.id)}
            >
              <span>{item.icon}</span>{item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="connection-dot" />本地生成服务
          <small>{isServiceOnline ? "已连接" : "连接异常"}</small>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="eyebrow">工艺工程 / 本地任务</p>
            <h1>{pageTitle(page)}</h1>
          </div>
          <div className="topbar-actions">
            <span className={`status-pill ${isServiceOnline ? "" : "offline"}`}><i />{isServiceOnline ? "服务已连接" : "服务未连接"}</span>
            <span className={`account-pill ${session.role}`}><b>{session.username}</b>{session.role === "administrator" ? "管理员" : "普通用户"}</span>
            <button className="button secondary mini" onClick={() => void logout()}>退出登录</button>
            {page === "workspace" && <button className="button primary" onClick={() => { resetWorkspace(setDesign, setStep, setValidation, setGenerationState, setApiError); setGenerationResult(null); setIsNewTask(true); }}>＋ 新建导轨任务</button>}
          </div>
        </header>
        {page === "workspace" && !isNewTask && <Dashboard onCreate={() => setIsNewTask(true)} />}
        {page === "workspace" && isNewTask && (
          <Workspace
            design={design}
            machines={machines}
            selectedMachine={selectedMachine}
            validation={validation}
            error={apiError}
            step={step}
            isValidating={isValidating}
            isGenerating={isGenerating}
            generationState={generationState}
            generationResult={generationResult}
            onSelectMachine={selectMachine}
            onUpdate={update}
            onValidate={validate}
            onGenerate={generate}
            onBack={() => setStep(1)}
          />
        )}
        {page === "history" && <History />}
        {page === "templates" && <Templates machines={machines} />}
        {page === "rules" && <Rules />}
      </main>
    </div>
  );
}

function LoginPage({ isServiceOnline, onLogin }: { isServiceOnline: boolean; onLogin: (username: string, password: string) => Promise<void> }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await onLogin(username, password);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "登录失败，请重试。");
    } finally {
      setIsSubmitting(false);
    }
  };

  return <main className="login-page">
    <form className="login-card" onSubmit={(event) => void submit(event)}>
      <p className="eyebrow">成型磨导轨 CAD 参数化生成器</p>
      <h1>登录工作台</h1>
      <p>登录后可生成并核对带尺寸标注的导轨截面预览。</p>
      {error && <div className="alert error">{error}</div>}
      <label>账户名<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label>
      <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>
      <button className="button primary" disabled={isSubmitting || !isServiceOnline}>{isSubmitting ? "正在登录…" : "登录"}</button>
      <small>{isServiceOnline ? "管理员与普通用户的权限由服务端配置控制。" : "本地生成服务未连接。"}</small>
    </form>
  </main>;
}

async function loadMachines(
  setMachines: Dispatch<SetStateAction<Machine[]>>,
  setDesign: Dispatch<SetStateAction<DesignInput>>,
) {
  const items = await api.machines();
  setMachines(items);
  const preferred = items.find((item) => item.id === initialDesign.machine_type) ?? items[0];
  if (preferred) applyMachine(preferred, setDesign);
}

function Dashboard({ onCreate }: { onCreate: () => void }) {
  return <section className="dashboard">
    <div className="metrics">
      <Metric label="今日任务" value="—" note="尚未读取任务记录" />
      <Metric label="已通过 RELEASE" value="—" note="正式图纸以校验报告为准" tone="success" />
      <Metric label="待处理失败" value="—" note="阻断任务需要返回修改" tone="error" />
      <Metric label="草稿" value="—" note="本地草稿功能即将接入" />
    </div>
    <div className="dashboard-grid">
      <section className="panel recent-panel">
        <div className="section-heading"><div><p className="eyebrow">本地任务</p><h2>最近任务列表</h2></div><button className="button secondary mini" onClick={onCreate}>新建任务</button></div>
        <div className="table-head"><span>任务名称</span><span>机台</span><span>成品形态</span><span>磨前形态</span><span>状态</span><span>操作</span></div>
        <div className="empty-table"><span>◷</span><div><strong>暂无任务记录</strong><p>新建一个导轨任务后，这里会显示生成状态和 report.json 摘要。</p></div></div>
      </section>
      <aside className="dashboard-aside">
        <section className="reminder-card">
          <div className="reminder-header">ⓘ 规则提醒</div>
          <RuleReminder number="01" title="INPUT LOGIC / 规格输入逻辑" text="成品规格与成型磨前规格必须独立输入；槽宽和导轨厚度以磨前规格为准。" />
          <RuleReminder number="02" title="RELEASE GATE / 正式图纸门禁" text="候选 DXF 未通过几何、图层、旧图元与尺寸定义点审计时，release.dxf 不会输出。" />
          <div className="block-reminder"><strong>BLOCKING / 校验阻断逻辑</strong><p>规格解析失败、关键尺寸不一致或定义点未绑定真实几何时，系统将阻断正式图纸。</p></div>
        </section>
        <section className="preview-placeholder"><span>◇</span><h3>参数化生成预览</h3><p>创建任务并完成计算后显示带尺寸标注的导轨截面。</p><button className="button inverse" onClick={onCreate}>进入生成工作区</button></section>
      </aside>
    </div>
  </section>;
}

function Metric({ label, value, note, tone }: { label: string; value: string; note: string; tone?: "success" | "error" }) {
  return <article className={`metric ${tone ?? ""}`}><p>{label}</p><strong>{value}</strong><small>{note}</small></article>;
}

function RuleReminder({ number, title, text }: { number: string; title: string; text: string }) {
  return <article className="rule-reminder"><span>{number}</span><div><h3>{title}</h3><p>{text}</p></div></article>;
}

function Workspace(props: {
  design: DesignInput;
  machines: Machine[];
  selectedMachine: Machine | null;
  validation: ValidationResult | null;
  error: string | null;
  step: Step;
  isValidating: boolean;
  isGenerating: boolean;
  generationState: "idle" | "passed" | "failed";
  generationResult: GenerationResult | null;
  onSelectMachine: (id: string) => void;
  onUpdate: <Key extends keyof DesignInput>(key: Key, value: DesignInput[Key]) => void;
  onValidate: () => void;
  onGenerate: () => void;
  onBack: () => void;
}) {
  const { design, selectedMachine, validation } = props;
  return (
    <section className="workspace">
      <Stepper active={props.step} />
      {props.error && <div className="alert error"><strong>需要处理：</strong>{props.error}</div>}
      {props.step === 1 && (
        <div className="input-layout">
          <div className="form-stack">
            <section className="panel">
              <PanelTitle number="01" title="选择机台" subtitle="机台固定结构参数来自模板配置，不可在任务中修改。" />
              <div className="machine-grid">
                {props.machines.length === 0 && <div className="skeleton-card">正在读取机台配置…</div>}
                {props.machines.map((machine) => (
                  <button
                    key={machine.id}
                    className={`machine-card ${design.machine_type === machine.id ? "selected" : ""} ${machine.supported_by_web_generation ? "" : "unsupported"}`}
                    onClick={() => props.onSelectMachine(machine.id)}
                    disabled={!machine.supported_by_web_generation}
                    >
                      <span>{machine.guide_sections === 2 ? "双" : "单"}</span>
                      <strong>{machine.name}</strong>
                      <small>{machine.supported_by_web_generation ? `${machine.guide_length} mm · ${machine.wheel_positions.join(" / ")}` : "Web 任务待接入"}</small>
                      <small className="machine-fixed">固定：上口 {machine.section_center_opening} mm · 下沿 {machine.section_slot_base_height} mm</small>
                    </button>
                ))}
              </div>
            </section>
            <section className="panel form-panel">
              <PanelTitle number="02" title="输入产品参数" subtitle="成品与成型磨前规格必须独立填写。" />
              <div className="spec-group finished">
                <GroupTitle badge="成品" title="成品规格" hint="用于确定最终形态与 R_form 来源。" />
                <div className="field-row">
                  <label>成品形态
                    <select value={design.product_shape_after} onChange={(event) => props.onUpdate("product_shape_after", event.target.value as DesignInput["product_shape_after"])}>
                      <option value="tile_shape">瓦型（双 R）</option>
                      <option value="bread_shape">馒头型（单 R）</option>
                    </select>
                  </label>
                  <div className="format-field">
                    <span className="field-label">规格格式</span>
                    <output className="format-hint">{design.product_shape_after === "tile_shape" ? "R外*R内*弦宽*长度*厚度" : "R*宽度*长度*厚度"}</output>
                  </div>
                </div>
                <label>成品规格
                  <input value={design.finished_spec} onChange={(event) => props.onUpdate("finished_spec", event.target.value)} spellCheck={false} />
                </label>
              </div>
              <div className="spec-group preform">
                <GroupTitle badge="磨前" title="成型磨前规格" hint="槽宽、宽度公差及导轨厚度均以此参数为准。" />
                <div className="field-row">
                  <label>磨前形态
                    <select value={design.product_shape_before} onChange={(event) => props.onUpdate("product_shape_before", event.target.value as DesignInput["product_shape_before"])}>
                      <option value="rectangular_block">方块</option>
                      <option value="same_r_tile">同 R 瓦型</option>
                    </select>
                  </label>
                  <label>避空
                    <input value={design.relief} onChange={(event) => props.onUpdate("relief", event.target.value)} />
                  </label>
                </div>
                <label>成型磨前规格
                  <input value={design.pre_grinding_spec} onChange={(event) => props.onUpdate("pre_grinding_spec", event.target.value)} spellCheck={false} />
                </label>
                <p className="input-help">方块：长度*宽度(上偏差/下偏差)*厚度(上偏差/下偏差)</p>
                <div className="process-options">
                  <label className="check-option">
                    <input type="checkbox" checked={design.single_side_or_high_requirement} onChange={(event) => props.onUpdate("single_side_or_high_requirement", event.target.checked)} />
                    <span>磨单边 / 高要求<small>勾选后厚度间隙固定为 0.09 mm</small></span>
                  </label>
                  <label className="check-option">
                    <input type="checkbox" checked={design.high_symmetry_requirement} disabled={design.large_tile_clearance} onChange={(event) => props.onUpdate("high_symmetry_requirement", event.target.checked)} />
                    <span>高对称度槽宽<small>显式采用 0.03 mm 槽宽间隙</small></span>
                  </label>
                  <label className="check-option">
                    <input type="checkbox" checked={design.large_tile_clearance} disabled={design.high_symmetry_requirement} onChange={(event) => props.onUpdate("large_tile_clearance", event.target.checked)} />
                    <span>大瓦放宽槽宽<small>显式采用 0.08 mm 槽宽间隙</small></span>
                  </label>
                  <label>砂轮半径（默认 R80）
                    <input type="number" min="1" step="0.01" value={design.wheel_radius} onChange={(event) => props.onUpdate("wheel_radius", Number(event.target.value))} />
                  </label>
                </div>
              </div>
              <div className="form-actions">
                <span>所有尺寸单位：mm</span>
                <button className="button primary" onClick={props.onValidate} disabled={props.isValidating || !selectedMachine}>
                  {props.isValidating ? "正在解析…" : "确认计算"} <b>→</b>
                </button>
              </div>
            </section>
          </div>
        </div>
      )}
      {props.step === 2 && validation && (
        <Review validation={validation} machine={selectedMachine} onBack={props.onBack} onGenerate={props.onGenerate} />
      )}
      {props.step === 3 && <Generation isGenerating={props.isGenerating} state={props.generationState} error={props.error} validation={validation} result={props.generationResult} />}
    </section>
  );
}

function Stepper({ active }: { active: Step }) {
  return <ol className="stepper">{["输入参数", "确认计算", "生成结果"].map((label, index) => {
    const step = (index + 1) as Step;
    return <li key={label} className={active === step ? "current" : active > step ? "done" : ""}><span>{active > step ? "✓" : index + 1}</span>{label}</li>;
  })}</ol>;
}

function PanelTitle({ number, title, subtitle }: { number: string; title: string; subtitle: string }) {
  return <div className="panel-title"><span>{number}</span><div><h2>{title}</h2><p>{subtitle}</p></div></div>;
}

function GroupTitle({ badge, title, hint }: { badge: string; title: string; hint: string }) {
  return <div className="group-title"><span>{badge}</span><div><h3>{title}</h3><p>{hint}</p></div></div>;
}

function Review({ validation, machine, onBack, onGenerate }: { validation: ValidationResult; machine: Machine | null; onBack: () => void; onGenerate: () => void }) {
  const rows = [
    ["槽宽", `${validation.derived.slot_width.toFixed(2)} ±${validation.derived.slot_width_tolerance.toFixed(2)} mm`, "磨前宽度及公差"],
    ["导轨厚度", `${validation.derived.guide_thickness.toFixed(2)} mm`, "磨前厚度中值 + 机台间隙"],
    ["R_form", validation.decision.arc_radius ? `R${validation.decision.arc_radius.toFixed(2)} mm` : "不适用（矩形槽）", validation.decision.R_form_source],
    ["避空", validation.derived.relief_label, "工艺规则"],
    ["砂轮半径", `R${validation.decision.process_options.wheel_radius.toFixed(2)} mm`, "任务显式参数（默认 R80）"],
  ];
  return <div className="review-layout">
    <section className="panel calculation-panel">
      <PanelTitle number="02" title="确认计算结果" subtitle="以下参数均来自既有 Python 工艺计算，不可直接改写。" />
      <div className="calculation-table">
        {rows.map(([label, value, source]) => <div key={label}><span>{label}</span><strong>{value}</strong><small>{source}</small></div>)}
      </div>
      <div className="machine-summary">{machine?.name} · {machine?.guide_length} mm · {validation.decision.final_section_profile_type}</div>
    </section>
    <section className="panel preview-panel">
      <div className="preview-header"><div><p className="eyebrow">参数化预览</p><h2>{formatProfile(validation.decision.groove_profile)}</h2></div><span className="preview-tag">仅预览</span></div>
      <SectionPreview profile={validation.decision.groove_profile} />
      <p className="preview-caption">正式 DXF 将由后端重新生成真实几何与尺寸定义点，不使用此预览代替图纸。</p>
    </section>
    <section className="panel audit-panel">
      <p className="eyebrow">规则审查</p>
      <h2>输入计算已通过</h2>
      {["成品与磨前规格独立", "槽宽取磨前规格与公差", "导轨厚度取磨前厚度中值", "型腔方向与第一砂轮一致"].map((item) => <div className="check-row" key={item}><span>✓</span>{item}</div>)}
      <div className="audit-warning">下一步将执行 DXF 几何、图层、旧图元和尺寸定义点完整审计。</div>
      <div className="review-actions"><button className="button secondary" onClick={onBack}>返回修改</button><button className="button primary" onClick={onGenerate}>校验并生成图纸 <b>→</b></button></div>
    </section>
  </div>;
}

function SectionPreview({ profile }: { profile: string }) {
  return <div className="drawing-canvas"><div className="axis horizontal" /><div className="axis vertical" /><div className={`slot-figure ${profile}`}><span className="slot-label">型腔</span><i /><b /><em /></div><div className="dimension-line width"><span>槽宽</span></div><div className="dimension-line height"><span>导轨厚度</span></div></div>;
}

function Generation({ isGenerating, state, error, validation, result }: { isGenerating: boolean; state: "idle" | "passed" | "failed"; error: string | null; validation: ValidationResult | null; result: GenerationResult | null }) {
  const stages = ["读取机台配置", "解析产品规格", "重建参数化槽口", "生成候选 release DXF", "运行完整校验", "晋级正式 release"];
  const passed = state === "passed";
  const files = result?.files ?? {};
  return <section className={`generation-view panel ${passed ? "result-passed" : ""}`}><div className={`result-icon ${passed ? "success" : state === "failed" ? "failure" : "running"}`}>{passed ? "✓" : state === "failed" ? "!" : "…"}</div><p className="eyebrow">生成任务</p><h2>{isGenerating ? "正在重建图纸与校验" : passed ? "正式图纸已通过校验" : "正式 release 未输出"}</h2><p>{isGenerating ? "后端正在按固定工作流生成候选文件。" : passed ? "release.dxf 已由候选文件晋级。" : error ?? "任务结束。"}</p>{passed && result?.preview && <div className="output-preview"><img src={result.preview.url} alt="带尺寸标注的导轨截面预览" /></div>}<ol className="generation-steps">{stages.map((label, index) => <li key={label} className={isGenerating && index > 2 ? "waiting" : passed || (!isGenerating && index < 5) ? "ok" : state === "failed" && index === 4 ? "bad" : "waiting"}><span>{passed || (!isGenerating && index < 5) ? "✓" : index + 1}</span>{label}</li>)}</ol>{validation && <div className="result-summary"><strong>{formatProfile(validation.decision.groove_profile)}</strong><span>槽宽 {validation.derived.slot_width.toFixed(2)} mm</span><span>导轨厚度 {validation.derived.guide_thickness.toFixed(2)} mm</span></div>}{passed && <div className="output-files"><h3>可下载文件</h3>{Object.entries(files).map(([key, file]) => <a key={key} href={file.url} target="_blank" rel="noreferrer"><span>▧</span><div><strong>{file.label}</strong><small>{file.name}</small></div><b>下载</b></a>)}</div>}</section>;
}

function History() {
  return <section className="panel page-panel"><PanelTitle number="任务" title="历史任务" subtitle="生成记录将以 report.json 为准，当前首版不修改已有图纸。" /><div className="empty-state"><span>◷</span><h2>暂无 Web 任务记录</h2><p>完成一次本地生成后，历史任务会在这里显示输入快照、校验结果和输出文件。</p></div></section>;
}

function Templates({ machines }: { machines: Machine[] }) {
  return <section className="panel page-panel"><PanelTitle number="配置" title="机台模板" subtitle="来自 templates/&lt;machine_id&gt;/config.yaml，仅供查看。" /><div className="template-table"><div className="template-head"><span>机台</span><span>导轨结构</span><span>砂轮顺序</span><span>固定长度</span></div>{machines.map((machine) => <div className="template-row" key={machine.id}><strong>{machine.name}</strong><span>{machine.guide_sections} 段 / {machine.guide_type === "double_guide" ? "双导轨" : "单导轨"}</span><span>{machine.wheel_positions.join(" / ")}</span><span>{machine.guide_length} mm</span></div>)}</div></section>;
}

function Rules() {
  return <section className="panel page-panel"><PanelTitle number="规则" title="生成与 release 门禁" subtitle="规则源于项目文档并由 Python 校验器执行。" /><div className="rule-list">{[["规格来源", "成品规格与成型磨前规格必须独立；槽宽与导轨厚度取磨前数据。"], ["几何一致性", "相邻图元误差不大于 0.001 mm，闭合轮廓必须严格闭合。"], ["正式图纸", "release 只会在候选 DXF 通过图层、残留图元和尺寸定义点审计后输出。"], ["尺寸审计", "显示值、定义点与真实几何必须一致；双导轨定义点误差不大于 0.01 mm。"]].map(([title, detail]) => <article key={title}><span>✓</span><div><h3>{title}</h3><p>{detail}</p></div></article>)}</div></section>;
}

function pageTitle(page: Page) { return ({ workspace: "导轨生成工作台", history: "历史任务", templates: "机台模板", rules: "规则与说明" })[page]; }

function applyMachine(machine: Machine, setter: Dispatch<SetStateAction<DesignInput>>) {
  setter((previous) => ({ ...previous, machine_type: machine.id, guide_rail_type: machine.guide_type, wheel_sequence: machine.wheel_positions, first_wheel_side: machineFirstSide(machine), template_coordinate_system: machine.template_coordinate_system }));
}

function resetWorkspace(setter: Dispatch<SetStateAction<DesignInput>>, setStep: Dispatch<SetStateAction<Step>>, setValidation: Dispatch<SetStateAction<ValidationResult | null>>, setGenerationState: Dispatch<SetStateAction<"idle" | "passed" | "failed">>, setError: Dispatch<SetStateAction<string | null>>) {
  setter(initialDesign); setStep(1); setValidation(null); setGenerationState("idle"); setError(null);
}
