import { useEffect, useState } from "react";
import { inspectRequest } from "../lib/api";
import { INSPECTION_DEBOUNCE_MS } from "../lib/constants";
import type { StudioInspectionResponse } from "../types";

/** 输入变化后防抖触发运行前预检。 */
export function useInspection(request: string) {
  const [inspection, setInspection] = useState<StudioInspectionResponse | null>(null);
  const [inspectionRunning, setInspectionRunning] = useState(false);

  useEffect(() => {
    const requestText = request.trim();
    if (!requestText) {
      setInspection(null);
      setInspectionRunning(false);
      return undefined;
    }

    const controller = new AbortController();
    let cancelled = false;
    setInspectionRunning(true);
    const timeoutId = window.setTimeout(() => {
      void inspectRequest(requestText, controller.signal)
        .then((data) => {
          if (!cancelled) {
            setInspection(data);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setInspection({
              success: false,
              ready: false,
              request: requestText,
              tasks: [],
              errors: [{ node: "studio", code: "unknown_error", message: "预检服务不可用。" }]
            });
          }
        })
        .finally(() => {
          if (!cancelled) {
            setInspectionRunning(false);
          }
        });
    }, INSPECTION_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [request]);

  return { inspection, inspectionRunning };
}
