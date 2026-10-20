import { useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { open, save } from "@tauri-apps/plugin-dialog";
import { writeFile } from "@tauri-apps/plugin-fs";
import { relaunch } from "@tauri-apps/plugin-process";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { api } from "./api";
import { Workbench } from "./Workbench";
import { useDesignJob } from "./useDesignJob";
import { resetApiBaseUrl } from "./api";
import type {
  DesignInput,
  DesktopSettings,
  GeneratedFile,
  Machine,
  TaskDetail,
  TaskHistoryResult,
  TaskStatus,
  TaskSummary,
} from "./types";

type Page = "workspace" | "history" | "templates" | "rules" | "settings";

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

const isTauri = () => "__TAURI_INTERNALS__" in window;

const saveGeneratedFile = async (
  file: GeneratedFile,
): Promise<string | null> => {
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
  if (
    source.protocol !== "http:" ||
    !["127.0.0.1", "localhost"].includes(source.hostname)
  ) {
    throw new Error("只允许保存本地 CAD 引擎生成的文件。");
  }

  const safeName = file.name.replace(/[<>:"/\\|?*\u0000-\u001F]/g, "_");
  const extension = safeName.includes(".")
    ? safeName.split(".").pop()?.toLowerCase()
    : undefined;
  const target = await save({
    defaultPath: safeName,
    filters: extension
      ? [{ name: file.label, extensions: [extension] }]
      : undefined,
  });
  if (!target) return null;

  const response = await fetch(source);
  if (!response.ok)
    throw new Error(`本地文件读取失败（HTTP ${response.status}）。`);
  const content = new Uint8Array(await response.arrayBuffer());
  if (content.byteLength === 0) throw new Error("生成文件为空，未执行保存。");
  await writeFile(target, content);
  return target;
};

function NavIcon({ kind }: { kind: Page }) {
  const paths: Record<Page, string> = {
    workspace: "M12 2 3 7v10l9 5 9-5V7ZM3 7l9 5 9-5M12 12v10",
    history: "M12 3a9 9 0 1 0 9 9 9 9 0 0 0-9-9Zm0 4v6l4 2",
    templates: "M6 2h8l4 4v16H6ZM14 2v5h4M9 11h6M9 15h6M9 18h5",
    rules:
      "M12 5C8 2 3 3 2 4v16c3-2 7-1 10 1 3-2 7-3 10-1V4c-3-2-7-1-10 1Zm0 0v16",
    settings:
      "m10 2-1 3-3 1-3-1-2 4 2 2v3l-2 2 2 4 3-1 3 1 1 3h4l1-3 3-1 3 1 2-4-2-2v-3l2-2-2-4-3 1-3-1-1-3ZM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
  };
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d={paths[kind]} />
    </svg>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("workspace");
  const [machines, setMachines] = useState<Machine[]>([]);
  const [design, setDesign] = useState<DesignInput>(initialDesign);
  const [isServiceOnline, setIsServiceOnline] = useState(false);
  const [taskHistory, setTaskHistory] = useState<TaskHistoryResult | null>(
    null,
  );
  const [isTasksLoading, setIsTasksLoading] = useState(false);
  const [taskHistoryError, setTaskHistoryError] = useState<string | null>(null);
  const refresh = () =>
    refreshTaskHistory(setTaskHistory, setIsTasksLoading, setTaskHistoryError);
  const job = useDesignJob(() => void refresh(), setIsServiceOnline);

  useEffect(() => {
    let active = true;
    void api
      .health()
      .then(() => {
        if (active) setIsServiceOnline(true);
        return api.machines();
      })
      .then((items) => {
        if (!active) return;
        setMachines(items);
        setDesign((previous) => {
          const machine =
            items.find((item) => item.id === previous.machine_type) ?? items[0];
          return machine
            ? {
                ...previous,
                machine_type: machine.id,
                guide_rail_type: machine.guide_type,
                wheel_sequence: machine.wheel_positions,
                first_wheel_side: machineFirstSide(machine),
                template_coordinate_system: machine.template_coordinate_system,
              }
            : previous;
        });
      })
      .catch(() => {
        if (active) setIsServiceOnline(false);
      });
    void refresh();
    if ("__TAURI_INTERNALS__" in window) void check().catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const release = () =>
      document
        .querySelectorAll("button.pointer-pressed")
        .forEach((button) => button.classList.remove("pointer-pressed"));
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
    window.addEventListener("blur", release);
    return () => {
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
      window.removeEventListener("blur", release);
    };
  }, []);
  const selectedMachine = useMemo(
    () =>
      machines.find((machine) => machine.id === design.machine_type) ?? null,
    [design.machine_type, machines],
  );
  const newTask = () => {
    job.invalidate();
    setDesign({ ...initialDesign });
    setPage("workspace");
  };
  const update = <K extends keyof DesignInput>(
    key: K,
    value: DesignInput[K],
  ) => {
    job.invalidate();
    setDesign((previous) => ({ ...previous, [key]: value }));
  };
  const selectMachine = (id: string) => {
    const machine = machines.find((item) => item.id === id);
    if (!machine) return;
    job.invalidate();
    applyMachine(machine, setDesign);
  };
  const copyTask = (input: DesignInput) => {
    job.invalidate();
    setDesign(JSON.parse(JSON.stringify(input)));
    setPage("workspace");
  };
  return (
    <div
      className="app-shell"
      onPointerDownCapture={(event) => {
        if (event.pointerType === "mouse" && event.button === 0)
          (event.target as HTMLElement)
            .closest("button:not(:disabled)")
            ?.classList.add("pointer-pressed");
      }}
    >
      <aside className="sidebar">
        <button
          className="brand-text"
          onClick={() => setPage("workspace")}
          aria-label="返回导轨工作台"
        >
          <span className="brand-glyph">
            <NavIcon kind="workspace" />
          </span>
          <span>
            <strong>成型磨导轨</strong>
            <small>参数化生成器</small>
          </span>
        </button>
        <nav>
          {navItems.map((item) => (
            <button
              className={`nav-item ${page === item.id ? "active" : ""}`}
              key={item.id}
              aria-label={item.label}
              aria-current={page === item.id ? "page" : undefined}
              onClick={() => setPage(item.id)}
            >
              <NavIcon kind={item.id} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div
          className={`sidebar-bottom ${isServiceOnline && !job.connectionError ? "" : "offline"}`}
        >
          <span className="connection-dot" />
          {job.connectionError
            ? "进度连接中断"
            : isServiceOnline
              ? "本地引擎已连接"
              : "本地引擎未连接"}
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <div>
            <h1>{pageTitle(page)}</h1>
            <p>依据磨前规格，生成可复核的加工图纸</p>
          </div>
          <div className="topbar-actions">
            <span className="local-task-label">本地任务</span>
            <button className="button primary" onClick={newTask}>
              新建任务
            </button>
          </div>
        </header>
        {page === "workspace" && (
          <Workbench
            design={design}
            machines={machines}
            selectedMachine={selectedMachine}
            job={job}
            onMachine={selectMachine}
            onUpdate={update}
            onNew={newTask}
            artifactActions={(file) => (
              <ArtifactActions
                key={`${file.task_id}-${file.name}`}
                file={file}
              />
            )}
          />
        )}
        {page === "history" && (
          <History
            history={taskHistory}
            isLoading={isTasksLoading}
            error={taskHistoryError}
            initialTaskId={null}
            onRefresh={refresh}
            onCopy={copyTask}
          />
        )}
        {page === "templates" && <Templates machines={machines} />}
        {page === "rules" && <Rules />}
        {page === "settings" && (
          <DesktopSettingsPage onEngineState={setIsServiceOnline} />
        )}
      </main>
    </div>
  );
}

function PanelTitle({
  number,
  title,
  subtitle,
}: {
  number: string;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="panel-title">
      <span>{number}</span>
      <div>
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
    </div>
  );
}

function ArtifactSaveButton({ file }: { file: GeneratedFile }) {
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">(
    "idle",
  );
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
      setMessage(
        error instanceof Error
          ? `保存失败：${error.message}`
          : "保存失败，请重新选择保存位置。",
      );
    }
  };

  return (
    <div className={`artifact-save ${state}`}>
      <button
        type="button"
        onClick={() => void saveFile()}
        disabled={state === "saving"}
      >
        {state === "saving"
          ? "保存中…"
          : state === "saved"
            ? "再次另存副本"
            : "另存副本"}
      </button>
      {message && (
        <small role="status" title={message}>
          {message}
        </small>
      )}
    </div>
  );
}

function ArtifactOpenButton({ file }: { file: GeneratedFile }) {
  const [state, setState] = useState<"idle" | "opening" | "opened" | "error">(
    "idle",
  );
  const [message, setMessage] = useState<string | null>(null);
  const isDrawing = /\.(dxf|dwg)$/i.test(file.name);
  const canOpen = Boolean(file.can_open && file.task_id && file.relative_path);

  if (!canOpen) return null;

  const openFile = async () => {
    setState("opening");
    setMessage(null);
    try {
      await api.openTaskFile(file.task_id!, file.relative_path!);
      setState("opened");
      setMessage("已交给本机默认程序打开。");
    } catch (openError) {
      setState("error");
      setMessage(
        openError instanceof Error ? openError.message : "文件打开失败。",
      );
    }
  };

  return (
    <div className={`artifact-open ${state}`}>
      <button
        type="button"
        onClick={() => void openFile()}
        disabled={state === "opening"}
      >
        {state === "opening"
          ? "正在打开…"
          : isDrawing
            ? "打开图纸"
            : "打开文件"}
      </button>
      {message && (
        <small role="status" title={message}>
          {message}
        </small>
      )}
    </div>
  );
}

function ArtifactActions({ file }: { file: GeneratedFile }) {
  return (
    <div className="artifact-actions">
      <ArtifactOpenButton file={file} />
      <ArtifactSaveButton file={file} />
    </div>
  );
}

function History({
  history,
  isLoading,
  error,
  initialTaskId,
  onRefresh,
  onCopy,
}: {
  history: TaskHistoryResult | null;
  isLoading: boolean;
  error: string | null;
  initialTaskId: string | null;
  onRefresh: () => Promise<void>;
  onCopy: (input: DesignInput) => void;
}) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<TaskStatus | "all">("all");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(
    initialTaskId,
  );
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(
    new Set(),
  );
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    if (!selectedTaskId) {
      setIsDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setIsDetailLoading(true);
    void api
      .task(selectedTaskId, controller.signal)
      .then((result) => {
        if (active && result.task_id === selectedTaskId) setDetail(result);
      })
      .catch((loadError) => {
        if (active && !controller.signal.aborted)
          setDetailError(
            loadError instanceof Error
              ? loadError.message
              : "任务详情读取失败。",
          );
      })
      .finally(() => {
        if (active) setIsDetailLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [selectedTaskId]);

  const normalizedQuery = query.trim().toLowerCase();
  const tasks = (history?.items ?? []).filter((task) => {
    if (statusFilter !== "all" && task.status !== statusFilter) return false;
    if (!normalizedQuery) return true;
    return [
      task.task_id,
      task.finished_spec,
      task.pre_grinding_spec,
      task.machine_name,
    ].some((value) => value.toLowerCase().includes(normalizedQuery));
  });
  const selectableTaskIds = tasks
    .filter((task) => task.can_delete)
    .map((task) => task.task_id);
  const allSelectableTasksSelected =
    selectableTaskIds.length > 0 &&
    selectableTaskIds.every((taskId) => selectedTaskIds.has(taskId));

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
    const confirmed = window.confirm(
      `确认删除任务 ${task.finished_spec || task.task_id}？\n删除后 DXF、DWG、预览和报告均无法恢复。`,
    );
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
      setDeleteError(
        deleteTaskError instanceof Error
          ? deleteTaskError.message
          : "历史任务删除失败。",
      );
    } finally {
      setDeletingTaskId(null);
    }
  };

  const deleteSelectedTasks = async () => {
    const taskIds = Array.from(selectedTaskIds);
    if (taskIds.length === 0) return;
    const confirmed = window.confirm(
      `确认批量删除已选择的 ${taskIds.length} 个任务？\n删除后 DXF、DWG、预览和报告均无法恢复。`,
    );
    if (!confirmed) return;
    setIsBulkDeleting(true);
    setDeleteError(null);
    setDeleteMessage(null);
    try {
      const result = await api.deleteTasks(taskIds);
      const deleted = new Set(result.deleted);
      setSelectedTaskIds(
        (previous) =>
          new Set(
            Array.from(previous).filter((taskId) => !deleted.has(taskId)),
          ),
      );
      if (selectedTaskId && deleted.has(selectedTaskId))
        setSelectedTaskId(null);
      const skippedSummary =
        result.skipped.length > 0
          ? `，跳过 ${result.skipped.length} 项：${result.skipped.map((item) => `${item.task_id} ${item.reason}`).join("；")}`
          : "";
      setDeleteMessage(
        `已删除 ${result.deleted.length} 个任务${skippedSummary}`,
      );
      await onRefresh();
    } catch (bulkDeleteError) {
      setDeleteError(
        bulkDeleteError instanceof Error
          ? bulkDeleteError.message
          : "批量删除失败。",
      );
    } finally {
      setIsBulkDeleting(false);
    }
  };

  return (
    <section className="history-page">
      <section className="panel history-list-panel">
        <div className="history-heading">
          <PanelTitle
            number="任务"
            title="历史任务"
            subtitle={`直接读取本地任务输入、校验结果与授权文件；${history?.retention_days === 0 ? "桌面任务长期保留。" : `完成任务自动保留 ${history?.retention_days ?? 30} 天。`}`}
          />
          <button
            className="button secondary mini"
            onClick={onRefresh}
            disabled={isLoading}
          >
            刷新记录
          </button>
        </div>
        <div className="history-filters">
          <input
            aria-label="搜索历史任务"
            placeholder="搜索规格、机台或任务 ID"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setSelectedTaskIds(new Set());
            }}
          />
          <select
            aria-label="筛选任务状态"
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as TaskStatus | "all");
              setSelectedTaskIds(new Set());
            }}
          >
            <option value="all">全部状态</option>
            <option value="passed">已通过</option>
            <option value="failed">失败 / 阻断</option>
            <option value="running">执行中</option>
          </select>
          <span>共 {tasks.length} 条</span>
        </div>
        <div className="history-bulk-actions">
          <span>
            已选择 <strong>{selectedTaskIds.size}</strong> 项
          </span>
          <button
            className="button danger mini"
            disabled={selectedTaskIds.size === 0 || isBulkDeleting}
            onClick={() => void deleteSelectedTasks()}
          >
            {isBulkDeleting ? "批量删除中…" : "批量删除"}
          </button>
          <small>执行中任务不可删除。</small>
        </div>
        <div className="table-head selectable">
          <label className="task-selector">
            <input
              type="checkbox"
              aria-label="全选当前可删除任务"
              checked={allSelectableTasksSelected}
              disabled={selectableTaskIds.length === 0}
              onChange={(event) => toggleAllVisibleTasks(event.target.checked)}
            />
          </label>
          <span>任务名称</span>
          <span>机台</span>
          <span>成品形态</span>
          <span>磨前形态</span>
          <span>状态</span>
          <span>操作</span>
        </div>
        {error && <div className="table-message error">{error}</div>}
        {deleteError && (
          <div className="history-action-error">{deleteError}</div>
        )}
        {deleteMessage && (
          <div className="history-action-message">{deleteMessage}</div>
        )}
        {!error && isLoading && (
          <div className="table-message">正在读取本地任务记录…</div>
        )}
        {!error && !isLoading && tasks.length > 0 && (
          <TaskRows
            tasks={tasks}
            selectedTaskId={selectedTaskId}
            selectedTaskIds={selectedTaskIds}
            deletingTaskId={deletingTaskId}
            onView={setSelectedTaskId}
            onToggleSelection={toggleTaskSelection}
            onDelete={(task) => void deleteHistoryTask(task)}
          />
        )}
        {!error && !isLoading && tasks.length === 0 && (
          <TaskEmpty filtered={Boolean(query || statusFilter !== "all")} />
        )}
      </section>
      <TaskDetailDrawer
        open={Boolean(selectedTaskId)}
        detail={detail?.task_id === selectedTaskId ? detail : null}
        isLoading={
          isDetailLoading ||
          Boolean(
            selectedTaskId &&
              detail?.task_id !== selectedTaskId &&
              !detailError,
          )
        }
        error={detailError}
        onClose={() => setSelectedTaskId(null)}
        onCopy={onCopy}
      />
    </section>
  );
}

