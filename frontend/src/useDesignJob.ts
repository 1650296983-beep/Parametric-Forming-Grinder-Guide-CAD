import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  DesignInput,
  GenerationProgress,
  ValidationResult,
} from "./types";

const snapshot = (design: DesignInput): DesignInput =>
  JSON.parse(JSON.stringify(design));
const fingerprint = (design: DesignInput) =>
  JSON.stringify(
    Object.keys(design)
      .sort()
      .map((key) => [key, design[key as keyof DesignInput]]),
  );
const message = (error: unknown) =>
  error instanceof Error ? error.message : "本地引擎暂时不可用。";

export function useDesignJob(
  onTerminal: () => void,
  onConnectionChange: (online: boolean) => void,
) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [reviewed, setReviewed] = useState<DesignInput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [starting, setStarting] = useState(false);
  const [progress, setProgress] = useState<GenerationProgress | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const epoch = useRef(0);
  const request = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const reviewedKey = useRef<string | null>(null);
  const terminal = useRef(onTerminal);
  terminal.current = onTerminal;
  const connection = useRef(onConnectionChange);
  connection.current = onConnectionChange;

  const invalidate = useCallback(() => {
    epoch.current += 1;
    request.current?.abort();
    submitting.current = false;
    reviewedKey.current = null;
    setValidation(null);
    setReviewed(null);
    setProgress(null);
    setJobId(null);
    setError(null);
    setConnectionError(null);
    setValidating(false);
    setStarting(false);
    setStep(1);
  }, []);

  useEffect(
    () => () => {
      epoch.current += 1;
      request.current?.abort();
    },
    [],
  );

  const validate = async (design: DesignInput) => {
    if (submitting.current) return;
    submitting.current = true;
    const version = epoch.current;
    const input = snapshot(design);
    const controller = new AbortController();
    request.current = controller;
    setError(null);
    setValidating(true);
    try {
      const result = await api.validate(input, controller.signal);
      if (version !== epoch.current) return;
      connection.current(true);
      reviewedKey.current = fingerprint(input);
      setValidation(result);
      setReviewed(input);
      setStep(2);
    } catch (failure) {
      if (version === epoch.current && !controller.signal.aborted) {
        if (failure instanceof TypeError) connection.current(false);
        setError(message(failure));
      }
    } finally {
      if (version === epoch.current) {
        setValidating(false);
        submitting.current = false;
      }
    }
  };

  const generate = async (current: DesignInput) => {
    if (
      submitting.current ||
      !reviewed ||
      !validation ||
      reviewedKey.current !== fingerprint(current)
    )
      return;
    submitting.current = true;
    const version = epoch.current;
    const controller = new AbortController();
    request.current = controller;
    setError(null);
    setStarting(true);
    setStep(3);
    try {
      const job = await api.startJob(snapshot(reviewed), controller.signal);
      if (version !== epoch.current) return;
      connection.current(true);
      setJobId(job.task_id);
      terminal.current();
    } catch (failure) {
      if (version === epoch.current && !controller.signal.aborted) {
        if (failure instanceof TypeError) connection.current(false);
        setError(message(failure));
        setStep(2);
      }
    } finally {
      if (version === epoch.current) {
        setStarting(false);
        submitting.current = false;
      }
    }
  };

  useEffect(() => {
    if (!jobId) return;
    const version = epoch.current;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
    const poll = async () => {
      try {
        const result = await api.progress(jobId, controller.signal);
        if (!active || version !== epoch.current || result.task_id !== jobId)
          return;
        connection.current(true);
        setProgress(result);
        setConnectionError(null);
        if (result.status === "running")
          timer = setTimeout(() => void poll(), 600);
        else {
          setError(
            result.status === "failed" ? result.error || result.message : null,
          );
          terminal.current();
        }
      } catch (failure) {
        if (active && !controller.signal.aborted && version === epoch.current) {
          connection.current(false);
          setConnectionError(message(failure));
        }
      }
    };
    void poll();
    return () => {
      active = false;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [jobId, retry]);

  return {
    step,
    validation,
    reviewed,
    error,
    validating,
    starting,
    progress,
    jobId,
    connectionError,
    validate,
    generate,
    invalidate,
    reconnect: () => {
      setRetry((value) => value + 1);
    },
  };
}
