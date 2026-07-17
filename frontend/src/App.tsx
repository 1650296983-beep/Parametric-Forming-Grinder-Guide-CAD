import { useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { open, save } from "@tauri-apps/plugin-dialog";
import { writeFile } from "@tauri-apps/plugin-fs";
import { relaunch } from "@tauri-apps/plugin-process";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { api } from "./api";
import { resetApiBaseUrl } from "./api";
import type { DesignInput, DesktopSettings, GeneratedFile, GenerationResult, Machine, TaskDetail, TaskHistoryResult, TaskStatus, TaskSummary, ValidationResult } from "./types";

type Page = "workspace" | "history" | "templates" | "rules" | "settings";
type Step = 1 | 2 | 3;

const initialDesign: DesignInput = {
  machine_type: "triple_single_down_up",
  guide_rail_type: "single_guide",
  wheel_sequence: ["下", "上"],
  first_wheel_side: "lower",
  template_coordinate_system: "section_xy_y_up",
  finished_spec: "",
  pre_grinding_spec: "",
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
  { id: "settings", icon: "⚙", label: "设置与更新" },
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

const isTauri = () => "__TAURI_INTERNALS__" in window;

const saveGeneratedFile = async (file: GeneratedFile): Promise<string | null> => {
  if (!isTauri()) {
    const anchor = document.createElement("a");
    anchor.href = file.url;
    anchor.download = file.name;
    anchor.rel = "noreferrer";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    return "浏览器默认下载目录";
  }

  const source = new URL(file.url);
  if (source.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(source.hostname)) {
    throw new Error("只允许保存本地 CAD 引擎生成的文件。");
  }

  const safeName = file.name.replace(/[<>:"/\\|?*\u0000-\u001F]/g, "_");
  const extension = safeName.includes(".") ? safeName.split(".").pop()?.toLowerCase() : undefined;
  const target = await save({
    defaultPath: safeName,
    filters: extension ? [{ name: file.label, extensions: [extension] }] : undefined,
  });
  if (!target) return null;

  const response = await fetch(source);
  if (!response.ok) throw new Error(`本地文件读取失败（HTTP ${response.status}）。`);
  const content = new Uint8Array(await response.arrayBuffer());
  if (content.byteLength === 0) throw new Error("生成文件为空，未执行保存。");
  await writeFile(target, content);
  return target;
};

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
  const [taskHistory, setTaskHistory] = useState<TaskHistoryResult | null>(null);
  const [isTasksLoading, setIsTasksLoading] = useState(false);
  const [taskHistoryError, setTaskHistoryError] = useState<string | null>(null);
  const [selectedHistoryTaskId, setSelectedHistoryTaskId] = useState<string | null>(null);

  useEffect(() => {
    void api.health()
      .then(() => { setIsServiceOnline(true); return loadMachines(setMachines, setDesign); })
      .catch(() => setIsServiceOnline(false));
  }, []);

  useEffect(() => {
    void refreshTaskHistory(setTaskHistory, setIsTasksLoading, setTaskHistoryError);
  }, []);

  useEffect(() => {
    if ("__TAURI_INTERNALS__" in window) void check().catch(() => undefined);
  }, []);

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
      void refreshTaskHistory(setTaskHistory, setIsTasksLoading, setTaskHistoryError);
    }
  };

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
              onClick={() => {
                setPage(item.id);
                if (item.id === "history") setSelectedHistoryTaskId(null);
              }}
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
            <span className="account-pill administrator"><b>本地</b>管理员</span>
            {page === "workspace" && <button className="button primary" onClick={() => { resetWorkspace(setDesign, setStep, setValidation, setGenerationState, setApiError); setGenerationResult(null); setIsNewTask(true); }}>＋ 新建导轨任务</button>}
          </div>
        </header>
        {page === "workspace" && !isNewTask && <Dashboard
          history={taskHistory}
          isLoading={isTasksLoading}
          error={taskHistoryError}
          onCreate={() => setIsNewTask(true)}
          onViewTask={(taskId) => { setSelectedHistoryTaskId(taskId); setPage("history"); }}
        />}
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
        {page === "history" && <History
          history={taskHistory}
          isLoading={isTasksLoading}
          error={taskHistoryError}
          initialTaskId={selectedHistoryTaskId}
          onRefresh={() => refreshTaskHistory(setTaskHistory, setIsTasksLoading, setTaskHistoryError)}
        />}
        {page === "templates" && <Templates machines={machines} />}
        {page === "rules" && <Rules />}
        {page === "settings" && <DesktopSettingsPage onEngineState={setIsServiceOnline} />}
      </main>
    </div>
  );
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

function Dashboard({ history, isLoading, error, onCreate, onViewTask }: {
  history: TaskHistoryResult | null;
  isLoading: boolean;
  error: string | null;
  onCreate: () => void;
  onViewTask: (taskId: string) => void;
}) {
  const metrics = history?.metrics;
  const recentTasks = history?.items.slice(0, 5) ?? [];
  return <section className="dashboard">
    <div className="metrics">
      <Metric label="今日任务" value={metricValue(metrics?.today, isLoading)} note="按本地任务创建时间统计" />
      <Metric label="已通过 RELEASE" value={metricValue(metrics?.passed, isLoading)} note="正式图纸以校验报告为准" tone="success" />
      <Metric label="待处理失败" value={metricValue(metrics?.failed, isLoading)} note="缺少报告或校验阻断的任务" tone="error" />
      <Metric label="全部任务" value={metricValue(metrics?.total, isLoading)} note={metrics?.running ? `${metrics.running} 个任务仍在执行` : "已读取本地任务记录"} />
    </div>
    <div className="dashboard-grid">
      <section className="panel recent-panel">
        <div className="section-heading"><div><p className="eyebrow">本地任务</p><h2>最近任务列表</h2></div><button className="button secondary mini" onClick={onCreate}>新建任务</button></div>
        <div className="table-head"><span>任务名称</span><span>机台</span><span>成品形态</span><span>磨前形态</span><span>状态</span><span>操作</span></div>
        {error && <div className="table-message error">{error}</div>}
        {!error && isLoading && <div className="table-message">正在读取本地任务记录…</div>}
        {!error && !isLoading && recentTasks.length > 0 && <TaskRows tasks={recentTasks} onView={onViewTask} />}
        {!error && !isLoading && recentTasks.length === 0 && <TaskEmpty />}
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

function metricValue(value: number | undefined, isLoading: boolean) {
  if (isLoading) return "…";
  return value === undefined ? "—" : String(value);
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
                  <input value={design.finished_spec} placeholder={design.product_shape_after === "tile_shape" ? "例如：R30*R28*17.4*23.5*3.95" : "例如：R9.6*8.6*42.6*2.1"} onChange={(event) => props.onUpdate("finished_spec", event.target.value)} spellCheck={false} />
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
                  <input value={design.pre_grinding_spec} placeholder="例如：42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)" onChange={(event) => props.onUpdate("pre_grinding_spec", event.target.value)} spellCheck={false} />
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
                <button className="button primary" onClick={props.onValidate} disabled={props.isValidating || !selectedMachine || !design.finished_spec.trim() || !design.pre_grinding_spec.trim()}>
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

function ArtifactSaveButton({ file }: { file: GeneratedFile }) {
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  const saveFile = async () => {
    setState("saving");
    setMessage(null);
    try {
      const target = await saveGeneratedFile(file);
      if (!target) {
        setState("idle");
        return;
      }
      setState("saved");
      setMessage(`已保存到：${target}`);
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? `保存失败：${error.message}` : "保存失败，请重新选择保存位置。");
    }
  };

  return <div className={`artifact-save ${state}`}>
    <button type="button" onClick={() => void saveFile()} disabled={state === "saving"}>
      {state === "saving" ? "保存中…" : state === "saved" ? "再次另存" : "另存为"}
    </button>
    {message && <small role="status" title={message}>{message}</small>}
  </div>;
}

function Generation({ isGenerating, state, error, validation, result }: { isGenerating: boolean; state: "idle" | "passed" | "failed"; error: string | null; validation: ValidationResult | null; result: GenerationResult | null }) {
  const stages = ["读取机台配置", "解析产品规格", "重建参数化槽口", "生成候选 release DXF", "运行完整校验", "晋级正式 release"];
  const passed = state === "passed";
  const files = result?.files ?? {};
  return <section className={`generation-view panel ${passed ? "result-passed" : ""}`}><div className={`result-icon ${passed ? "success" : state === "failed" ? "failure" : "running"}`}>{passed ? "✓" : state === "failed" ? "!" : "…"}</div><p className="eyebrow">生成任务</p><h2>{isGenerating ? "正在重建图纸与校验" : passed ? "正式图纸已通过校验" : "正式 release 未输出"}</h2><p>{isGenerating ? "后端正在按固定工作流生成候选文件。" : passed ? "release.dxf 已由候选文件晋级。" : error ?? "任务结束。"}</p>{passed && result?.preview && <div className="output-preview"><img src={result.preview.url} alt="带尺寸标注的导轨截面预览" /></div>}<ol className="generation-steps">{stages.map((label, index) => <li key={label} className={isGenerating && index > 2 ? "waiting" : passed || (!isGenerating && index < 5) ? "ok" : state === "failed" && index === 4 ? "bad" : "waiting"}><span>{passed || (!isGenerating && index < 5) ? "✓" : index + 1}</span>{label}</li>)}</ol>{validation && <div className="result-summary"><strong>{formatProfile(validation.decision.groove_profile)}</strong><span>槽宽 {validation.derived.slot_width.toFixed(2)} mm</span><span>导轨厚度 {validation.derived.guide_thickness.toFixed(2)} mm</span></div>}{passed && <div className="output-files"><h3>可保存文件</h3>{Object.entries(files).map(([key, file]) => <div className="output-file-row" key={key}><span>▧</span><div><strong>{file.label}</strong><small>{file.name}</small></div><ArtifactSaveButton file={file} /></div>)}</div>}</section>;
}

function History({ history, isLoading, error, initialTaskId, onRefresh }: {
  history: TaskHistoryResult | null;
  isLoading: boolean;
  error: string | null;
  initialTaskId: string | null;
  onRefresh: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<TaskStatus | "all">("all");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(initialTaskId);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(new Set());
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedTaskId) {
      setDetail(null);
      return;
    }
    setIsDetailLoading(true);
    setDetailError(null);
    void api.task(selectedTaskId)
      .then(setDetail)
      .catch((loadError) => setDetailError(loadError instanceof Error ? loadError.message : "任务详情读取失败。"))
      .finally(() => setIsDetailLoading(false));
  }, [selectedTaskId]);

  const normalizedQuery = query.trim().toLowerCase();
  const tasks = (history?.items ?? []).filter((task) => {
    if (statusFilter !== "all" && task.status !== statusFilter) return false;
    if (!normalizedQuery) return true;
    return [task.task_id, task.finished_spec, task.pre_grinding_spec, task.machine_name]
      .some((value) => value.toLowerCase().includes(normalizedQuery));
  });
  const selectableTaskIds = tasks.filter((task) => task.can_delete).map((task) => task.task_id);
  const allSelectableTasksSelected = selectableTaskIds.length > 0
    && selectableTaskIds.every((taskId) => selectedTaskIds.has(taskId));

  const toggleTaskSelection = (taskId: string, checked: boolean) => {
    setSelectedTaskIds((previous) => {
      const next = new Set(previous);
      if (checked) next.add(taskId);
      else next.delete(taskId);
      return next;
    });
  };

  const toggleAllVisibleTasks = (checked: boolean) => {
    setSelectedTaskIds((previous) => {
      const next = new Set(previous);
      for (const taskId of selectableTaskIds) {
        if (checked) next.add(taskId);
        else next.delete(taskId);
      }
      return next;
    });
  };

  const deleteHistoryTask = async (task: TaskSummary) => {
    const confirmed = window.confirm(`确认删除任务 ${task.finished_spec || task.task_id}？\n删除后 DXF、DWG、预览和报告均无法恢复。`);
    if (!confirmed) return;
    setDeletingTaskId(task.task_id);
    setDeleteError(null);
    setDeleteMessage(null);
    try {
      await api.deleteTask(task.task_id);
      if (selectedTaskId === task.task_id) setSelectedTaskId(null);
      setSelectedTaskIds((previous) => {
        const next = new Set(previous);
        next.delete(task.task_id);
        return next;
      });
      setDeleteMessage("任务已删除。");
      await onRefresh();
    } catch (deleteTaskError) {
      setDeleteError(deleteTaskError instanceof Error ? deleteTaskError.message : "历史任务删除失败。");
    } finally {
      setDeletingTaskId(null);
    }
  };

  const deleteSelectedTasks = async () => {
    const taskIds = Array.from(selectedTaskIds);
    if (taskIds.length === 0) return;
    const confirmed = window.confirm(`确认批量删除已选择的 ${taskIds.length} 个任务？\n删除后 DXF、DWG、预览和报告均无法恢复。`);
    if (!confirmed) return;
    setIsBulkDeleting(true);
    setDeleteError(null);
    setDeleteMessage(null);
    try {
      const result = await api.deleteTasks(taskIds);
      const deleted = new Set(result.deleted);
      setSelectedTaskIds((previous) => new Set(Array.from(previous).filter((taskId) => !deleted.has(taskId))));
      if (selectedTaskId && deleted.has(selectedTaskId)) setSelectedTaskId(null);
      const skippedSummary = result.skipped.length > 0
        ? `，跳过 ${result.skipped.length} 项：${result.skipped.map((item) => `${item.task_id} ${item.reason}`).join("；")}`
        : "";
      setDeleteMessage(`已删除 ${result.deleted.length} 个任务${skippedSummary}`);
      await onRefresh();
    } catch (bulkDeleteError) {
      setDeleteError(bulkDeleteError instanceof Error ? bulkDeleteError.message : "批量删除失败。");
    } finally {
      setIsBulkDeleting(false);
    }
  };

  return <section className="history-page">
    <section className="panel history-list-panel">
      <div className="history-heading">
        <PanelTitle number="任务" title="历史任务" subtitle={`直接读取本地任务输入、校验结果与授权文件；${history?.retention_days === 0 ? "桌面任务长期保留。" : `完成任务自动保留 ${history?.retention_days ?? 30} 天。`}`} />
        <button className="button secondary mini" onClick={onRefresh} disabled={isLoading}>刷新记录</button>
      </div>
      <div className="history-filters">
        <input aria-label="搜索历史任务" placeholder="搜索规格、机台或任务 ID" value={query} onChange={(event) => { setQuery(event.target.value); setSelectedTaskIds(new Set()); }} />
        <select aria-label="筛选任务状态" value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value as TaskStatus | "all"); setSelectedTaskIds(new Set()); }}>
          <option value="all">全部状态</option>
          <option value="passed">已通过</option>
          <option value="failed">失败 / 阻断</option>
          <option value="running">执行中</option>
        </select>
        <span>共 {tasks.length} 条</span>
      </div>
      <div className="history-bulk-actions"><span>已选择 <strong>{selectedTaskIds.size}</strong> 项</span><button className="button danger mini" disabled={selectedTaskIds.size === 0 || isBulkDeleting} onClick={() => void deleteSelectedTasks()}>{isBulkDeleting ? "批量删除中…" : "批量删除"}</button><small>执行中任务不可删除。</small></div>
      <div className="table-head selectable"><label className="task-selector"><input type="checkbox" aria-label="全选当前可删除任务" checked={allSelectableTasksSelected} disabled={selectableTaskIds.length === 0} onChange={(event) => toggleAllVisibleTasks(event.target.checked)} /></label><span>任务名称</span><span>机台</span><span>成品形态</span><span>磨前形态</span><span>状态</span><span>操作</span></div>
      {error && <div className="table-message error">{error}</div>}
      {deleteError && <div className="history-action-error">{deleteError}</div>}
      {deleteMessage && <div className="history-action-message">{deleteMessage}</div>}
      {!error && isLoading && <div className="table-message">正在读取本地任务记录…</div>}
      {!error && !isLoading && tasks.length > 0 && <TaskRows tasks={tasks} selectedTaskId={selectedTaskId} selectedTaskIds={selectedTaskIds} deletingTaskId={deletingTaskId} onView={setSelectedTaskId} onToggleSelection={toggleTaskSelection} onDelete={(task) => void deleteHistoryTask(task)} />}
      {!error && !isLoading && tasks.length === 0 && <TaskEmpty filtered={Boolean(query || statusFilter !== "all")} />}
    </section>
    {(selectedTaskId || isDetailLoading || detailError) && <TaskDetailDrawer detail={detail} isLoading={isDetailLoading} error={detailError} onClose={() => setSelectedTaskId(null)} />}
  </section>;
}

