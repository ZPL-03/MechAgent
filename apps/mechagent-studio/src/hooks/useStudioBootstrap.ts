import { useEffect, useState } from "react";
import {
  fetchCapabilities,
  fetchDiagnostics,
  fetchExamples,
  fetchHealth
} from "../lib/api";
import type {
  StudioCapability,
  StudioDiagnosticsResponse,
  StudioExample,
  StudioHealth
} from "../types";

/** 启动时拉取 health / diagnostics / capabilities / examples。 */
export function useStudioBootstrap() {
  const [health, setHealth] = useState<StudioHealth | null>(null);
  const [diagnostics, setDiagnostics] = useState<StudioDiagnosticsResponse | null>(null);
  const [capabilities, setCapabilities] = useState<StudioCapability[]>([]);
  const [catalogExamples, setCatalogExamples] = useState<StudioExample[]>([]);

  useEffect(() => {
    void fetchHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    void fetchDiagnostics()
      .then((data) => setDiagnostics(data as StudioDiagnosticsResponse))
      .catch(() => setDiagnostics(null));
  }, []);

  useEffect(() => {
    void fetchCapabilities()
      .then(setCapabilities)
      .catch(() => setCapabilities([]));
  }, []);

  useEffect(() => {
    void fetchExamples()
      .then(setCatalogExamples)
      .catch(() => setCatalogExamples([]));
  }, []);

  return { health, diagnostics, capabilities, catalogExamples };
}
