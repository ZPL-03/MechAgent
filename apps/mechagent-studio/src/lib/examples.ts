import type { StudioCapability, StudioExample } from "../types";
import { DEFAULT_EXAMPLES } from "./constants";
import type { Example, ExampleFilter } from "./uiTypes";

export function filterExamples(examples: Example[], filter: ExampleFilter, query: string) {
  const normalizedQuery = normalizeSearchText(query);
  return examples.filter((example) => {
    if (!exampleMatchesFilter(example, filter)) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    return normalizeSearchText(`${example.tag} ${example.title} ${example.request}`).includes(
      normalizedQuery
    );
  });
}

function exampleMatchesFilter(example: Example, filter: ExampleFilter) {
  if (filter === "all") {
    return true;
  }
  const haystack = normalizeSearchText(`${example.tag} ${example.title} ${example.request}`);
  if (filter === "beam") {
    return haystack.includes("梁") || haystack.includes("beam");
  }
  if (filter === "plate") {
    return haystack.includes("板") || haystack.includes("plate");
  }
  if (filter === "solid") {
    return haystack.includes("实体") || haystack.includes("solid") || haystack.includes("block");
  }
  return (
    haystack.includes("开孔") ||
    haystack.includes("孔") ||
    haystack.includes("hole") ||
    haystack.includes("perforated")
  );
}

function normalizeSearchText(value: string) {
  return value.trim().toLocaleLowerCase("zh-CN");
}

export function displayExamples(
  catalogExamples: StudioExample[],
  capabilities: StudioCapability[]
): Example[] {
  if (catalogExamples.length > 0) {
    return catalogExamples.map((example) => ({
      tag: catalogExampleTag(example),
      title: example.title,
      request: example.request
    }));
  }
  const examples = capabilities.flatMap((capability) =>
    capability.example_requests.map((requestText) => ({
      tag: exampleTag(capability, requestText),
      title: exampleTitle(capability, requestText),
      request: requestText
    }))
  );
  return examples.length > 0 ? examples : DEFAULT_EXAMPLES;
}

function catalogExampleTag(example: StudioExample) {
  const knownTag = example.tags.find((tag) =>
    ["梁", "板", "实体", "beam", "plate", "solid"].includes(tag)
  );
  if (knownTag === "beam") {
    return "梁";
  }
  if (knownTag === "plate") {
    return "板";
  }
  if (knownTag === "solid") {
    return "实体";
  }
  if (knownTag) {
    return knownTag;
  }
  if (example.geometry_type === "beam") {
    return "梁";
  }
  if (example.geometry_type === "plate") {
    return "板";
  }
  if (example.geometry_type === "solid") {
    return "实体";
  }
  return example.capability_id;
}

function exampleTag(capability: StudioCapability, requestText: string) {
  const text = requestText.toLowerCase();
  if (text.includes("beam") || requestText.includes("梁")) {
    return "梁";
  }
  if (text.includes("plate") || requestText.includes("板")) {
    return "板";
  }
  if (text.includes("solid") || requestText.includes("实体") || requestText.includes("长方体")) {
    return "实体";
  }
  return capability.physics_domain || capability.analysis_type || "能力";
}

function exampleTitle(capability: StudioCapability, requestText: string) {
  const text = requestText.toLowerCase();
  if (text.includes("beam") || requestText.includes("梁")) {
    return `${capability.title} · 梁`;
  }
  if (text.includes("plate") || requestText.includes("板")) {
    return `${capability.title} · 板`;
  }
  if (text.includes("solid") || requestText.includes("实体") || requestText.includes("长方体")) {
    return `${capability.title} · 实体`;
  }
  return capability.title;
}