function TaskRows({ tasks, selectedTaskId, selectedTaskIds, deletingTaskId = null, onView, onToggleSelection, onDelete }: { tasks: TaskSummary[]; selectedTaskId?: string | null; selectedTaskIds?: ReadonlySet<string>; deletingTaskId?: string | null; onView: (taskId: string) => void; onToggleSelection?: (taskId: string, checked: boolean) => void; onDelete?: (task: TaskSummary) => void }) {
  const selectable = Boolean(onToggleSelection);
  return <div className="task-rows">{tasks.map((task) => <div className={`task-row ${selectable ? "selectable" : ""} ${selectedTaskId === task.task_id ? "selected" : ""}`} key={task.task_id}>
    {selectable && <label className="task-selector"><input type="checkbox" aria-label={`选择任务 ${task.finished_spec || task.task_id}`} checked={selectedTaskIds?.has(task.task_id) ?? false} disabled={!task.can_delete} onChange={(event) => onToggleSelection?.(task.task_id, event.target.checked)} /></label>}
    <div className="task-name"><strong>{task.finished_spec || task.task_id}</strong><small>{formatTaskTime(task.created_at)} · {task.task_id}</small></div>
    <span>{task.machine_name}</span>
    <span>{shapeLabel(task.finished_shape)}</span>
    <span>{shapeLabel(task.pre_grinding_shape)}</span>
    <span><TaskStatusBadge status={task.status} /></span>
    <div className="task-actions"><button className="link-button" onClick={() => onView(task.task_id)}>查看</button>{task.can_delete && onDelete && <button className="link-button danger" disabled={deletingTaskId === task.task_id} onClick={() => onDelete(task)}>{deletingTaskId === task.task_id ? "删除中" : "删除"}</button>}</div>
  </div>)}</div>;
}

