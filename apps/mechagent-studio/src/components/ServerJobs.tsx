import { useEffect, useState } from "react";
import { useI18n } from "../i18n/LocaleProvider";
import { fetchEvidence, fetchJob, fetchJobs, retryJob } from "../lib/api";
import { isActiveJob, jobStatusLabel } from "../lib/job";
import type { StudioJobResponse } from "../types";

export function ServerJobs({ running, onOpen }: {
  running: boolean; onOpen: (job: StudioJobResponse) => void;
}) {
  const { t } = useI18n();
  const [jobs, setJobs] = useState<StudioJobResponse[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function action(callback: () => Promise<void>) {
    setBusy(true); setMessage("");
    try { await callback(); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }
  async function refresh() {
    const page = await fetchJobs();
    setJobs(page.jobs);
    setNextCursor(page.pagination.next_cursor);
    setHasMore(page.pagination.has_more);
  }
  async function loadMore() {
    if (!nextCursor) return;
    const page = await fetchJobs(nextCursor);
    setJobs(current => [...current, ...page.jobs]);
    setNextCursor(page.pagination.next_cursor);
    setHasMore(page.pagination.has_more);
  }
  useEffect(() => { void action(refresh); }, [running]);
  return <section className="server-jobs" aria-label={t("服务器作业")}>
    <div className="server-jobs-head">
      <strong>{t("服务器作业")}</strong>
      <button type="button" className="secondary-action" disabled={busy}
        onClick={() => void action(refresh)}>{t("刷新")}</button>
    </div>
    <p className="server-jobs-help">{t("显示最近作业；完整记录保存在本机数据库。")}</p>
    {message && <p className="preflight-error" role="status">{t(message)}</p>}
    {jobs.map(job => <div className="server-job" key={job.job_id}>
      <button type="button" className="history-item" disabled={running || busy}
        onClick={() => void action(async () => onOpen(await fetchJob(job.job_id)))}>
        <strong>{job.job_id.slice(0, 8)} · {t(jobStatusLabel(job.status))}</strong>
        <small>{job.request}</small>
      </button>
      {!isActiveJob(job) && <div className="server-job-actions">
        <button type="button" className="secondary-action" disabled={running || busy}
          onClick={() => void action(async () => { onOpen(await retryJob(job.job_id)); await refresh(); })}>
          {t("重试")}
        </button>
        <button type="button" className="secondary-action" disabled={busy}
          onClick={() => void action(async () => {
            const evidence = await fetchEvidence(job.job_id);
            setMessage(evidence.valid ? "证据文件完整性通过。" : `证据校验失败：${evidence.errors.join("; ")}`);
          })}>{t("校验证据")}</button>
      </div>}
    </div>)}
    {hasMore && <button type="button" className="secondary-action" disabled={busy || running}
      onClick={() => void action(loadMore)}>{t("加载更多")}</button>}
  </section>;
}
