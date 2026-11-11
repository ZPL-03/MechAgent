import { describe, expect, it, vi, afterEach } from "vitest";
import { isActiveJob, jobStatusLabel } from "./job";
import { createJob, fetchJob } from "./api";
import type { StudioJobResponse, StudioJobStatus } from "../types";

afterEach(() => vi.unstubAllGlobals());
describe("durable job lifecycle", () => {
  it.each(["queued", "starting", "running", "cancelling"] as StudioJobStatus[])("tracks %s", status => {
    expect(isActiveJob({ status } as StudioJobResponse)).toBe(true);
  });
  it.each(["cancelled", "interrupted", "failed", "succeeded"] as StudioJobStatus[])("ends %s", status => {
    expect(isActiveJob({ status } as StudioJobResponse)).toBe(false);
    expect(jobStatusLabel(status)).toBeTruthy();
  });
  it("resends a submission with the same idempotency key", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ job_id: "same" }) });
    vi.stubGlobal("fetch", fetch);
    await createJob("beam", false, "submission-1");
    await createJob("beam", false, "submission-1");
    for (const call of fetch.mock.calls) expect(call[1].headers["Idempotency-Key"]).toBe("submission-1");
  });
  it("exposes a missing persisted job instead of inventing a result", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: "missing" }) }));
    await expect(fetchJob("unknown")).rejects.toThrow("missing");
  });
});
