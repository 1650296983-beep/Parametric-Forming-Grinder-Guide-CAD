import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Clipboard,
  Loader2,
  Plus,
  RotateCcw,
  Sparkles,
  WifiOff,
  X,
} from "lucide-react";
import { DrawingCanvas } from "./DrawingCanvas";
import {
  exampleSpec,
  normalizeSpec,
  parseRelief,
  parseSpec,
  specHint,
  type SpecKind,
  type SpecShape,
} from "./spec";
import { useToast } from "./Toast";
import type {
  DesignInput,
  GeneratedFile,
  GenerationProgress,
  GenerationStage,
  Machine,
  ValidationResult,
} from "./types";
import type { useDesignJob } from "./useDesignJob";

type Job = ReturnType<typeof useDesignJob>;
const mm = (value: number | undefined | null) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
const stages: Array<[GenerationStage, string]> = [
  ["queued", "任务排队"],
  ["preparing", "读取配置与规格"],
  ["outline", "绘制机台轮廓"],
  ["cavity", "重建型腔与避空"],
  ["dimensions", "绑定真实尺寸"],
  ["candidate", "保存候选图纸"],
  ["preview", "生成预览"],
  ["validation", "完整几何校验"],
  ["promotion", "晋级正式图纸"],
  ["complete", "完成"],
];

