import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { DrawingCanvas } from "./DrawingCanvas";
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
              {state === "completed"
                ? "✓"
                : state === "failed"
                  ? "!"
                  : index + 1}
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

function InputRail({
  design,
  machines,
  selectedMachine,
  onMachine,
  onUpdate,
}: {
  design: DesignInput;
  machines: Machine[];
  selectedMachine: Machine | null;
  onMachine: (id: string) => void;
  onUpdate: <K extends keyof DesignInput>(
    key: K,
    value: DesignInput[K],
  ) => void;
}) {
  return (
    <>
      <div className="rail-heading">
        <h2>输入参数</h2>
        <p>成品与磨前规格独立填写</p>
      </div>
      <div className="rail-form-section">
        <label>
          机台
          <select
            value={design.machine_type}
            onChange={(event) => onMachine(event.target.value)}
            disabled={!machines.length}
          >
            {!machines.length && <option>正在读取机台…</option>}
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
        {selectedMachine && (
          <small>
            {selectedMachine.guide_length} mm ·{" "}
            {selectedMachine.wheel_positions.join(" / ")} · 入丝口上限{" "}
            {mm(selectedMachine.section_center_opening_max)} mm
          </small>
        )}
      </div>
      <div className="rail-form-section">
        <label>
          成品形态
          <select
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
        <label>
          成品规格
          <input
            id="finished-spec"
            aria-describedby="finished-help"
            value={design.finished_spec}
            placeholder={
              design.product_shape_after === "tile_shape"
                ? "R30*R28*17.4*23.5*3.95"
                : "R9.6*8.6*42.6*2.1"
            }
            spellCheck={false}
            onChange={(event) => onUpdate("finished_spec", event.target.value)}
          />
        </label>
        <small id="finished-help">
          {design.product_shape_after === "tile_shape"
            ? "R外 * R内 * 弦宽 * 长度 * 厚度"
            : "R * 宽度 * 长度 * 厚度"}
        </small>
      </div>
      <div className="rail-form-section">
        <label>
          成型磨前形态
          <select
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
        <label>
          成型磨前规格
          <textarea
            id="preform-spec"
            aria-describedby="preform-help"
            rows={2}
            value={design.pre_grinding_spec}
            placeholder={
              design.product_shape_before === "rectangular_block"
                ? "42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)"
                : "R30*R30*17.4(+0.02/-0.02)*23.5*3.95(+0.01/-0.01)"
            }
            spellCheck={false}
            onChange={(event) =>
              onUpdate("pre_grinding_spec", event.target.value)
            }
          />
        </label>
        <small id="preform-help">
          {design.product_shape_before === "rectangular_block"
            ? "长度 * 宽度(上公差/下公差) * 厚度(上公差/下公差)"
            : "R * R * 弦宽(上公差/下公差) * 长度 * 厚度(上公差/下公差)"}
        </small>
      </div>
      <div className="rail-form-section">
        <div className="rail-field-pair">
          <label>
            侧部避空
            <input
              id="relief-input"
              value={design.relief}
              onChange={(event) => onUpdate("relief", event.target.value)}
            />
          </label>
          <label>
            砂轮半径（mm）
            <input
              type="number"
              min="1"
              step="0.01"
              value={design.wheel_radius}
              onChange={(event) =>
                onUpdate("wheel_radius", Number(event.target.value))
              }
            />
          </label>
        </div>
        <small>4-1 表示四处 Ø1.00 / R0.50；中心另有固定 2 × R0.50。</small>
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
  selectedMachine,
  job,
  onMachine,
  onUpdate,
  onNew,
  artifactActions,
}: {
  design: DesignInput;
  machines: Machine[];
  selectedMachine: Machine | null;
  job: Job;
  onMachine: (id: string) => void;
  onUpdate: <K extends keyof DesignInput>(
    key: K,
    value: DesignInput[K],
  ) => void;
  onNew: () => void;
  artifactActions: (file: GeneratedFile) => ReactNode;
}) {
  const { validation, progress } = job;
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
  return (
    <section className="workbench">
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
              selectedMachine={selectedMachine}
              onMachine={onMachine}
              onUpdate={onUpdate}
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
              {job.jobId && <p className="task-id">任务 {job.jobId}</p>}
              {job.connectionError && (
                <div className="rail-warning" role="alert">
                  <p>进度连接中断：{job.connectionError}</p>
                  <p>后台任务可能仍在执行，重新连接将读取同一任务。</p>
                  <button className="button secondary" onClick={job.reconnect}>
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
            {failed || inputError ? "!" : job.step === 2 || passed ? "✓" : "○"}
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
              {job.validating ? "正在解析…" : "确认计算 →"}
            </button>
          ) : job.step === 2 ? (
            <button
              key="generate"
              className="button primary"
              disabled={job.starting}
              onClick={() => void job.generate(design)}
            >
              生成并校验图纸 →
            </button>
          ) : passed || failed ? (
            <button key="new-task" className="button primary" onClick={onNew}>
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