function TaskEmpty({ filtered = false }: { filtered?: boolean }) {
  return <div className="empty-table"><span>◷</span><div><strong>{filtered ? "没有符合条件的任务" : "暂无任务记录"}</strong><p>{filtered ? "请调整搜索词或状态筛选。" : "新建任务后，这里会显示输入快照、生成状态和 report.json 摘要。"}</p></div></div>;
}

function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const labels: Record<TaskStatus, string> = { running: "执行中", passed: "已通过", failed: "失败 / 阻断" };
  return <span className={`task-status ${status}`}>{labels[status]}</span>;
}

function TaskDetailDrawer({ detail, isLoading, error, onClose }: { detail: TaskDetail | null; isLoading: boolean; error: string | null; onClose: () => void }) {
  return <div className="task-detail-layer"><button className="task-detail-backdrop" aria-label="关闭任务详情" onClick={onClose} /><aside className="task-detail-drawer" role="dialog" aria-modal="true" aria-label="任务详情"><div className="task-detail-toolbar"><strong>任务详情</strong><button aria-label="关闭任务详情" onClick={onClose}>×</button></div>{isLoading ? <div className="table-message">正在读取任务详情…</div> : error ? <div className="table-message error">{error}</div> : detail ? <TaskDetailContent detail={detail} /> : null}</aside></div>;
}