function Elapsed({
  progress,
  starting,
  disconnected,
}: {
  progress: GenerationProgress | null;
  starting: boolean;
  disconnected: boolean;
}) {
  const [seconds, setSeconds] = useState(0);
  const start = progress?.events[0]?.at;
  const running = starting || progress?.status === "running";
  const finishedAt = progress?.events[progress.events.length - 1]?.at;
  const duration =
    !running && start && finishedAt
      ? Math.max(
          0,
          Math.floor(
            (new Date(finishedAt).getTime() - new Date(start).getTime()) / 1000,
          ),
        )
      : seconds;
  useEffect(() => {
    if (!running) return;
    const begin = start ? new Date(start).getTime() : Date.now();
    const update = () =>
      setSeconds(Math.max(0, Math.floor((Date.now() - begin) / 1000)));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [running, start]);
  return (
    <small className="elapsed">
      {running ? (disconnected ? "已等待" : "已运行") : "耗时"} {duration} 秒
    </small>
  );
}

function ProgressStages({ progress }: { progress: GenerationProgress | null }) {
  return (
    <ol className="true-progress">
      {stages.map(([id, label], index) => {
        const events =
          progress?.events.filter((event) => event.stage === id) ?? [];
        const event = events[events.length - 1];
        const state = event?.status ?? "waiting";
        return (
          <li key={id} className={state}>
            <span>
              {state === "completed" ? (
                <Check size={12} aria-hidden="true" />
              ) : state === "failed" ? (
                <AlertTriangle size={12} aria-hidden="true" />
              ) : (
                index + 1
              )}
            </span>
            <div>
              <strong>{label}</strong>
              {progress?.stage === id && <small>{progress.message}</small>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function SpecField({
  id,
  label,
  kind,
  shape,
  value,
  onChange,
}: {
  id: string;
  label: string;
  kind: SpecKind;
  shape: SpecShape;
  value: string;
  onChange: (value: string) => void;
}) {
  const preview = parseSpec(value, kind, shape);
  const input = useRef<HTMLTextAreaElement>(null);
  const helpId = `${id}-help`;
  const errorId = `${id}-error`;

  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.max(element.scrollHeight, 42)}px`;
  }, [value]);

  return (
    <div className="spec-field">
      <div className="field-heading">
        <label htmlFor={id}>{label}</label>
        <button
          type="button"
          className="link-button"
          onClick={() => onChange(exampleSpec(kind, shape))}
        >
          <Sparkles size={13} aria-hidden="true" />
          载入示例
        </button>
      </div>
      <textarea
        id={id}
        ref={input}
        className="spec-input"
        rows={1}
        value={value}
        placeholder={exampleSpec(kind, shape)}
        spellCheck={false}
        aria-invalid={Boolean(preview.error)}
        aria-describedby={preview.error ? `${helpId} ${errorId}` : helpId}
        onChange={(event) => onChange(event.target.value)}
        onBlur={() => {
          if (preview.normalized && preview.normalized !== value) {
            onChange(preview.normalized);
          }
        }}
        onPaste={(event) => {
          const text = event.clipboardData.getData("text");
          const normalized = normalizeSpec(text);
          if (normalized !== text) {
            event.preventDefault();
            onChange(normalized);
          }
        }}
      />
      <div className="spec-meta">
        <small id={helpId}>{specHint(kind, shape)}</small>
        {preview.normalized && preview.normalized !== value && (
          <span className="spec-normalized">
            将归一化为 {preview.normalized}
          </span>
        )}
      </div>
      {preview.tokens.length > 0 && !preview.error && (
        <ul className="spec-tokens" aria-label={`${label}解析结果`}>
          {preview.tokens.map((token, index) => (
            <li key={`${token.label}-${index}`}>
              <span>{token.label}</span>
              <strong>
                {token.radius ? "R" : ""}
                {token.value ?? "—"}
                {token.tolerance && <small> ({token.tolerance})</small>}
              </strong>
            </li>
          ))}
        </ul>
      )}
      {preview.error && (
        <p className="field-error" id={errorId} role="alert">
          <AlertTriangle size={13} aria-hidden="true" />
          {preview.error}
        </p>
      )}
      {!preview.error && preview.warning && (
        <p className="field-warning">
          <AlertTriangle size={13} aria-hidden="true" />
          {preview.warning}
        </p>
      )}
    </div>
  );
}

function InputRail({
  design,
  machines,
  machinesLoading,
  machinesError,
  selectedMachine,
  onMachine,
  onUpdate,
  onRetryMachines,
}: {
  design: DesignInput;
  machines: Machine[];
  machinesLoading: boolean;
  machinesError: string | null;
  selectedMachine: Machine | null;
  onMachine: (id: string) => void;
  onUpdate: <K extends keyof DesignInput>(
    key: K,
    value: DesignInput[K],
  ) => void;
  onRetryMachines: () => void;
}) {
  const relief = parseRelief(design.relief);
  const wheelRadiusValid =
    Number.isFinite(design.wheel_radius) && design.wheel_radius > 0;
  return (
    <>
      <div className="rail-heading">
        <h2>输入参数</h2>
        <p>成品与磨前规格独立填写</p>
      </div>
      <div className="rail-form-section">
        <label htmlFor="machine-select">
          机台
          <select
            id="machine-select"
            value={design.machine_type}
            onChange={(event) => onMachine(event.target.value)}
            disabled={!machines.length}
            aria-busy={machinesLoading}
          >
            {!machines.length && (
              <option value="">
                {machinesLoading
                  ? "正在读取机台…"
                  : machinesError
                    ? "机台配置读取失败"
                    : "没有可用的机台"}
              </option>
            )}
            {machines.map((machine) => (
              <option
                key={machine.id}
                value={machine.id}
                disabled={!machine.supported_by_web_generation}
              >
                {machine.name}
              </option>
            ))}
          </select>
        </label>
        {machinesError && (
          <div className="inline-error" role="alert">
            <AlertTriangle size={14} aria-hidden="true" />
            <span>{machinesError}</span>
            <button
              type="button"
              className="link-button"
              onClick={onRetryMachines}
              disabled={machinesLoading}
            >
              {machinesLoading ? (
                <Loader2 className="spin" size={13} aria-hidden="true" />
              ) : (
                <RotateCcw size={13} aria-hidden="true" />
              )}
              重试
            </button>
          </div>
        )}
        {selectedMachine && (
          <small>
            {selectedMachine.guide_length} mm ·{" "}
            {selectedMachine.wheel_positions.join(" / ")} · 入丝口上限{" "}
            {mm(selectedMachine.section_center_opening_max)} mm
          </small>
        )}
        {selectedMachine && !selectedMachine.supported_by_web_generation && (
          <p className="field-warning">
            <AlertTriangle size={13} aria-hidden="true" />
            该机台暂不支持网页端生成，请改用桌面引擎。
          </p>
        )}
      </div>
      <div className="rail-form-section">
        <label htmlFor="finished-shape">
          成品形态
          <select
            id="finished-shape"
            value={design.product_shape_after}
            onChange={(event) =>
              onUpdate(
                "product_shape_after",
                event.target.value as DesignInput["product_shape_after"],
              )
            }
          >
            <option value="bread_shape">馒头型（单 R）</option>
            <option value="tile_shape">瓦型（双 R）</option>
          </select>
        </label>
        <SpecField
          id="finished-spec"
          label="成品规格"
          kind="finished"
          shape={design.product_shape_after}
          value={design.finished_spec}
          onChange={(value) => onUpdate("finished_spec", value)}
        />
      </div>
      <div className="rail-form-section">
        <label htmlFor="preform-shape">
          成型磨前形态
          <select
            id="preform-shape"
            value={design.product_shape_before}
            onChange={(event) =>
              onUpdate(
                "product_shape_before",
                event.target.value as DesignInput["product_shape_before"],
              )
            }
          >
            <option value="rectangular_block">方块</option>
            <option value="same_r_tile">同 R 瓦型</option>
          </select>
        </label>
        <SpecField
          id="preform-spec"
          label="成型磨前规格"
          kind="preform"
          shape={design.product_shape_before}
          value={design.pre_grinding_spec}
          onChange={(value) => onUpdate("pre_grinding_spec", value)}
        />
      </div>
      <div className="rail-form-section">
        <div className="rail-field-pair">
          <label>
            侧部避空
            <input
              id="relief-input"
              value={design.relief}
              spellCheck={false}
              aria-invalid={!relief && Boolean(design.relief)}
              aria-describedby="relief-help"
              onChange={(event) => onUpdate("relief", event.target.value)}
              onBlur={() =>
                onUpdate("relief", normalizeSpec(design.relief))
              }
            />
          </label>
          <label>
            砂轮半径（mm）
            <input
              type="number"
              min="1"
              step="0.01"
              value={design.wheel_radius}
              aria-invalid={!wheelRadiusValid}
              onChange={(event) =>
                onUpdate("wheel_radius", Number(event.target.value))
              }
            />
          </label>
        </div>
        <small id="relief-help">
          {relief
            ? `${relief.count} 处 Ø${relief.diameter.toFixed(2)} / R${relief.radius.toFixed(2)}；中心另有固定 2 × R0.50。`
            : "4-1 表示四处 Ø1.00 / R0.50；中心另有固定 2 × R0.50。"}
        </small>
        {!relief && Boolean(design.relief) && (
          <p className="field-error" role="alert">
            <AlertTriangle size={13} aria-hidden="true" />
            避空格式应为“数量-直径”，例如 4-1。
          </p>
        )}
        {!wheelRadiusValid && (
          <p className="field-error" role="alert">
            <AlertTriangle size={13} aria-hidden="true" />
            砂轮半径必须大于 0。
          </p>
        )}
      </div>
      <details className="process-details">
        <summary>工艺选项</summary>
        <div>
          {(
            [
              [
                "single_side_or_high_requirement",
                "磨单边 / 高要求",
                "厚度间隙采用 0.09 mm",
              ],
              [
                "high_symmetry_requirement",
                "高对称度槽宽",
                "槽宽间隙采用 0.03 mm",
              ],
              ["large_tile_clearance", "大瓦放宽槽宽", "槽宽间隙采用 0.08 mm"],
            ] as const
          ).map(([key, label, hint]) => (
            <label className="check-option" key={key}>
              <input
                type="checkbox"
                checked={design[key]}
                disabled={
                  key === "large_tile_clearance"
                    ? design.high_symmetry_requirement
                    : key === "high_symmetry_requirement"
                      ? design.large_tile_clearance
                      : false
                }
                onChange={(event) => onUpdate(key, event.target.checked)}
              />
              <span>
                {label}
                <small>{hint}</small>
              </span>
            </label>
          ))}
          <button
            type="button"
            className="link-button reset-options"
            onClick={() => {
              onUpdate("single_side_or_high_requirement", false);
              onUpdate("high_symmetry_requirement", false);
              onUpdate("large_tile_clearance", false);
            }}
            disabled={
              !design.single_side_or_high_requirement &&
              !design.high_symmetry_requirement &&
              !design.large_tile_clearance
            }
          >
            <RotateCcw size={13} aria-hidden="true" />
            重置工艺选项
          </button>
        </div>
      </details>
      <p className="rail-note">
        所有尺寸单位为 mm。完整解析与工艺计算由 CAD 引擎执行。
      </p>
    </>
  );
}

function SnapshotRows({
  design,
  machine,
}: {
  design: DesignInput;
  machine: Machine | null;
}) {
  return (
    <dl className="snapshot-rows">
      <dt>机台</dt>
      <dd>
        {machine?.name ?? design.machine_type}
        <small>
          {machine?.guide_length} mm · {design.wheel_sequence.join(" / ")}
        </small>
      </dd>
      <dt>成品</dt>
      <dd>{design.finished_spec}</dd>
      <dt>磨前</dt>
      <dd>{design.pre_grinding_spec}</dd>
    </dl>
  );
}

function CalculationRows({ validation }: { validation: ValidationResult }) {
  const d = validation.derived;
  return (
    <div className="calculation-rows">
      <div className="main-value">
        <span>槽宽</span>
        <strong>
          {mm(d.slot_width)} <small>mm</small>
        </strong>
        <p>±{mm(d.slot_width_tolerance)} mm</p>
      </div>
      <div>
        <span>导轨厚度</span>
        <strong>
          {mm(d.guide_thickness)} <small>mm</small>
        </strong>
      </div>
      <div>
        <span>入丝口</span>
        <strong>
          {mm(d.center_opening)} <small>mm</small>
        </strong>
        <p>
          槽宽 × 30%，机台上限 {mm(d.opening_max)} mm
          <br />
          向下保留两位小数
        </p>
      </div>
      <div>
        <span>侧部避空</span>
        <strong>
          4 × Ø{mm(d.relief_diameter)}{" "}
          <small>mm / R{mm(d.relief_radius)}</small>
        </strong>
      </div>
      <div>
        <span>中心过渡</span>
        <strong>
          {validation.derived.center_transition_count} × R
          {mm(d.center_transition_radius)}
        </strong>
      </div>
      <div>
        <span>砂轮半径</span>
        <strong>
          R{mm(validation.decision.process_options.wheel_radius)}{" "}
          <small>mm</small>
        </strong>
      </div>
      {validation.decision.arc_radius != null && (
        <div>
          <span>型腔 R</span>
          <strong>R{mm(validation.decision.arc_radius)}</strong>
          <p>
            {validation.decision.R_form_source === "finished_product_max_radius"
              ? "取成品双 R 中的较大值"
              : "取成型磨前规格"}{" "}
            ·{" "}
            {validation.decision.arc_side === "lower"
              ? "下侧"
              : validation.decision.arc_side === "upper"
                ? "上侧"
                : validation.decision.arc_side}
          </p>
        </div>
      )}
    </div>
  );
}

export function Workbench({
  design,
  machines,
  machinesLoading,
  machinesError,
  selectedMachine,
  job,
  onMachine,
  onUpdate,
  onNew,
  onRetryMachines,
  draftRestored,
  onDismissDraft,
  onClearDraft,
  artifactActions,
}: {
  design: DesignInput;
  machines: Machine[];
  machinesLoading: boolean;
  machinesError: string | null;
  selectedMachine: Machine | null;
  job: Job;
  onMachine: (id: string) => void;
  onUpdate: <K extends keyof DesignInput>(
    key: K,
    value: DesignInput[K],
  ) => void;
  onNew: () => void;
  onRetryMachines: () => void;
  draftRestored: boolean;
  onDismissDraft: () => void;
  onClearDraft: () => void;
  artifactActions: (file: GeneratedFile) => ReactNode;
}) {
  const { validation, progress } = job;
  const toast = useToast();
  const rail = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    if (rail.current) rail.current.scrollTop = 0;
  }, [job.step, progress?.status]);
  useLayoutEffect(() => {
    if (job.error && rail.current) rail.current.scrollTop = 0;
  }, [job.error]);
  const passed =
    progress?.status === "passed" &&
    progress.result?.ok &&
    progress.result.release_allowed;
  const gateMismatch = progress?.status === "passed" && !passed;
  const failed = progress?.status === "failed" || gateMismatch;
  const inputError = job.step === 1 && Boolean(job.error);
  const files = Object.entries(progress?.result?.files ?? {});
  const formalFiles = files.filter(
    ([key]) => key === "release_dxf" || key === "release_dwg",
  );
  const otherFiles = files.filter(
    ([key]) => key !== "release_dxf" && key !== "release_dwg",
  );
  const scene =
    job.step === 1
      ? null
      : gateMismatch
        ? (validation?.scene ?? null)
        : (progress?.scene ?? validation?.scene ?? null);
  const canValidate =
    !!selectedMachine &&
    !!design.finished_spec.trim() &&
    !!design.pre_grinding_spec.trim() &&
    !job.validating;
  const back = () => {
    job.invalidate();
    requestAnimationFrame(() =>
      document
        .getElementById(
          /避空|relief|相交/.test(job.error ?? "")
            ? "relief-input"
            : "preform-spec",
        )
        ?.focus(),
    );
  };
  const copyJobId = async () => {
    if (!job.jobId) return;
    try {
      await navigator.clipboard.writeText(job.jobId);
      toast.success("任务 ID 已复制");
    } catch {
      toast.error("无法访问剪贴板，请手动复制任务 ID。");
    }
  };
  return (
    <section
      className="workbench"
      onKeyDown={(event) => {
        if (!(event.metaKey || event.ctrlKey) || event.key !== "Enter") return;
        if (job.step === 1 && canValidate) {
          event.preventDefault();
          void job.validate(design);
        } else if (job.step === 2 && !job.starting) {
          event.preventDefault();
          void job.generate(design);
        }
      }}
    >
      <ol className="workbench-steps">
        {["输入参数", "确认计算", "生成结果"].map((label, index) => (
          <li
            key={label}
            className={
              job.step === index + 1
                ? "current"
                : job.step > index + 1
                  ? "done"
                  : ""
            }
          >
            <span>{job.step > index + 1 ? "✓" : index + 1}</span>
            <strong>{label}</strong>
          </li>
        ))}
      </ol>
      <div className="workbench-body">
        <aside ref={rail} className="parameter-rail">
          {draftRestored && job.step === 1 && (
            <div className="draft-notice" role="status">
              <RotateCcw size={15} aria-hidden="true" />
              <div>
                <strong>已恢复上次草稿</strong>
                <span>输入保存在本机，可直接继续修改。</span>
              </div>
              <button
                type="button"
                className="link-button"
                onClick={onDismissDraft}
              >
                保留
              </button>
              <button
                type="button"
                className="link-button danger"
                onClick={onClearDraft}
              >
                清除
              </button>
            </div>
          )}
          {gateMismatch && (
            <div className="workbench-error" role="alert">
              任务状态与正式图纸门禁结果不一致，未允许打开或导出正式图纸。请查看校验报告并重新生成。
            </div>
          )}
          {job.error && (
            <div className="workbench-error" role="alert">
              {job.error}
            </div>
          )}
          {job.step === 1 ? (
            <InputRail
              design={design}
              machines={machines}
              machinesLoading={machinesLoading}
              machinesError={machinesError}
              selectedMachine={selectedMachine}
              onMachine={onMachine}
              onUpdate={onUpdate}
              onRetryMachines={onRetryMachines}
            />
          ) : job.step === 2 && validation ? (
            <>
              <div className="rail-heading">
                <h2>计算结果</h2>
                <p>当前输入已解析</p>
              </div>
              <SnapshotRows
                design={job.reviewed ?? design}
                machine={validation.machine}
              />
              <CalculationRows validation={validation} />
              {validation.decision.warnings.map((warning) => (
                <p className="rail-warning" key={warning}>
                  {warning}
                </p>
              ))}
              {validation.parsed && (
                <details className="parsed-details">
                  <summary>查看引擎解析字段</summary>
                  {Object.entries(validation.parsed).map(([group, values]) => (
                    <div key={group}>
                      <strong>{group === "finished" ? "成品" : "磨前"}</strong>
                      <dl>
                        {Object.entries(values).map(([key, value]) => (
                          <div key={key}>
                            <dt>{key}</dt>
                            <dd>
                              {typeof value === "number"
                                ? mm(value)
                                : typeof value === "object"
                                  ? JSON.stringify(value)
                                  : String(value)}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  ))}
                </details>
              )}
              <p className="rail-note">正式图纸仍需通过完整几何校验。</p>
            </>
          ) : (
            <>
              <div
                className={`rail-heading ${failed ? "failed" : passed ? "passed" : ""}`}
              >
                <h2>
                  {job.connectionError
                    ? "等待恢复连接"
                    : passed
                      ? "图纸已通过校验"
                      : failed
                        ? "图纸生成被阻断"
                        : "正在绘制与校验"}
                </h2>
                <p>
                  {job.starting
                    ? "正在提交当前输入快照…"
                    : (progress?.message ?? "正在连接当前任务…")}
                </p>
                <Elapsed
                  progress={progress}
                  starting={job.starting}
                  disconnected={Boolean(job.connectionError)}
                />
              </div>
              <div className="stage-announcement sr-only" role="status">
                {progress?.stage} {progress?.message}
              </div>
              {job.jobId && (
                <p className="task-id">
                  <span>任务</span>
                  <code>{job.jobId}</code>
                  <button
                    type="button"
                    className="icon-button mini"
                    onClick={() => void copyJobId()}
                    title="复制任务 ID"
                    aria-label="复制任务 ID"
                  >
                    <Clipboard size={13} aria-hidden="true" />
                  </button>
                </p>
              )}
              {job.connectionError && (
                <div className="rail-warning" role="alert">
                  <p>
                    <WifiOff size={14} aria-hidden="true" />
                    进度连接中断：{job.connectionError}
                  </p>
                  <p>后台任务可能仍在执行，重新连接将读取同一任务。</p>
                  <button className="button secondary" onClick={job.reconnect}>
                    <RotateCcw size={14} aria-hidden="true" />
                    重新连接任务
                  </button>
                </div>
              )}
              {passed ? (
                <>
                  <div className="release-gate">
                    <span>✓</span>正式 release 已通过完整门禁
                  </div>
                  {formalFiles.map(([key, file]) => (
                    <div className="formal-file" key={`${job.jobId}-${key}`}>
                      <strong>{file.label}</strong>
                      <small>{file.name}</small>
                      {artifactActions(file)}
                    </div>
                  ))}
                  {validation && <CalculationRows validation={validation} />}
                  <details className="secondary-files">
                    <summary>校验报告与辅助文件（{otherFiles.length}）</summary>
                    {otherFiles.map(([key, file]) => (
                      <div key={`${job.jobId}-${key}`}>
                        <strong>{file.label}</strong>
                        {artifactActions(file)}
                      </div>
                    ))}
                  </details>
                </>
              ) : (
                <ProgressStages progress={progress} />
              )}
              <details className="generation-snapshot">
                <summary>本次输入快照</summary>
                <SnapshotRows
                  design={job.reviewed ?? design}
                  machine={selectedMachine}
                />
              </details>
            </>
          )}
        </aside>
        <DrawingCanvas scene={scene} taskId={job.jobId} />
      </div>
      <footer className="workbench-actions">
        <div
          className={`action-state ${failed || inputError ? "failed" : job.step === 2 || passed ? "passed" : ""}`}
        >
          <span>
            {failed || inputError ? (
              <AlertTriangle size={14} aria-hidden="true" />
            ) : job.step === 2 || passed ? (
              <Check size={14} aria-hidden="true" />
            ) : (
              "○"
            )}
          </span>
          <p>
            {job.step === 1
              ? inputError
                ? "输入未通过，请查看参数栏说明"
                : job.validating
                  ? "正在解析当前输入…"
                  : "填写成品与磨前规格，确认后查看真实型腔"
              : job.step === 2
                ? "当前输入计算通过 · 尚未生成正式图纸"
                : passed
                  ? "正式图纸已晋级 · 文件保存在本地任务中"
                  : failed
                    ? "保留本次输入，请返回修改后重试"
                    : job.connectionError
                      ? "进度连接中断 · 可重新连接同一任务"
                      : (progress?.message ?? "正在提交任务…")}
          </p>
        </div>
        <div
          className="action-buttons"
          onClickCapture={(event) => {
            // A second click must not activate a different action after a fast step change.
            if (event.detail > 1) {
              event.preventDefault();
              event.stopPropagation();
            }
          }}
          onKeyDownCapture={(event) => {
            if (event.repeat && (event.key === "Enter" || event.key === " "))
              event.preventDefault();
          }}
        >
          {job.step !== 1 && (
            <button className="button secondary" onClick={back}>
              {failed ? "返回修正参数" : "返回修改"}
            </button>
          )}
          {job.step === 1 ? (
            <button
              key="validate"
              className="button primary"
              disabled={!canValidate}
              onClick={() => void job.validate(design)}
            >
              {job.validating ? (
                <>
                  <Loader2 className="spin" size={15} aria-hidden="true" />
                  正在解析…
                </>
              ) : (
                <>
                  确认计算
                  <ArrowRight size={15} aria-hidden="true" />
                </>
              )}
            </button>
          ) : job.step === 2 ? (
            <button
              key="generate"
              className="button primary"
              disabled={job.starting}
              onClick={() => void job.generate(design)}
            >
              生成并校验图纸
              <ArrowRight size={15} aria-hidden="true" />
            </button>
          ) : passed || failed ? (
            <button key="new-task" className="button primary" onClick={onNew}>
              <Plus size={15} aria-hidden="true" />
              新建任务
            </button>
          ) : (
            <button key="generating" className="button primary" disabled>
              {job.starting
                ? "正在提交…"
                : job.connectionError
                  ? "等待恢复连接"
                  : "正在生成…"}
            </button>
          )}
        </div>
      </footer>
    </section>
  );
}