function TaskRows({
  tasks,
  selectedTaskId,
  selectedTaskIds,
  deletingTaskId = null,
  onView,
  onToggleSelection,
  onDelete,
}: {
  tasks: TaskSummary[];
  selectedTaskId?: string | null;
  selectedTaskIds?: ReadonlySet<string>;
  deletingTaskId?: string | null;
  onView: (taskId: string) => void;
  onToggleSelection?: (taskId: string, checked: boolean) => void;
  onDelete?: (task: TaskSummary) => void;
}) {
  const selectable = Boolean(onToggleSelection);
  return (
    <div className="task-rows">
      {tasks.map((task) => (
        <div
          className={`task-row ${selectable ? "selectable" : ""} ${selectedTaskId === task.task_id ? "selected" : ""}`}
          key={task.task_id}
        >
          {selectable && (
            <label className="task-selector">
              <input
                type="checkbox"
                aria-label={`选择任务 ${task.finished_spec || task.task_id}`}
                checked={selectedTaskIds?.has(task.task_id) ?? false}
                disabled={!task.can_delete}
                onChange={(event) =>
                  onToggleSelection?.(task.task_id, event.target.checked)
                }
              />
            </label>
          )}
          <div className="task-name">
            <strong>{task.finished_spec || task.task_id}</strong>
            <small>
              {formatTaskTime(task.created_at)} · {task.task_id}
            </small>
          </div>
          <span>{task.machine_name}</span>
          <span>{shapeLabel(task.finished_shape)}</span>
          <span>{shapeLabel(task.pre_grinding_shape)}</span>
          <span>
            <TaskStatusBadge status={task.status} />
          </span>
          <div className="task-actions">
            <button
              className="link-button"
              onClick={() => onView(task.task_id)}
            >
              查看
            </button>
            {task.can_delete && onDelete && (
              <button
                className="link-button danger"
                disabled={deletingTaskId === task.task_id}
                onClick={() => onDelete(task)}
              >
                {deletingTaskId === task.task_id ? "删除中" : "删除"}
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function TaskEmpty({ filtered = false }: { filtered?: boolean }) {
  return (
    <div className="empty-table">
      <span>◷</span>
      <div>
        <strong>{filtered ? "没有符合条件的任务" : "暂无任务记录"}</strong>
        <p>
          {filtered
            ? "请调整搜索词或状态筛选。"
            : "新建任务后，这里会显示输入快照、生成状态和 report.json 摘要。"}
        </p>
      </div>
    </div>
  );
}

function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const labels: Record<TaskStatus, string> = {
    running: "执行中",
    passed: "已通过",
    failed: "失败 / 阻断",
  };
  return <span className={`task-status ${status}`}>{labels[status]}</span>;
}

function TaskDetailDrawer({
  open,
  detail,
  isLoading,
  error,
  onClose,
  onCopy,
}: {
  open: boolean;
  detail: TaskDetail | null;
  isLoading: boolean;
  error: string | null;
  onClose: () => void;
  onCopy: (input: DesignInput) => void;
}) {
  const [mounted, setMounted] = useState(open);
  const [visible, setVisible] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const lastDetail = useRef<TaskDetail | null>(null);
  if (detail) lastDetail.current = detail;
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let frame: number | undefined;
    if (open) {
      setMounted(true);
      frame = requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
      timer = setTimeout(() => setMounted(false), 170);
    }
    return () => {
      if (timer) clearTimeout(timer);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [open]);
  useEffect(() => {
    if (!open || !mounted) return;
    const origin = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() =>
      panel.current?.querySelector<HTMLButtonElement>("button")?.focus(),
    );
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
      if (event.key !== "Tab") return;
      const elements = Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), a[href], input, select, textarea, summary, [tabindex='0']",
        ) ?? [],
      );
      const first = elements[0],
        last = elements[elements.length - 1];
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          !panel.current?.contains(document.activeElement))
      ) {
        event.preventDefault();
        last?.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          !panel.current?.contains(document.activeElement))
      ) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", keydown);
      if (origin?.isConnected) origin.focus();
    };
  }, [open, mounted]);
  if (!mounted) return null;
  const shownDetail = open ? detail : lastDetail.current;
  return (
    <div
      className={`task-detail-layer ${visible ? "is-visible" : "is-closing"}`}
      aria-hidden={!open}
    >
      <button
        className="task-detail-backdrop"
        aria-label="关闭任务详情"
        tabIndex={-1}
        onClick={onClose}
      />
      <aside
        ref={panel}
        className="task-detail-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="任务详情"
      >
        <div className="task-detail-toolbar">
          <strong>任务详情</strong>
          <button aria-label="关闭任务详情" onClick={onClose}>
            ×
          </button>
        </div>
        {isLoading ? (
          <div className="table-message">正在读取任务详情…</div>
        ) : error ? (
          <div className="table-message error">{error}</div>
        ) : shownDetail ? (
          <>
            <div className="drawer-copy">
              <button
                className="button primary"
                onClick={() => onCopy(shownDetail.input)}
              >
                复制为新任务
              </button>
            </div>
            <TaskDetailContent key={shownDetail.task_id} detail={shownDetail} />
          </>
        ) : null}
      </aside>
    </div>
  );
}

