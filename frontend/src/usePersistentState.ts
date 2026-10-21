import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

const PREFIX = "forming-grinder-cad:";

export function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (raw == null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function readStoredString(key: string): string | null {
  try {
    return window.localStorage.getItem(PREFIX + key);
  } catch {
    return null;
  }
}

export function writeStoredString(key: string, value: string): void {
  try {
    window.localStorage.setItem(PREFIX + key, value);
  } catch {
    // Storage can be unavailable in a locked-down webview; the UI still works.
  }
}

export function usePersistentState<T>(
  key: string,
  initial: T,
  options: { delay?: number } = {},
): {
  value: T;
  setValue: Dispatch<SetStateAction<T>>;
  clear: () => void;
  restored: boolean;
} {
  const initialRef = useRef(initial);
  const restoredRef = useRef(false);
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(PREFIX + key);
      if (raw == null) return initial;
      const parsed = JSON.parse(raw) as T;
      restoredRef.current =
        JSON.stringify(parsed) !== JSON.stringify(initialRef.current);
      return parsed;
    } catch {
      return initial;
    }
  });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const delay = options.delay ?? 250;

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      try {
        window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
      } catch {
        // Ignore quota or privacy-mode failures; this is a convenience draft.
      }
    }, delay);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [key, value, delay]);

  const clear = useCallback(() => {
    try {
      window.localStorage.removeItem(PREFIX + key);
    } catch {
      // Ignore.
    }
    setValue(initialRef.current);
  }, [key]);

  return {
    value,
    setValue,
    clear,
    restored: restoredRef.current,
  };
}
