import type { TaskSummary } from "../types";
import { arrayValue, formatNumber, formatUnknownNumber, textValue } from "./format";

export function geometryLabel(
  geometry: Record<string, unknown> | null,
  dimensions: Record<string, unknown> | null
) {
  if (!geometry) {
    return "N/A";
  }
  const type = textValue(geometry.type, "unknown");
  if (!dimensions) {
    return type;
  }
  const dimensionText = Object.entries(dimensions)
    .map(([key, value]) => `${key}=${formatUnknownNumber(value)}mm`)
    .join(", ");
  return `${type} · ${dimensionText}`;
}

export function materialLabel(material: Record<string, unknown> | null) {
  if (!material) {
    return "N/A";
  }
  const type = textValue(material.type, "isotropic");
  const elastic = formatUnknownNumber(material.E);
  const nu = formatUnknownNumber(material.nu);
  return `${type} · E=${elastic}MPa · ν=${nu}`;
}

export function loadLabel(load: Record<string, unknown> | undefined) {
  if (!load) {
    return "N/A";
  }
  const type = textValue(load.type, "load");
  const magnitude = formatUnknownNumber(load.magnitude);
  const region = textValue(load.region, "region");
  const direction = arrayValue(load.direction)
    .map((item) => formatUnknownNumber(item))
    .join(", ");
  return `${type} · ${magnitude} · ${region} · [${direction}]`;
}

export function boundaryLabel(boundary: Record<string, unknown> | undefined, count: number) {
  if (!boundary) {
    return "N/A";
  }
  const type = textValue(boundary.type, "bc");
  const region = textValue(boundary.region, "region");
  const dofs = arrayValue(boundary.dofs)
    .map((item) => textValue(item, ""))
    .filter(Boolean);
  return `${type} · ${region} · ${dofs.join("/") || "dofs"}${count > 1 ? ` · ${count} 组` : ""}`;
}

export function meshLabel(
  mesh: Record<string, unknown> | null,
  meshResult: TaskSummary["mesh_result"]
) {
  const element = textValue(mesh?.element_type, "element");
  const seed = mesh?.seed_size !== undefined ? `${formatUnknownNumber(mesh.seed_size)}mm` : "N/A";
  const count =
    meshResult?.element_count !== undefined && meshResult.node_count !== undefined
      ? ` · ${meshResult.node_count} 节点 / ${meshResult.element_count} 单元`
      : "";
  return `${element} · seed=${seed}${count}`;
}
