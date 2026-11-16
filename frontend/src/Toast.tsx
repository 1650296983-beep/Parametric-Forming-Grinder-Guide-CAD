import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

export type ToastTone = "success" | "error" | "info";

export interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
  /** Milliseconds before auto-dismiss. Use 0 to keep it open. */
  duration?: number;
}

interface ToastItem extends ToastInput {
  id: number;
  tone: ToastTone;
  closing?: boolean;
}

const TOAST_EXIT_MS = 150;

interface ToastApi {
  push: (toast: ToastInput) => number;
  dismiss: (id: number) => void;
  success: (title: string, description?: string) => number;
  error: (title: string, description?: string) => number;
  info: (title: string, description?: string) => number;
}

const ToastContext = createContext<ToastApi | null>(null);
const ICONS = {
  success: CheckCircle2,
  error: AlertTriangle,
  info: Info,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const exitTimers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const removeNow = useCallback((id: number) => {
    const exitTimer = exitTimers.current.get(id);
    if (exitTimer) clearTimeout(exitTimer);
    exitTimers.current.delete(id);
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const dismiss = useCallback(
    (id: number) => {
      const timer = timers.current.get(id);
      if (timer) clearTimeout(timer);
      timers.current.delete(id);
      const reducedMotion =
        typeof window !== "undefined" &&
        window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      if (reducedMotion) {
        removeNow(id);
        return;
      }
      if (exitTimers.current.has(id)) return;
      setItems((current) =>
        current.map((item) =>
          item.id === id ? { ...item, closing: true } : item,
        ),
      );
      exitTimers.current.set(
        id,
        setTimeout(() => removeNow(id), TOAST_EXIT_MS),
      );
    },
    [removeNow],
  );

  useEffect(() => {
    return () => {
      timers.current.forEach((timer) => clearTimeout(timer));
      timers.current.clear();
      exitTimers.current.forEach((timer) => clearTimeout(timer));
      exitTimers.current.clear();
    };
  }, []);

  const push = useCallback(
    (toast: ToastInput) => {
      const id = nextId.current++;
      const tone = toast.tone ?? "info";
      const item: ToastItem = { ...toast, id, tone };
      setItems((current) => [...current.slice(-3), item]);
      const duration = toast.duration ?? (tone === "error" ? 7000 : 4200);
      if (duration > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), duration),
        );
      }
      return id;
    },
    [dismiss],
  );

  const api = useMemo(
    () => ({
      push,
      dismiss,
      success: (title: string, description?: string) =>
        push({ title, description, tone: "success" }),
      error: (title: string, description?: string) =>
        push({ title, description, tone: "error" }),
      info: (title: string, description?: string) =>
        push({ title, description, tone: "info" }),
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-viewport" aria-label="通知">
        {items.map((item) => {
          const Icon = ICONS[item.tone];
          return (
            <div
              className={`toast toast-${item.tone}`}
              data-closing={item.closing ? "true" : undefined}
              key={item.id}
              role={item.tone === "error" ? "alert" : "status"}
            >
              <Icon className="toast-icon" aria-hidden="true" />
              <div className="toast-copy">
                <strong>{item.title}</strong>
                {item.description && <p>{item.description}</p>}
              </div>
              <button
                className="toast-close"
                aria-label="关闭通知"
                onClick={() => dismiss(item.id)}
              >
                <X size={15} aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
