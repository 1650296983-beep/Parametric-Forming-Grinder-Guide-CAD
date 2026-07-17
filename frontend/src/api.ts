import { invoke } from "@tauri-apps/api/core";
import type { BulkDeleteResult, DesignInput, DesktopSettings, EngineStatus, GenerationResult, Machine, TaskDetail, TaskHistoryResult, UserSession, ValidationResult } from "./types";

let apiBaseUrlPromise: Promise<string> | null = null;

const isTauri = () => "__TAURI_INTERNALS__" in window;

const apiBaseUrl = async (): Promise<string> => {
  if (!apiBaseUrlPromise) {
    apiBaseUrlPromise = isTauri()
      ? invoke<EngineStatus>("engine_status").then((status) => {
          if (!status.running || !status.apiBaseUrl) throw new Error(status.error ?? "本地 CAD 引擎未启动。");
          return status.apiBaseUrl;
        })
      : Promise.resolve("");
  }
  return apiBaseUrlPromise;
};

export const resetApiBaseUrl = () => { apiBaseUrlPromise = null; };

const request = async <T>(path: string, options?: RequestInit): Promise<T> => {
  const base = await apiBaseUrl();
  const response = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (response.ok) return response.json() as Promise<T>;
  const error = (await response.json().catch(() => null)) as { detail?: string } | null;
  throw new Error(error?.detail ?? "本地服务暂时不可用。");
};

const canonicalDesignPayload = (design: DesignInput): Omit<DesignInput, "tolerance"> => {
  const { tolerance: _legacyTolerance, ...payload } = design;
  return payload;
};

const withAbsoluteFileUrls = async <T>(payload: T): Promise<T> => {
  const base = await apiBaseUrl();
  if (!base) return payload;
  const visit = (value: unknown): void => {
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      if (key === "url" && typeof child === "string" && child.startsWith("/api/")) {
        (value as Record<string, unknown>)[key] = `${base}${child}`;
      } else {
        visit(child);
      }
    }
  };
  visit(payload);
  return payload;
};

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  me: () => request<UserSession>("/api/auth/me"),
  machines: () => request<Machine[]>("/api/machines"),
  settings: () => request<DesktopSettings>("/api/settings"),
  updateSettings: (autocadCoreConsole: string | null) => request<DesktopSettings>("/api/settings", {
    method: "PUT",
    body: JSON.stringify({ autocad_core_console: autocadCoreConsole }),
  }),
  tasks: (limit = 100) => request<TaskHistoryResult>(`/api/tasks?limit=${limit}`).then(withAbsoluteFileUrls),
  task: (taskId: string) => request<TaskDetail>(`/api/tasks/${encodeURIComponent(taskId)}`).then(withAbsoluteFileUrls),
  deleteTask: (taskId: string) => request<{ task_id: string; status: "deleted" }>(
    `/api/tasks/${encodeURIComponent(taskId)}`,
    { method: "DELETE" },
  ),
  deleteTasks: (taskIds: string[]) => request<BulkDeleteResult>(
    "/api/tasks/bulk-delete",
    { method: "POST", body: JSON.stringify({ task_ids: taskIds }) },
  ),
  validate: (design: DesignInput) => request<ValidationResult>("/api/designs/validate", {
    method: "POST",
    body: JSON.stringify(canonicalDesignPayload(design)),
  }),
  generate: (design: DesignInput) => request<GenerationResult>("/api/designs/generate", {
    method: "POST",
    body: JSON.stringify({ design: canonicalDesignPayload(design) }),
  }).then(withAbsoluteFileUrls),
};