function TaskDetailContent({ detail }: { detail: TaskDetail }) {
  const files = Object.entries(detail.files);
  return <section className="task-detail">
    <div className="task-detail-header"><div><p className="eyebrow">任务详情 / {detail.task_id}</p><h2>{detail.finished_spec}</h2><small>{formatTaskTime(detail.created_at)} · {detail.machine_name}</small></div><TaskStatusBadge status={detail.status} /></div>
    {detail.error && <div className="task-error"><strong>失败原因</strong><span>{detail.error}</span></div>}
    <div className="task-detail-grid">
      <div><h3>输入快照</h3><dl><dt>成品规格</dt><dd>{detail.input.finished_spec}</dd><dt>磨前规格</dt><dd>{detail.input.pre_grinding_spec}</dd><dt>成品 / 磨前形态</dt><dd>{shapeLabel(detail.input.product_shape_after)} / {shapeLabel(detail.input.product_shape_before)}</dd><dt>避空 / 砂轮半径</dt><dd>{detail.input.relief} / R{detail.input.wheel_radius.toFixed(2)}</dd></dl></div>
      <div><h3>计算与门禁</h3><dl><dt>槽宽</dt><dd>{formatMillimeter(detail.derived.slot_width)}</dd><dt>导轨厚度</dt><dd>{formatMillimeter(detail.derived.guide_thickness)}</dd><dt>DXF 几何检查</dt><dd>{auditLabel(detail.audit.inspection_passed)}</dd><dt>尺寸定义点</dt><dd>{auditLabel(detail.audit.dimension_points_passed)}</dd></dl></div>
      {detail.preview && <div className="task-preview"><h3>截面预览</h3><a href={detail.preview.url} target="_blank" rel="noreferrer"><img src={detail.preview.url} alt={`${detail.finished_spec} 导轨截面预览`} /></a></div>}
    </div>
    <div className="task-files"><h3>可用文件</h3>{files.length === 0 ? <p>该任务没有可保存的授权文件。</p> : files.map(([key, file]) => <div className="task-file-row" key={key}><span>{file.label}</span><small>{file.name}</small><ArtifactSaveButton file={file} /></div>)}</div>
  </section>;
}

function formatTaskTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

function shapeLabel(shape: string) {
  return ({ tile_shape: "瓦型", bread_shape: "馒头型", rectangular_block: "方块", same_r_tile: "同 R 瓦型" })[shape] ?? shape;
}

function formatMillimeter(value: number | null) {
  return value === null ? "—" : `${value.toFixed(2)} mm`;
}

function auditLabel(passed: boolean) {
  return passed ? "通过" : "未通过 / 无报告";
}

async function refreshTaskHistory(
  setHistory: Dispatch<SetStateAction<TaskHistoryResult | null>>,
  setLoading: Dispatch<SetStateAction<boolean>>,
  setError: Dispatch<SetStateAction<string | null>>,
) {
  setLoading(true);
  setError(null);
  try {
    setHistory(await api.tasks(200));
  } catch (loadError) {
    setError(loadError instanceof Error ? loadError.message : "历史任务读取失败。");
  } finally {
    setLoading(false);
  }
}

function Templates({ machines }: { machines: Machine[] }) {
  return <section className="panel page-panel"><PanelTitle number="配置" title="机台模板" subtitle="来自 templates/&lt;machine_id&gt;/config.yaml，仅供查看。" /><div className="template-table"><div className="template-head"><span>机台</span><span>导轨结构</span><span>砂轮顺序</span><span>固定长度</span></div>{machines.map((machine) => <div className="template-row" key={machine.id}><strong>{machine.name}</strong><span>{machine.guide_sections} 段 / {machine.guide_type === "double_guide" ? "双导轨" : "单导轨"}</span><span>{machine.wheel_positions.join(" / ")}</span><span>{machine.guide_length} mm</span></div>)}</div></section>;
}

