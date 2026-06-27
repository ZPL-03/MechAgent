import { History, Ruler, Search, SlidersHorizontal, Trash2 } from "lucide-react";
import { EXAMPLE_FILTERS } from "../lib/constants";
import { runOutcome } from "../lib/results";
import { historyMeta, historyTitle } from "../lib/storage";
import type { DisplayItem, Example, ExampleFilter, RunHistoryItem, SideTab } from "../lib/uiTypes";
import type { StudioRunResponse } from "../types";
import { CompactEmpty } from "./common";

export function SidePanel({
  selectedSideTab,
  onSelectSideTab,
  examples,
  totalCount,
  exampleFilter,
  exampleQuery,
  onFilterChange,
  onQueryChange,
  onSelectExample,
  history,
  activeHistoryId,
  recentlyClearedCount,
  onClearHistory,
  onUndoClear,
  onSelectHistory,
  facts
}: {
  selectedSideTab: SideTab;
  onSelectSideTab: (tab: SideTab) => void;
  examples: Example[];
  totalCount: number;
  exampleFilter: ExampleFilter;
  exampleQuery: string;
  onFilterChange: (filter: ExampleFilter) => void;
  onQueryChange: (query: string) => void;
  onSelectExample: (request: string) => void;
  history: RunHistoryItem[];
  activeHistoryId: string | null;
  recentlyClearedCount: number;
  onClearHistory: () => void;
  onUndoClear: () => void;
  onSelectHistory: (item: RunHistoryItem) => void;
  facts: DisplayItem[];
}) {
  const tabs: Array<{ key: SideTab; label: string; icon: typeof SlidersHorizontal }> = [
    { key: "examples", label: "工况", icon: SlidersHorizontal },
    { key: "history", label: "历史", icon: History },
    { key: "facts", label: "摘要", icon: Ruler }
  ];
  return (
    <section className="panel side-panel">
      <div className="side-tabs" role="tablist" aria-label="输入辅助面板">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              className={selectedSideTab === tab.key ? "active" : ""}
              type="button"
              role="tab"
              aria-selected={selectedSideTab === tab.key}
              onClick={() => onSelectSideTab(tab.key)}
            >
              <Icon aria-hidden="true" size={15} />
              {tab.label}
            </button>
          );
        })}
      </div>
      <div className="side-panel-body">
        {selectedSideTab === "examples" && (
          <ExampleList
            examples={examples}
            totalCount={totalCount}
            filter={exampleFilter}
            query={exampleQuery}
            onFilterChange={onFilterChange}
            onQueryChange={onQueryChange}
            onSelect={onSelectExample}
          />
        )}
        {selectedSideTab === "history" && (
          <HistoryList
            activeHistoryId={activeHistoryId}
            history={history}
            recentlyClearedCount={recentlyClearedCount}
            onClear={onClearHistory}
            onUndoClear={onUndoClear}
            onSelect={onSelectHistory}
          />
        )}
        {selectedSideTab === "facts" && <FactList facts={facts} />}
      </div>
    </section>
  );
}

function ExampleList({
  examples,
  totalCount,
  filter,
  query,
  onFilterChange,
  onQueryChange,
  onSelect
}: {
  examples: Example[];
  totalCount: number;
  filter: ExampleFilter;
  query: string;
  onFilterChange: (filter: ExampleFilter) => void;
  onQueryChange: (query: string) => void;
  onSelect: (request: string) => void;
}) {
  return (
    <div className="example-panel">
      <div className="example-toolbar">
        <label className="example-search">
          <Search aria-hidden="true" size={15} />
          <input
            type="search"
            name="example-search"
            autoComplete="off"
            inputMode="search"
            placeholder="搜索工况、材料、载荷…"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            aria-label="搜索工况示例"
          />
        </label>
        <div className="example-filter" role="group" aria-label="工况筛选">
          {EXAMPLE_FILTERS.map((item) => (
            <button
              key={item.key}
              className={filter === item.key ? "active" : ""}
              type="button"
              aria-pressed={filter === item.key}
              onClick={() => onFilterChange(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <span className="example-count">
          {examples.length}/{totalCount} 个工况
        </span>
      </div>
      {examples.length > 0 ? (
        <div className="example-list">
          {examples.map((example) => (
            <button
              key={`${example.title}:${example.request}`}
              className="example-item"
              title={example.request}
              type="button"
              onClick={() => onSelect(example.request)}
            >
              <span className="example-tag">{example.tag}</span>
              <strong>{example.title}</strong>
              <small>{example.request}</small>
            </button>
          ))}
        </div>
      ) : (
        <CompactEmpty text="没有匹配工况。" />
      )}
    </div>
  );
}

function HistoryList({
  activeHistoryId,
  history,
  recentlyClearedCount,
  onClear,
  onUndoClear,
  onSelect
}: {
  activeHistoryId: string | null;
  history: RunHistoryItem[];
  recentlyClearedCount: number;
  onClear: () => void;
  onUndoClear: () => void;
  onSelect: (item: RunHistoryItem) => void;
}) {
  return (
    <>
      <div className="side-panel-actions">
        <span>{history.length > 0 ? `${history.length} 条记录` : "无历史记录"}</span>
        <button
          className="clear-history-button"
          title="清空历史"
          type="button"
          aria-label="清空运行历史"
          disabled={history.length === 0}
          onClick={onClear}
        >
          <Trash2 aria-hidden="true" size={16} />
          <span>清空</span>
        </button>
      </div>
      {recentlyClearedCount > 0 && (
        <div className="undo-clear" role="status" aria-live="polite">
          <span>已清空 {recentlyClearedCount} 条记录</span>
          <button type="button" onClick={onUndoClear}>
            恢复
          </button>
        </div>
      )}
      {history.length > 0 ? (
        <div className="history-list">
          {history.map((item) => (
            <button
              key={item.id}
              className={`history-item ${item.id === activeHistoryId ? "active" : ""}`}
              type="button"
              onClick={() => onSelect(item)}
            >
              <HistoryState result={item.result} />
              <strong>{historyTitle(item.result)}</strong>
              <small>{historyMeta(item)}</small>
              <span>{item.request}</span>
            </button>
          ))}
        </div>
      ) : (
        <CompactEmpty text="运行后显示最近结果，便于回看不同请求。" />
      )}
    </>
  );
}

function HistoryState({ result }: { result: StudioRunResponse }) {
  const outcome = runOutcome(result);
  return <span className={`history-state ${outcome.tone}`}>{outcome.label}</span>;
}

function FactList({ facts }: { facts: DisplayItem[] }) {
  if (facts.length === 0) {
    return <CompactEmpty text="运行后显示几何、材料、载荷和网格摘要。" />;
  }
  return (
    <dl className="fact-list">
      {facts.map((fact) => (
        <div key={fact.label}>
          <dt>{fact.label}</dt>
          <dd>{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}
