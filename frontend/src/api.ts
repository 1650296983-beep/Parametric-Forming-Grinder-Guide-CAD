import type { BulkDeleteResult, DesignInput, GenerationResult, Machine, TaskDetail, TaskHistoryResult, UserSession, ValidationResult } from "./types";

const request = async <T>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (response.ok) {
    return response.json() as Promise<T>;
  }
  const error = (await response.json().catch(() => null)) as { detail?: string } | null;
  throw new Error(error?.detail ?? "本地服务暂时不可用。");
};

const canonicalDesignPayload = (design: DesignInput): Omit<DesignInput, "tolerance"> => {
  // The parser treats tolerances inside the pre-grinding specification as the
  // source of truth.  Never resend stale compatibility metadata from a prior
  // task after an operator edits the specification field.
  const { tolerance: _legacyTolerance, ...payload } = design;
  return payload;
};

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  login: (username: string, password: string) =>
    request<UserSession>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<{ status: string }>("/api/auth/logout", { method: "POST" }),
  me: () => request<UserSession>("/api/auth/me"),
  machines: () => request<Machine[]>("/api/machines"),
  tasks: (limit = 100) => request<TaskHistoryResult>(`/api/tasks?limit=${limit}`),
  task: (taskId: string) => request<TaskDetail>(`/api/tasks/${encodeURIComponent(taskId)}`),
  deleteTask: (taskId: string) => request<{ task_id: string; status: "deleted" }>(
    `/api/tasks/${encodeURIComponent(taskId)}`,
    { method: "DELETE" },
  ),
  deleteTasks: (taskIds: string[]) => request<BulkDeleteResult>(
    "/api/tasks/bulk-delete",
    { method: "POST", body: JSON.stringify({ task_ids: taskIds }) },
  ),
  validate: (design: DesignInput) =>
    request<ValidationResult>("/api/designs/validate", {
      method: "POST",
      body: JSON.stringify(canonicalDesignPayload(design)),
    }),
  generate: (design: DesignInput) =>
    request<GenerationResult>(
      "/api/designs/generate",
      {
        method: "POST",
        body: JSON.stringify({ design: canonicalDesignPayload(design) }),
      },
    ),
};