function Rules() {
  return <section className="panel page-panel"><PanelTitle number="规则" title="生成与 release 门禁" subtitle="规则源于项目文档并由 Python 校验器执行。" /><div className="rule-list">{[["规格来源", "成品规格与成型磨前规格必须独立；槽宽与导轨厚度取磨前数据。"], ["几何一致性", "相邻图元误差不大于 0.001 mm，闭合轮廓必须严格闭合。"], ["正式图纸", "release 只会在候选 DXF 通过图层、残留图元和尺寸定义点审计后输出。"], ["尺寸审计", "显示值、定义点与真实几何必须一致；双导轨定义点误差不大于 0.01 mm。"]].map(([title, detail]) => <article key={title}><span>✓</span><div><h3>{title}</h3><p>{detail}</p></div></article>)}</div></section>;
}

function DesktopSettingsPage({ onEngineState }: { onEngineState: (online: boolean) => void }) {
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [version, setVersion] = useState("1.0.2");
  const [availableUpdate, setAvailableUpdate] = useState<Update | null>(null);
  const [updateMessage, setUpdateMessage] = useState("尚未检查更新。");
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const tauri = "__TAURI_INTERNALS__" in window;

  const loadSettings = async () => {
    setSettingsError(null);
    try { setSettings(await api.settings()); }
    catch (error) { setSettingsError(error instanceof Error ? error.message : "设置读取失败。"); }
  };

  const checkForUpdate = async (quiet = false) => {
    if (!tauri) {
      if (!quiet) setUpdateMessage("浏览器开发模式不执行桌面更新。");
      return;
    }
    setChecking(true);
    if (!quiet) setUpdateMessage("正在连接 GitHub Releases…");
    try {
      const found = await check();
      setAvailableUpdate(found);
      setUpdateMessage(found ? `发现新版本 ${found.version}` : "当前已是最新版本。");
    } catch {
      setUpdateMessage("无法访问更新服务；离线 CAD 功能不受影响。");
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    void loadSettings();
    if (tauri) {
      void getVersion().then(setVersion).catch(() => undefined);
      void checkForUpdate(true);
    }
  }, []);

  const chooseAutoCad = async () => {
    if (!tauri) {
      setSettingsError("浏览器开发模式不能读取本机文件路径，请设置 CAD_AUTOCAD_CORE_CONSOLE。");
      return;
    }
    const selected = await open({ multiple: false, directory: false, title: "选择 AcCoreConsole" });
    if (typeof selected !== "string") return;
    try { setSettings(await api.updateSettings(selected)); setSettingsError(null); }
    catch (error) { setSettingsError(error instanceof Error ? error.message : "AutoCAD 路径保存失败。"); }
  };

  const installUpdate = async () => {
    if (!availableUpdate) return;
    setInstalling(true);
    setDownloadProgress(0);
    let downloaded = 0;
    let total = 0;
    let stage: "download" | "install" = "download";
    let engineStopped = false;
    try {
      setUpdateMessage(`正在下载并验证版本 ${availableUpdate.version}…`);
      await availableUpdate.download((event) => {
        if (event.event === "Started") total = event.data.contentLength ?? 0;
        if (event.event === "Progress") {
          downloaded += event.data.chunkLength;
          if (total > 0) setDownloadProgress(Math.min(100, Math.round((downloaded / total) * 100)));
        }
        if (event.event === "Finished") setDownloadProgress(100);
      }, { timeout: 10 * 60 * 1000 });
      setUpdateMessage("下载和签名验证已通过，正在关闭本地引擎并安装…");
      stage = "install";
      await invoke("prepare_for_update");
      engineStopped = true;
      onEngineState(false);
      await availableUpdate.install();
      setUpdateMessage("更新安装完成，正在重新启动应用…");
      await relaunch();
    } catch (error) {
      if (engineStopped) {
        try {
          await invoke("restart_engine");
          resetApiBaseUrl();
          await api.health();
          onEngineState(true);
        } catch {
          onEngineState(false);
        }
      }
      setUpdateMessage(updateFailureMessage(stage, error));
      setInstalling(false);
    }
  };

  const restartEngine = async () => {
    if (!tauri) return;
    onEngineState(false);
    try {
      await invoke("restart_engine");
      resetApiBaseUrl();
      await api.health();
      onEngineState(true);
      await loadSettings();
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : "本地 CAD 引擎重启失败。");
    }
  };

  return <section className="settings-page">
    <section className="panel page-panel">
      <PanelTitle number="本机" title="AutoCAD 与数据目录" subtitle="DWG 只调用本机 AutoCAD；未安装时仍可正常生成 DXF。" />
      {settingsError && <div className="alert error">{settingsError}</div>}
      <dl className="settings-list">
        <dt>应用数据目录</dt><dd>{settings?.app_data_root ?? "读取中…"}</dd>
        <dt>AutoCAD 状态</dt><dd>{settings?.autocad.available ? `已检测到 AutoCAD ${settings.autocad.version ?? "未知版本"}` : "未检测到；仍可生成和下载 DXF"}</dd>
        <dt>AcCoreConsole</dt><dd>{settings?.autocad.path ?? "未配置"}</dd>
      </dl>
      <div className="settings-actions">
        <button className="button secondary" onClick={() => void chooseAutoCad()}>手动选择 AcCoreConsole</button>
        <button className="button secondary" onClick={() => void api.updateSettings(null).then(setSettings)}>恢复自动检测</button>
        <button className="button secondary" disabled={!tauri} onClick={() => void restartEngine()}>重启本地 CAD 引擎</button>
      </div>
    </section>
    <section className="panel page-panel">
      <PanelTitle number="更新" title={`Forming Grinder CAD ${version}`} subtitle="更新包必须通过 Tauri 公钥签名验证，失败时保留当前版本。" />
      <p className="update-status">{updateMessage}</p>
      {availableUpdate && <div className="update-detail"><strong>版本 {availableUpdate.version}</strong><span>{availableUpdate.date ?? "发布时间未提供"}</span><p>{availableUpdate.body ?? "此版本未提供更新说明。"}</p></div>}
      {installing && <progress value={downloadProgress} max="100">{downloadProgress}%</progress>}
      <div className="settings-actions">
        <button className="button secondary" disabled={checking || installing || !tauri} onClick={() => void checkForUpdate()}>{checking ? "检查中…" : "检查更新"}</button>
        <button className="button primary" disabled={!availableUpdate || installing} onClick={() => void installUpdate()}>{installing ? `下载与安装 ${downloadProgress}%` : "下载并安装"}</button>
      </div>
    </section>
  </section>;
}

