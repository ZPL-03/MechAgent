import { useEffect, useRef, useState } from "react";
import { cancelJob, createJob, fetchJob } from "../lib/api";
import { JOB_POLL_INTERVAL_MS } from "../lib/constants";
import { isActiveJob, jobFailureDisposition, jobStatusLabel, runError, sleep } from "../lib/job";
import type { StudioJobResponse, StudioRunResponse } from "../types";

const STORAGE_KEY = "mechagent.activeJob.v1";
interface PendingJob { request: string; useLlm: boolean; key: string; id?: string }

export function usePersistentJob(onComplete: (request: string, result: StudioRunResponse) => void) {
  const [activeJob, setActiveJob] = useState<StudioJobResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [disconnected, setDisconnected] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<PendingJob | null>(null);
  const busy = useRef(false);
  const tracking = useRef(false);
  const restored = useRef(false);
  const callback = useRef(onComplete);
  callback.current = onComplete;

  function persist(value: PendingJob | null) {
    pending.current = value;
    try {
      if (value) localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      setError("浏览器无法保存作业标识；可从服务器记录重新打开。");
    }
  }

  async function track(value: PendingJob) {
    if (tracking.current) return;
    tracking.current = true;
    busy.current = true;
    setRunning(true);
    setDisconnected(false);
    setError("");
    persist(value);
    try {
      let job = value.id ? await fetchJob(value.id) :
        await createJob(value.request, value.useLlm, value.key);
      value = { ...value, id: job.job_id };
      persist(value);
      setActiveJob(job);
      while (isActiveJob(job)) {
        await sleep(JOB_POLL_INTERVAL_MS);
        job = await fetchJob(job.job_id);
        setActiveJob(job);
      }
      persist(null);
      busy.current = false;
      setRunning(false);
      callback.current(job.request, job.result ?? runError(job.error ?? jobStatusLabel(job.status)));
    } catch (failure) {
      const message = failure instanceof Error ? failure.message : String(failure);
      const disposition = jobFailureDisposition(failure, Boolean(value.id));
      if (disposition === "missing") {
        persist(null);
        busy.current = false;
        setRunning(false);
        setDisconnected(false);
        setActiveJob(null);
        setError("服务器作业不存在或已清理；本地跟踪已清除。");
      } else if (disposition === "submission") {
        persist(null);
        busy.current = false;
        setRunning(false);
        callback.current(value.request, runError(message));
      } else {
        // 网络断开时保留作业标识，重连后通过服务器状态确认求解结果。
        setDisconnected(true);
        setError(message);
      }
    } finally {
      tracking.current = false;
    }
  }

  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as PendingJob;
      if (typeof saved.request !== "string" || typeof saved.key !== "string" ||
          typeof saved.useLlm !== "boolean" || (saved.id !== undefined && typeof saved.id !== "string")) {
        throw new Error("作业标识无效。");
      }
      void track(saved);
    } catch {
      setError("浏览器作业标识无法恢复；可从服务器记录重新打开。");
    }
  }, []);

  return {
    activeJob, running, disconnected, error, setActiveJob,
    start(request: string, useLlm: boolean) {
      if (busy.current) return;
      setActiveJob(null);
      return track({ request, useLlm, key: crypto.randomUUID() });
    },
    open(job: StudioJobResponse) {
      if (busy.current) return;
      return track({ request: job.request, useLlm: job.use_llm_agents,
                     key: crypto.randomUUID(), id: job.job_id });
    },
    reconnect() { if (pending.current) void track(pending.current); },
    stopTracking() {
      if (tracking.current) return;
      persist(null);
      busy.current = false;
      setRunning(false);
      setDisconnected(false);
      setActiveJob(null);
      setError("已停止跟踪；服务器作业继续执行，可从服务器记录打开。");
    },
    async cancel() {
      if (!activeJob || activeJob.status === "cancelling") return;
      try { setActiveJob(await cancelJob(activeJob.job_id)); }
      catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    },
  };
}
