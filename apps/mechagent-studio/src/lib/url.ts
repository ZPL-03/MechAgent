import {
  AUTO_RUN_QUERY_KEY,
  DEFAULT_REQUEST,
  LLM_QUERY_KEY,
  REQUEST_QUERY_KEY,
  RENDER_MODES,
  VIEW_QUERY_KEY,
  type RenderModeKey
} from "./constants";

export function initialRequestFromUrl() {
  if (typeof window === "undefined") {
    return DEFAULT_REQUEST;
  }
  const requestValue = new URLSearchParams(window.location.search).get(REQUEST_QUERY_KEY);
  return requestValue?.trim() || DEFAULT_REQUEST;
}

export function initialParameterCompletionFromUrl() {
  if (typeof window === "undefined") {
    return false;
  }
  const value = new URLSearchParams(window.location.search).get(LLM_QUERY_KEY);
  return value === "1" || value?.toLowerCase() === "true";
}

export function initialRenderModeIndexFromUrl() {
  if (typeof window === "undefined") {
    return 0;
  }
  const value = new URLSearchParams(window.location.search).get(VIEW_QUERY_KEY);
  const index = RENDER_MODES.findIndex((mode) => mode.key === value);
  return index >= 0 ? index : 0;
}

export function initialAutoRunFromUrl() {
  if (typeof window === "undefined") {
    return false;
  }
  const value = new URLSearchParams(window.location.search).get(AUTO_RUN_QUERY_KEY);
  return value === "1" || value?.toLowerCase() === "true";
}

export function studioWorkspaceLink(
  requestText: string,
  useLlmAgents: boolean,
  renderMode: RenderModeKey
) {
  if (typeof window === "undefined") {
    return "";
  }
  const url = new URL(window.location.href);
  applyWorkspaceQuery(url, requestText, useLlmAgents, renderMode);
  return url.toString();
}

export function replaceStudioUrl(
  requestText: string,
  useLlmAgents: boolean,
  renderMode: RenderModeKey
) {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  applyWorkspaceQuery(url, requestText, useLlmAgents, renderMode);
  const nextPath = `${url.pathname}${url.search}${url.hash}`;
  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (nextPath !== currentPath) {
    window.history.replaceState(null, "", nextPath);
  }
}

function applyWorkspaceQuery(
  url: URL,
  requestText: string,
  useLlmAgents: boolean,
  renderMode: RenderModeKey
) {
  url.searchParams.delete(AUTO_RUN_QUERY_KEY);
  const requestValue = requestText.trim();
  if (requestValue && requestValue !== DEFAULT_REQUEST) {
    url.searchParams.set(REQUEST_QUERY_KEY, requestValue);
  } else {
    url.searchParams.delete(REQUEST_QUERY_KEY);
  }
  if (useLlmAgents) {
    url.searchParams.set(LLM_QUERY_KEY, "1");
  } else {
    url.searchParams.delete(LLM_QUERY_KEY);
  }
  if (RENDER_MODES.some((mode) => mode.key === renderMode)) {
    url.searchParams.set(VIEW_QUERY_KEY, renderMode);
  } else {
    url.searchParams.delete(VIEW_QUERY_KEY);
  }
}

export function removeAutoRunQuery() {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  if (!url.searchParams.has(AUTO_RUN_QUERY_KEY)) {
    return;
  }
  url.searchParams.delete(AUTO_RUN_QUERY_KEY);
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}