function updateFailureMessage(stage: "download" | "install", error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error ?? "");
  if (/signature|public key|verify|verification/i.test(detail)) {
    return "更新包签名验证失败，已拒绝安装；当前版本已保留。";
  }
  if (/timed?\s*out|timeout/i.test(detail)) {
    return "更新下载超时，请检查网络后重试；离线 CAD 功能不受影响。";
  }
  if (stage === "download") {
    return "更新包下载失败，可能无法稳定访问 GitHub；当前版本已保留。";
  }
  return "更新安装失败，本地 CAD 引擎已尝试恢复；当前版本已保留。";
}

function pageTitle(page: Page) { return ({ workspace: "导轨生成工作台", history: "历史任务", templates: "机台模板", rules: "规则与说明", settings: "设置与更新" })[page]; }

function applyMachine(machine: Machine, setter: Dispatch<SetStateAction<DesignInput>>) {
  setter((previous) => ({ ...previous, machine_type: machine.id, guide_rail_type: machine.guide_type, wheel_sequence: machine.wheel_positions, first_wheel_side: machineFirstSide(machine), template_coordinate_system: machine.template_coordinate_system }));
}

function resetWorkspace(setter: Dispatch<SetStateAction<DesignInput>>, setStep: Dispatch<SetStateAction<Step>>, setValidation: Dispatch<SetStateAction<ValidationResult | null>>, setGenerationState: Dispatch<SetStateAction<"idle" | "passed" | "failed">>, setError: Dispatch<SetStateAction<string | null>>) {
  setter(initialDesign); setStep(1); setValidation(null); setGenerationState("idle"); setError(null);
}
