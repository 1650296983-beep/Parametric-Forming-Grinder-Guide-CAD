import type { DesignInput, GenerationResult, Machine, UserSession, ValidationResult } from "./types";

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