function TaskDetailContent({ detail }: { detail: TaskDetail }) {
  const files = Object.entries(detail.files);
  return (
    <section className="task-detail">
      <div className="task-detail-header">
        <div>
          <p className="eyebrow">任务详情 / {detail.task_id}</p>
          <h2>{detail.finished_spec}</h2>
          <small>
            {formatTaskTime(detail.created_at)} · {detail.machine_name}
          </small>
        </div>
        <TaskStatusBadge status={detail.status} />
      </div>
      {detail.error && (
        <div className="task-error">
          <strong>失败原因</strong>
          <span>{detail.error}</span>
        </div>
      )}
      <div className="task-detail-grid">
        <div>
          <h3>输入快照</h3>
          <dl>
            <dt>成品规格</dt>
            <dd>{detail.input.finished_spec}</dd>
            <dt>磨前规格</dt>
            <dd>{detail.input.pre_grinding_spec}</dd>
            <dt>成品 / 磨前形态</dt>
            <dd>
              {shapeLabel(detail.input.product_shape_after)} /{" "}
              {shapeLabel(detail.input.product_shape_before)}
            </dd>
            <dt>避空 / 砂轮半径</dt>
            <dd>
              {detail.input.relief} / R{detail.input.wheel_radius.toFixed(2)}
            </dd>
          </dl>
        </div>
        <div>
          <h3>计算与门禁</h3>
          <dl>
            <dt>槽宽</dt>
            <dd>{formatMillimeter(detail.derived.slot_width)}</dd>
            <dt>导轨厚度</dt>
            <dd>{formatMillimeter(detail.derived.guide_thickness)}</dd>
            <dt>DXF 几何检查</dt>
            <dd>{auditLabel(detail.audit.inspection_passed)}</dd>
            <dt>尺寸定义点</dt>
            <dd>{auditLabel(detail.audit.dimension_points_passed)}</dd>
          </dl>
        </div>
        {detail.preview && (
          <div className="task-preview">
            <h3>截面预览</h3>
            <a href={detail.preview.url} target="_blank" rel="noreferrer">
              <img
                src={detail.preview.url}
                alt={`${detail.finished_spec} 导轨截面预览`}
              />
            </a>
          </div>
        )}
      </div>
      <div className="task-files">
        <h3>任务图纸库</h3>
        {files.length === 0 ? (
          <p>该任务没有可打开的授权文件。</p>
        ) : (
          <>
            <p className="artifact-library-note">
              直接打开任务内原文件；仅在需要交付副本时使用“另存副本”。
            </p>
            {files.map(([key, file]) => (
              <div className="task-file-row" key={key}>
                <span>{file.label}</span>
                <small>{file.name}</small>
                <ArtifactActions file={file} />
              </div>
            ))}
          </>
        )}
      </div>
    </section>
  );
}

function formatTaskTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(date);
}

function shapeLabel(shape: string) {
  return (
    {
      tile_shape: "瓦型",
      bread_shape: "馒头型",
      rectangular_block: "方块",
      same_r_tile: "同 R 瓦型",
    }[shape] ?? shape
  );
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
    setError(
      loadError instanceof Error ? loadError.message : "历史任务读取失败。",
    );
  } finally {
    setLoading(false);
  }
}

function Templates({ machines }: { machines: Machine[] }) {
  return (
    <section className="panel page-panel">
      <PanelTitle
        number="配置"
        title="机台模板"
        subtitle="来自 templates/&lt;machine_id&gt;/config.yaml，仅供查看。"
      />
      <div className="template-table">
        <div className="template-head">
          <span>机台</span>
          <span>导轨结构</span>
          <span>砂轮顺序</span>
          <span>固定长度</span>
        </div>
        {machines.map((machine) => (
          <div className="template-row" key={machine.id}>
            <strong>{machine.name}</strong>
            <span>
              {machine.guide_sections} 段 /{" "}
              {machine.guide_type === "double_guide" ? "双导轨" : "单导轨"}
            </span>
            <span>{machine.wheel_positions.join(" / ")}</span>
            <span>{machine.guide_length} mm</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function Rules() {
  return (
    <section className="panel page-panel">
      <PanelTitle
        number="规则"
        title="生成与 release 门禁"
        subtitle="规则源于项目文档并由 Python 校验器执行。"
      />
      <div className="rule-list">
        {[
          [
            "规格来源",
            "成品规格与成型磨前规格必须独立；槽宽与导轨厚度取磨前数据。",
          ],
          ["几何一致性", "相邻图元误差不大于 0.001 mm，闭合轮廓必须严格闭合。"],
          [
            "正式图纸",
            "release 只会在候选 DXF 通过图层、残留图元和尺寸定义点审计后输出。",
          ],
          [
            "尺寸审计",
            "显示值、定义点与真实几何必须一致；双导轨定义点误差不大于 0.01 mm。",
          ],
        ].map(([title, detail]) => (
          <article key={title}>
            <span>✓</span>
            <div>
              <h3>{title}</h3>
              <p>{detail}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function DesktopSettingsPage({
  onEngineState,
}: {
  onEngineState: (online: boolean) => void;
}) {
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [version, setVersion] = useState("1.2.0-dev");
  const [availableUpdate, setAvailableUpdate] = useState<Update | null>(null);
  const [updateMessage, setUpdateMessage] = useState("尚未检查更新。");
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const tauri = "__TAURI_INTERNALS__" in window;

  const loadSettings = async () => {
    setSettingsError(null);
    try {
      setSettings(await api.settings());
    } catch (error) {
      setSettingsError(
        error instanceof Error ? error.message : "设置读取失败。",
      );
    }
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
      setUpdateMessage(
        found ? `发现新版本 ${found.version}` : "当前已是最新版本。",
      );
    } catch {
      setUpdateMessage("无法访问更新服务；离线 CAD 功能不受影响。");
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    void loadSettings();
    if (tauri) {
      void getVersion()
        .then(setVersion)
        .catch(() => undefined);
      void checkForUpdate(true);
    }
  }, []);

  const chooseAutoCad = async () => {
    if (!tauri) {
      setSettingsError(
        "浏览器开发模式不能读取本机文件路径，请设置 CAD_AUTOCAD_CORE_CONSOLE。",
      );
      return;
    }
    const selected = await open({
      multiple: false,
      directory: false,
      title: "选择 AcCoreConsole",
    });
    if (typeof selected !== "string") return;
    try {
      setSettings(await api.updateSettings(selected));
      setSettingsError(null);
    } catch (error) {
      setSettingsError(
        error instanceof Error ? error.message : "AutoCAD 路径保存失败。",
      );
    }
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
      await availableUpdate.download(
        (event) => {
          if (event.event === "Started") total = event.data.contentLength ?? 0;
          if (event.event === "Progress") {
            downloaded += event.data.chunkLength;
            if (total > 0)
              setDownloadProgress(
                Math.min(100, Math.round((downloaded / total) * 100)),
              );
          }
          if (event.event === "Finished") setDownloadProgress(100);
        },
        { timeout: 10 * 60 * 1000 },
      );
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
      setSettingsError(
        error instanceof Error ? error.message : "本地 CAD 引擎重启失败。",
      );
    }
  };

  return (
    <section className="settings-page">
      <section className="panel page-panel">
        <PanelTitle
          number="本机"
          title="AutoCAD 与数据目录"
          subtitle="DWG 只调用本机 AutoCAD；未安装时仍可正常生成 DXF。"
        />
        {settingsError && <div className="alert error">{settingsError}</div>}
        <dl className="settings-list">
          <dt>应用数据目录</dt>
          <dd>{settings?.app_data_root ?? "读取中…"}</dd>
          <dt>AutoCAD 状态</dt>
          <dd>
            {settings?.autocad.available
              ? `已检测到 AutoCAD ${settings.autocad.version ?? "未知版本"}`
              : "未检测到；仍可生成和下载 DXF"}
          </dd>
          <dt>AcCoreConsole</dt>
          <dd>{settings?.autocad.path ?? "未配置"}</dd>
        </dl>
        <div className="settings-actions">
          <button
            className="button secondary"
            onClick={() => void chooseAutoCad()}
          >
            手动选择 AcCoreConsole
          </button>
          <button
            className="button secondary"
            onClick={() => void api.updateSettings(null).then(setSettings)}
          >
            恢复自动检测
          </button>
          <button
            className="button secondary"
            disabled={!tauri}
            onClick={() => void restartEngine()}
          >
            重启本地 CAD 引擎
          </button>
        </div>
      </section>
      <section className="panel page-panel">
        <PanelTitle
          number="更新"
          title={`Forming Grinder CAD ${version}`}
          subtitle="更新包必须通过 Tauri 公钥签名验证，失败时保留当前版本。"
        />
        <p className="update-status">{updateMessage}</p>
        {availableUpdate && (
          <div className="update-detail">
            <strong>版本 {availableUpdate.version}</strong>
            <span>{availableUpdate.date ?? "发布时间未提供"}</span>
            <p>{availableUpdate.body ?? "此版本未提供更新说明。"}</p>
          </div>
        )}
        {installing && (
          <progress value={downloadProgress} max="100">
            {downloadProgress}%
          </progress>
        )}
        <div className="settings-actions">
          <button
            className="button secondary"
            disabled={checking || installing || !tauri}
            onClick={() => void checkForUpdate()}
          >
            {checking ? "检查中…" : "检查更新"}
          </button>
          <button
            className="button primary"
            disabled={!availableUpdate || installing}
            onClick={() => void installUpdate()}
          >
            {installing ? `下载与安装 ${downloadProgress}%` : "下载并安装"}
          </button>
        </div>
      </section>
    </section>
  );
}

function updateFailureMessage(
  stage: "download" | "install",
  error: unknown,
): string {
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

function pageTitle(page: Page) {
  return {
    workspace: "导轨工作台",
    history: "历史任务",
    templates: "机台模板",
    rules: "规则与说明",
    settings: "设置与更新",
  }[page];
}

function applyMachine(
  machine: Machine,
  setter: Dispatch<SetStateAction<DesignInput>>,
) {
  setter((previous) => ({
    ...previous,
    machine_type: machine.id,
    guide_rail_type: machine.guide_type,
    wheel_sequence: machine.wheel_positions,
    first_wheel_side: machineFirstSide(machine),
    template_coordinate_system: machine.template_coordinate_system,
  }));
}
