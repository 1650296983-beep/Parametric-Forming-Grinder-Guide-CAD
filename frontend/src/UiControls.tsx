import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { useToast } from "./Toast";

export function CrossfadeIcon({
  active,
  activeIcon,
  inactiveIcon,
}: {
  active: boolean;
  activeIcon: ReactNode;
  inactiveIcon: ReactNode;
}) {
  return (
    <span className="icon-swap" aria-hidden="true">
      <span
        className={`icon-swap-layer ${active ? "is-hidden" : "is-shown"}`}
      >
        {inactiveIcon}
      </span>
      <span
        className={`icon-swap-layer is-overlay ${active ? "is-shown" : "is-hidden"}`}
      >
        {activeIcon}
      </span>
    </span>
  );
}

export function CopyIconButton({
  value,
  size = 13,
  ariaLabel,
  title,
  successMessage,
}: {
  value: string;
  size?: number;
  ariaLabel: string;
  title: string;
  successMessage: string;
}) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1600);
      toast.success(successMessage);
    } catch {
      toast.error("无法访问剪贴板，请手动复制。");
    }
  };

  return (
    <button
      type="button"
      className="icon-button mini"
      aria-label={ariaLabel}
      title={title}
      onClick={() => void copy()}
    >
      <CrossfadeIcon
        active={copied}
        activeIcon={<Check size={size} />}
        inactiveIcon={<Copy size={size} />}
      />
    </button>
  );
}
