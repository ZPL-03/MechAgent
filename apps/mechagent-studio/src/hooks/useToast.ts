import { useCallback, useEffect, useState } from "react";
import { NOTICE_TIMEOUT_MS } from "../lib/constants";
import type { Notice } from "../lib/uiTypes";

export function useToast() {
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    if (!notice) {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => {
      setNotice((current) => (current?.id === notice.id ? null : current));
    }, NOTICE_TIMEOUT_MS);
    return () => window.clearTimeout(timeoutId);
  }, [notice]);

  const showNotice = useCallback((message: string, tone: Notice["tone"] = "ok") => {
    setNotice({ id: Date.now(), message, tone });
  }, []);

  return { notice, showNotice };
}
