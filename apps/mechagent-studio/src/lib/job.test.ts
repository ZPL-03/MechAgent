import { describe, expect, it, vi, afterEach } from "vitest";
import { isActiveJob, jobFailureDisposition, jobStatusLabel } from "./job";
import { ApiError, createJob, fetchHealth, fetchJob, fetchJobs, inspectRequest } from "./api";
import type { StudioJobResponse, StudioJobStatus } from "../types";

afterEach(() => vi.unstubAllGlobals());
describe("durable job lifecycle", () => {
  it("clears a persisted job only when the server confirms it is missing", () => {
    expect(jobFailureDisposition(new ApiError("missing", 404), true)).toBe("missing");
    expect(jobFailureDisposition(new ApiError("denied", 403), true)).toBe("disconnected");
    expect(jobFailureDisposition(new ApiError("invalid", 400), false)).toBe("submission");
    expect(jobFailureDisposition(new ApiError("offline", 0, "transport_error"), false)).toBe(
      "disconnected",
    );
  });
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
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/jobs");
    for (const call of fetch.mock.calls) expect(call[1].headers["Idempotency-Key"]).toBe("submission-1");
  });
  it("exposes a missing persisted job instead of inventing a result", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: "missing" }) }));
    await expect(fetchJob("unknown")).rejects.toThrow("missing");
  });
  it("preserves the server error code for client decisions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ code: "forbidden", detail: "denied" })
    }));
    const error = await fetchJob("restricted").catch(value => value);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("forbidden");
    expect((error as ApiError).status).toBe(403);
  });
  it("preserves structured error details from validation responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ code: "validation_error", detail: [{ loc: ["body"], msg: "invalid" }] })
    }));
    const error = await fetchHealth().catch(value => value);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toContain('"msg":"invalid"');
    expect((error as ApiError).detail).toEqual([{ loc: ["body"], msg: "invalid" }]);
  });
  it("uses the text body when an error response is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => { throw new Error("not json"); },
      text: async () => "upstream unavailable"
    }));
    await expect(fetchHealth()).rejects.toMatchObject({
      status: 502,
      code: undefined,
      detail: "upstream unavailable"
    });
  });
  it("reports transport failures with a stable client error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(fetchHealth()).rejects.toMatchObject({
      status: 0,
      code: "transport_error",
      message: "offline"
    });
  });
  it("keeps an explicitly cancelled request as an abort", async () => {
    const aborted = new Error("cancelled");
    aborted.name = "AbortError";
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(aborted));
    await expect(fetchHealth()).rejects.toBe(aborted);
  });
  it("passes the inspection abort signal to the request", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, ready: false, request: "beam", tasks: [], errors: [] })
    });
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    await inspectRequest("beam", controller.signal);
    expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
  });
  it("encodes persisted job identifiers before requesting status", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ job_id: "job" }) });
    vi.stubGlobal("fetch", fetch);
    await fetchJob("job/id with space");
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/jobs/job%2Fid%20with%20space");
  });
  it("requests the next job page with the server cursor", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ jobs: [], pagination: { limit: 10, next_cursor: null, has_more: false } })
    });
    vi.stubGlobal("fetch", fetch);
    await fetchJobs("cursor-value");
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/jobs?limit=10&cursor=cursor-value");
  });
});
