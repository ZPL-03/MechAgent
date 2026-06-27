import { useEffect, useId, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { VisualizationScene } from "./types";

export type RenderMode = VisualizationScene["mode"];
type SceneField = NonNullable<VisualizationScene["fields"]>[number];
type SceneNode = VisualizationScene["nodes"][number];
type SceneLoad = NonNullable<VisualizationScene["loads"]>[number];
type SceneBoundaryCondition = NonNullable<VisualizationScene["boundary_conditions"]>[number];
type ViewPreset = "iso" | "top" | "front" | "right";
type AxisName = "x" | "y" | "z";
type SceneBounds = {
  min: [number, number, number];
  max: [number, number, number];
};

const AXIS_INDEX: Record<AxisName, 0 | 1 | 2> = {
  x: 0,
  y: 1,
  z: 2
};

type Props = {
  scene: VisualizationScene;
  mode: RenderMode;
};

const GEOMETRY_COLORS = {
  fill: new THREE.Color("#dbeafe"),
  edge: new THREE.Color("#174c7d"),
  mesh: new THREE.Color("#5b6b7e"),
  result: new THREE.Color("#2563eb"),
  point: new THREE.Color("#dc2626")
};

const VIEW_PRESETS: Array<{ key: ViewPreset; label: string; title: string }> = [
  { key: "iso", label: "ISO", title: "等轴视图" },
  { key: "top", label: "TOP", title: "俯视图" },
  { key: "front", label: "FRONT", title: "前视图" },
  { key: "right", label: "RIGHT", title: "右视图" }
];

export function ThreeViewport({ scene, mode }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const axisHostRef = useRef<HTMLDivElement | null>(null);
  const fieldSelectId = useId();
  const [selectedFieldKey, setSelectedFieldKey] = useState("");
  // 让尺寸变化回调读取当前场景与模式，以便重新适配相机距离。
  const sceneRef = useRef(scene);
  const modeRef = useRef(mode);
  sceneRef.current = scene;
  modeRef.current = mode;
  const stateRef = useRef<{
    renderer: THREE.WebGLRenderer;
    threeScene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    controls: OrbitControls;
    root: THREE.Group;
    axisRenderer: THREE.WebGLRenderer;
    axisScene: THREE.Scene;
    axisCamera: THREE.OrthographicCamera;
    axisRoot: THREE.Group;
    resizeObserver: ResizeObserver;
    render: () => void;
  } | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    const axisHost = axisHostRef.current;
    if (!host || !axisHost) {
      return;
    }

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
      preserveDrawingBuffer: true
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(viewportClearColor(), 1);
    renderer.domElement.className = "three-canvas";
    host.appendChild(renderer.domElement);

    const axisRenderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance"
    });
    axisRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    axisRenderer.setClearColor(0x000000, 0);
    axisRenderer.domElement.className = "axis-gizmo-canvas";
    axisHost.appendChild(axisRenderer.domElement);

    const threeScene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enablePan = true;

    const root = new THREE.Group();
    threeScene.add(root);
    threeScene.add(new THREE.AmbientLight(0xffffff, 1.35));

    const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
    keyLight.position.set(2.5, 3.8, 4.5);
    threeScene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0xbfdcff, 0.75);
    fillLight.position.set(-4, -2, 3);
    threeScene.add(fillLight);

    const axisScene = new THREE.Scene();
    const axisCamera = new THREE.OrthographicCamera(-1.35, 1.35, 1.35, -1.35, 0.1, 10);
    axisCamera.position.set(0, 0, 4);
    axisCamera.lookAt(0, 0, 0);
    const axisRoot = buildAxisGizmoRoot();
    axisScene.add(axisRoot);
    axisScene.add(new THREE.AmbientLight(0xffffff, 1.45));
    const axisLight = new THREE.DirectionalLight(0xffffff, 1.15);
    axisLight.position.set(2, 3, 4);
    axisScene.add(axisLight);

    let pendingFrame = 0;
    const renderViewport = () => {
      axisRoot.quaternion.copy(camera.quaternion).invert();
      renderer.render(threeScene, camera);
      axisRenderer.render(axisScene, axisCamera);
    };
    const scheduleRender = () => {
      if (pendingFrame !== 0) {
        return;
      }
      pendingFrame = window.requestAnimationFrame(() => {
        pendingFrame = 0;
        renderViewport();
      });
    };

    const resizeObserver = new ResizeObserver(() => {
      const rect = host.getBoundingClientRect();
      const width = Math.max(rect.width, 1);
      const height = Math.max(rect.height, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      // 宽高比变化后重新适配相机距离，保证模型完整居中。
      refitCameraDistance(camera, controls, sceneRef.current, modeRef.current);

      const axisRect = axisHost.getBoundingClientRect();
      axisRenderer.setSize(Math.max(axisRect.width, 1), Math.max(axisRect.height, 1), false);
      scheduleRender();
    });
    resizeObserver.observe(host);
    resizeObserver.observe(axisHost);

    controls.addEventListener("change", scheduleRender);
    scheduleRender();

    stateRef.current = {
      renderer,
      threeScene,
      camera,
      controls,
      root,
      axisRenderer,
      axisScene,
      axisCamera,
      axisRoot,
      resizeObserver,
      render: scheduleRender
    };

    return () => {
      resizeObserver.disconnect();
      if (pendingFrame !== 0) {
        window.cancelAnimationFrame(pendingFrame);
      }
      controls.removeEventListener("change", scheduleRender);
      controls.dispose();
      disposeObject(root);
      disposeObject(axisRoot);
      renderer.dispose();
      axisRenderer.dispose();
      if (renderer.domElement.parentElement === host) {
        host.removeChild(renderer.domElement);
      }
      if (axisRenderer.domElement.parentElement === axisHost) {
        axisHost.removeChild(axisRenderer.domElement);
      }
      stateRef.current = null;
    };
  }, []);

  useEffect(() => {
    const state = stateRef.current;
    if (!state) {
      return;
    }
    const activeField = fieldByKey(scene, selectedFieldKey);
    rebuildScene(state.root, state.camera, state.controls, scene, mode, activeField);
    state.render();
  }, [scene, mode, selectedFieldKey]);

  // 主题切换时更新 3D 画布背景色（读取 --color-viewport-bg 令牌）。
  useEffect(() => {
    if (typeof MutationObserver === "undefined") {
      return undefined;
    }
    const observer = new MutationObserver(() => {
      const state = stateRef.current;
      if (!state) {
        return;
      }
      state.renderer.setClearColor(viewportClearColor(), 1);
      state.render();
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"]
    });
    return () => observer.disconnect();
  }, []);

  const fields = useMemo(() => resultFields(scene), [scene]);
  const activeField = fieldByKey(scene, selectedFieldKey);
  const summaryField = mode === "result" ? activeField : defaultField(scene);
  const summary = sceneSummary(scene, mode, summaryField);

  useEffect(() => {
    setSelectedFieldKey(defaultField(scene).key);
  }, [scene]);

  function applyView(view: ViewPreset) {
    const state = stateRef.current;
    if (!state) {
      return;
    }
    orientCamera(state.camera, state.controls, scene, mode, view);
    state.render();
  }

  return (
    <div className="three-viewport" aria-label={`${scene.geometry_type} ${summary.label} 3D 视图`}>
      <div ref={hostRef} className="three-stage" />
      <div
        ref={axisHostRef}
        className="axis-gizmo-stage"
        aria-label="跟随视角的 XYZ 全局坐标系"
      />
      <div className="three-overlay" aria-hidden="true">
        <span>{summary.label}</span>
        <span>{summary.mesh}</span>
        <span>{summary.result}</span>
      </div>
      <div className="three-controls" aria-label="3D 视图控制">
        {mode === "result" && fields.length > 1 && (
          <div className="field-switch" role="group" aria-label="结果场量">
            <label htmlFor={fieldSelectId}>场量</label>
            <select
              id={fieldSelectId}
              value={activeField.key}
              onChange={(event) => setSelectedFieldKey(event.target.value)}
            >
              {fields.map((field) => (
                <option key={field.key} value={field.key}>
                  {field.name}
                  {field.unit ? ` (${field.unit})` : ""}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="view-switch" role="group" aria-label="视角切换">
          {VIEW_PRESETS.map((preset) => (
            <button
              key={preset.key}
              type="button"
              title={preset.title}
              onClick={() => applyView(preset.key)}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </div>
      {mode === "result" && (
        <div className="three-legend" aria-hidden="true">
          <span>{summary.scalarLabel}</span>
          <i />
          <div>
            <small>{formatScalar(activeField.min)}</small>
            <small>{formatScalar(activeField.max)}</small>
          </div>
          <small>变形 ×{formatScale(scene.deformation_scale)}</small>
        </div>
      )}
    </div>
  );
}

function viewportClearColor(): THREE.Color {
  if (typeof window !== "undefined") {
    const value = getComputedStyle(document.documentElement)
      .getPropertyValue("--color-viewport-bg")
      .trim();
    if (value) {
      try {
        return new THREE.Color(value);
      } catch {
        // 回退到默认浅色背景。
      }
    }
  }
  return new THREE.Color("#f7faff");
}

function buildAxisGizmoRoot() {
  const root = new THREE.Group();
  root.add(buildAxisArrow(new THREE.Vector3(1, 0, 0), "#d92d20", "X"));
  root.add(buildAxisArrow(new THREE.Vector3(0, 1, 0), "#0f9f59", "Y"));
  root.add(buildAxisArrow(new THREE.Vector3(0, 0, 1), "#2563eb", "Z"));
  const origin = new THREE.Mesh(
    new THREE.SphereGeometry(0.055, 18, 12),
    new THREE.MeshStandardMaterial({
      color: "#24364d",
      roughness: 0.42,
      metalness: 0.02
    })
  );
  root.add(origin);
  return root;
}

function buildAxisArrow(direction: THREE.Vector3, color: string, label: string) {
  const group = new THREE.Group();
  const axis = direction.clone().normalize();
  const quaternion = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), axis);

  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(0.034, 0.034, 0.74, 20),
    new THREE.MeshStandardMaterial({
      color,
      roughness: 0.4,
      metalness: 0.03
    })
  );
  shaft.position.copy(axis.clone().multiplyScalar(0.36));
  shaft.quaternion.copy(quaternion);
  group.add(shaft);

  const head = new THREE.Mesh(
    new THREE.ConeGeometry(0.095, 0.24, 26),
    new THREE.MeshStandardMaterial({
      color,
      roughness: 0.4,
      metalness: 0.03
    })
  );
  head.position.copy(axis.clone().multiplyScalar(0.86));
  head.quaternion.copy(quaternion);
  group.add(head);

  const sprite = buildAxisLabel(label, color);
  sprite.position.copy(axis.clone().multiplyScalar(1.14));
  group.add(sprite);
  return group;
}

function buildAxisLabel(text: string, color: string) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext("2d");
  if (context) {
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.lineWidth = 8;
    context.strokeStyle = "rgba(255, 255, 255, 0.92)";
    context.shadowColor = "rgba(15, 42, 75, 0.22)";
    context.shadowBlur = 8;
    context.shadowOffsetX = 0;
    context.shadowOffsetY = 2;
    context.font = "800 58px Inter, Segoe UI, Arial, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.strokeText(text, 64, 66);
    context.shadowColor = "transparent";
    context.fillStyle = color;
    context.fillText(text, 64, 66);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false,
      depthWrite: false
    })
  );
  sprite.scale.set(0.42, 0.42, 1);
  sprite.renderOrder = 20;
  return sprite;
}

function rebuildScene(
  root: THREE.Group,
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  scene: VisualizationScene,
  mode: RenderMode,
  field: SceneField
) {
  for (const child of [...root.children]) {
    root.remove(child);
    disposeObject(child);
  }

  const bounds = viewBounds(scene, mode);
  const center = midpoint(bounds.min, bounds.max);
  const span = Math.max(
    bounds.max[0] - bounds.min[0],
    bounds.max[1] - bounds.min[1],
    bounds.max[2] - bounds.min[2],
    1.0
  );

  root.add(buildReferenceGrid(bounds, span));

  if (mode === "geometry") {
    root.add(buildGeometryActor(scene, span, center));
  } else if (mode === "mesh") {
    root.add(buildMeshActor(scene, false, field));
  } else {
    root.add(buildMeshActor(scene, true, field));
  }
  if (mode === "geometry") {
    root.add(buildBoundaryLoadOverlay(scene, bounds, span));
  }

  orientCamera(camera, controls, scene, mode, "iso");
}

function buildReferenceGrid(bounds: {
  min: [number, number, number];
  max: [number, number, number];
}, span: number) {
  const xSpan = Math.max(bounds.max[0] - bounds.min[0], span * 0.2, 1);
  const zSpan = Math.max(bounds.max[2] - bounds.min[2], span * 0.2, 1);
  const horizontalSpan = Math.max(xSpan, zSpan);
  const verticalSpan = Math.max(bounds.max[1] - bounds.min[1], 0);
  const margin = Math.max(horizontalSpan * 0.18, span * 0.05, 1);
  const minX = bounds.min[0] - margin;
  const maxX = bounds.max[0] + margin;
  const minZ = bounds.min[2] - margin;
  const maxZ = bounds.max[2] + margin;
  const y = bounds.min[1] - Math.max(span * 0.012, verticalSpan * 0.04, 0.01);
  const step = Math.max(horizontalSpan / 14, 1);
  const xDivisions = Math.max(8, Math.min(48, Math.round((maxX - minX) / step)));
  const zDivisions = Math.max(8, Math.min(48, Math.round((maxZ - minZ) / step)));
  const positions: number[] = [];

  for (let index = 0; index <= xDivisions; index += 1) {
    const x = minX + ((maxX - minX) * index) / xDivisions;
    positions.push(x, y, minZ, x, y, maxZ);
  }
  for (let index = 0; index <= zDivisions; index += 1) {
    const z = minZ + ((maxZ - minZ) * index) / zDivisions;
    positions.push(minX, y, z, maxX, y, z);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({
      color: 0xd8e3ef,
      transparent: true,
      opacity: 0.92
    })
  );
}

function buildGeometryActor(
  scene: VisualizationScene,
  span: number,
  center: [number, number, number]
): THREE.Object3D {
  const dims = scene.dimensions;
  const length = positive(dims.length, span);
  const width = positive(dims.width, Math.max(span * 0.2, 1));
  const height = positive(dims.height, Math.max(span * 0.15, 1));
  const thickness = positive(dims.thickness, Math.max(Math.min(length, width) * 0.08, 1));
  const geometryType = scene.geometry_type.toLowerCase();
  const holes = plateHoles(dims, length, width);
  const slots = plateSlots(dims, length, width);

  let geometry: THREE.BufferGeometry;
  if (geometryType === "beam") {
    geometry = new THREE.BoxGeometry(length, width, height);
  } else if (geometryType === "plate" && (holes.length > 0 || slots.length > 0)) {
    geometry = buildPerforatedPlateGeometry(length, width, thickness, holes, slots);
  } else if (geometryType === "plate") {
    geometry = new THREE.BoxGeometry(length, thickness, width);
  } else {
    geometry = new THREE.BoxGeometry(length, height, width);
  }

  const mesh = new THREE.Mesh(
    geometry,
    new THREE.MeshStandardMaterial({
      color: GEOMETRY_COLORS.fill,
      transparent: true,
      opacity: 0.35,
      roughness: 0.32,
      metalness: 0.04,
      side: THREE.DoubleSide
    })
  );

  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(geometry),
    new THREE.LineBasicMaterial({
      color: GEOMETRY_COLORS.edge,
      transparent: true,
      opacity: 0.95
    })
  );

  const group = new THREE.Group();
  group.add(mesh);
  group.add(edges);
  group.position.set(center[0], center[1], center[2]);
  return group;
}

function buildBoundaryLoadOverlay(
  scene: VisualizationScene,
  bounds: SceneBounds,
  span: number
): THREE.Object3D {
  const group = new THREE.Group();
  for (const boundary of scene.boundary_conditions ?? []) {
    group.add(buildBoundaryConditionMarker(boundary, bounds, span));
  }
  for (const load of scene.loads ?? []) {
    group.add(buildLoadMarker(scene, load, bounds, span));
  }
  group.traverse((object) => {
    object.renderOrder = 30;
    const material = (object as THREE.Object3D & { material?: THREE.Material | THREE.Material[] }).material;
    if (Array.isArray(material)) {
      material.forEach(markOverlayMaterial);
    } else if (material) {
      markOverlayMaterial(material);
    }
  });
  return group;
}

function markOverlayMaterial(material: THREE.Material) {
  material.depthTest = false;
  material.depthWrite = false;
}

function buildBoundaryConditionMarker(
  boundary: SceneBoundaryCondition,
  bounds: SceneBounds,
  span: number
): THREE.Object3D {
  const region = normalizeToken(boundary.region);
  if (region.includes("edge")) {
    return buildEdgeSupportMarker(bounds, span);
  }
  const group = new THREE.Group();
  const x = region.includes("right") || region.includes("end") ? bounds.max[0] : bounds.min[0];
  const side = x <= midpoint(bounds.min, bounds.max)[0] ? -1 : 1;
  const center = new THREE.Vector3(x, (bounds.min[1] + bounds.max[1]) / 2, (bounds.min[2] + bounds.max[2]) / 2);
  const width = Math.max(bounds.max[2] - bounds.min[2], span * 0.12);
  const height = Math.max(bounds.max[1] - bounds.min[1], span * 0.1);
  const thickness = Math.max(span * 0.012, 0.6);
  const clamp = new THREE.Mesh(
    new THREE.BoxGeometry(thickness, height + span * 0.08, width + span * 0.08),
    new THREE.MeshStandardMaterial({
      color: "#162033",
      transparent: true,
      opacity: 0.72,
      roughness: 0.48,
      metalness: 0.02
    })
  );
  clamp.position.copy(center).add(new THREE.Vector3(side * thickness * 0.7, 0, 0));
  group.add(clamp);

  const hatchCount = 7;
  const hatchPositions: number[] = [];
  const hatchX = x + side * thickness * 1.6;
  for (let index = 0; index < hatchCount; index += 1) {
    const z = bounds.min[2] + ((index + 0.5) / hatchCount) * (bounds.max[2] - bounds.min[2] || width);
    const y0 = bounds.min[1] - span * 0.03;
    const y1 = bounds.max[1] + span * 0.08;
    hatchPositions.push(hatchX, y0, z - span * 0.018, hatchX + side * span * 0.045, y1, z + span * 0.018);
  }
  const hatchGeometry = new THREE.BufferGeometry();
  hatchGeometry.setAttribute("position", new THREE.Float32BufferAttribute(hatchPositions, 3));
  group.add(
    new THREE.LineSegments(
      hatchGeometry,
      new THREE.LineBasicMaterial({ color: "#162033", transparent: true, opacity: 0.62 })
    )
  );
  return group;
}

function buildEdgeSupportMarker(bounds: SceneBounds, span: number): THREE.Object3D {
  const group = new THREE.Group();
  const y = bounds.max[1] + Math.max(span * 0.002, 0.05);
  const radius = Math.max(span * 0.0025, 0.12);
  const color = "#155e75";
  const corners = [
    new THREE.Vector3(bounds.min[0], y, bounds.min[2]),
    new THREE.Vector3(bounds.max[0], y, bounds.min[2]),
    new THREE.Vector3(bounds.max[0], y, bounds.max[2]),
    new THREE.Vector3(bounds.min[0], y, bounds.max[2])
  ];
  for (let index = 0; index < corners.length; index += 1) {
    group.add(buildCylinderBetween(corners[index], corners[(index + 1) % corners.length], radius, color, 0.76));
  }
  for (const point of supportSamplePoints(bounds, y)) {
    group.add(buildEdgeSupportCone(point, bounds, span, color));
  }
  return group;
}

function buildEdgeSupportCone(
  point: THREE.Vector3,
  bounds: SceneBounds,
  span: number,
  color: string
) {
  const center = new THREE.Vector3(
    (bounds.min[0] + bounds.max[0]) / 2,
    point.y,
    (bounds.min[2] + bounds.max[2]) / 2
  );
  const inward = center.sub(point);
  inward.y = 0;
  if (inward.lengthSq() <= 1e-9) {
    inward.set(0, 0, 1);
  }
  inward.normalize();
  const height = Math.max(span * 0.035, 1.6);
  const support = new THREE.Mesh(
    new THREE.ConeGeometry(Math.max(span * 0.012, 0.55), height, 4),
    new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.74, roughness: 0.4 })
  );
  support.quaternion.copy(
    new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), inward)
  );
  support.position.copy(point).add(inward.clone().multiplyScalar(-height / 2));
  return support;
}

function supportSamplePoints(bounds: SceneBounds, y: number) {
  const points: THREE.Vector3[] = [];
  const zCenter = (bounds.min[2] + bounds.max[2]) / 2;
  const xCenter = (bounds.min[0] + bounds.max[0]) / 2;
  for (const x of [bounds.min[0], xCenter, bounds.max[0]]) {
    points.push(new THREE.Vector3(x, y, bounds.min[2]));
    points.push(new THREE.Vector3(x, y, bounds.max[2]));
  }
  for (const z of [zCenter]) {
    points.push(new THREE.Vector3(bounds.min[0], y, z));
    points.push(new THREE.Vector3(bounds.max[0], y, z));
  }
  return points;
}

function buildLoadMarker(
  scene: VisualizationScene,
  load: SceneLoad,
  bounds: SceneBounds,
  span: number
): THREE.Object3D {
  const group = new THREE.Group();
  const type = normalizeToken(load.type);
  const region = normalizeToken(load.region);
  const direction = viewDirection(scene, load.direction);
  const arrowLength = Math.max(span * 0.085, 4);
  const color = "#dc2626";

  if (type.includes("pressure") && isEndFaceRegion(region)) {
    for (const origin of endFaceLoadOrigins(bounds, region, direction, arrowLength)) {
      group.add(buildArrow(origin, direction, arrowLength, color, span));
    }
    return group;
  }

  if (type.includes("pressure") || region.includes("surface")) {
    for (const origin of pressureOrigins(scene, bounds, direction, arrowLength)) {
      group.add(buildArrow(origin, direction, arrowLength, color, span));
    }
    return group;
  }

  if (type.includes("line") || region.includes("span")) {
    for (const origin of lineLoadOrigins(bounds, direction, arrowLength)) {
      group.add(buildArrow(origin, direction, arrowLength, color, span));
    }
    return group;
  }

  const pointArrowLength = arrowLength * 1.15;
  for (const origin of pointLoadOrigins(bounds, region, direction, pointArrowLength)) {
    group.add(buildArrow(origin, direction, pointArrowLength, color, span));
  }
  return group;
}

function buildArrow(
  origin: THREE.Vector3,
  direction: THREE.Vector3,
  length: number,
  color: string,
  span: number
) {
  const unit = direction.clone().normalize();
  const group = new THREE.Group();
  const headLength = Math.max(length * 0.3, span * 0.018, 1.2);
  const headRadius = Math.max(length * 0.07, span * 0.005, 0.35);
  const shaftRadius = Math.max(length * 0.018, span * 0.0022, 0.14);
  const tip = origin.clone().add(unit.clone().multiplyScalar(length));
  const shaftEnd = tip.clone().add(unit.clone().multiplyScalar(-headLength));
  group.add(buildCylinderBetween(origin, shaftEnd, shaftRadius, color, 0.92));
  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(headRadius, headLength, 20),
    new THREE.MeshStandardMaterial({
      color,
      transparent: true,
      opacity: 0.94,
      roughness: 0.38,
      metalness: 0.02
    })
  );
  cone.position.copy(tip.clone().add(unit.clone().multiplyScalar(-headLength / 2)));
  cone.quaternion.copy(
    new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), unit)
  );
  group.add(cone);
  group.traverse((object) => {
    const material = (object as THREE.Object3D & { material?: THREE.Material | THREE.Material[] }).material;
    if (Array.isArray(material)) {
      material.forEach(markOverlayMaterial);
    } else if (material) {
      markOverlayMaterial(material);
    }
  });
  return group;
}

function pressureOrigins(
  scene: VisualizationScene,
  bounds: SceneBounds,
  direction: THREE.Vector3,
  tailDistance: number
) {
  return surfacePressureTargets(scene, bounds, direction).map((target) =>
    target.add(direction.clone().multiplyScalar(-tailDistance))
  );
}

function surfacePressureTargets(
  scene: VisualizationScene,
  bounds: SceneBounds,
  direction: THREE.Vector3
) {
  const normalAxis = dominantAxis(direction);
  const planeAxes = (["x", "y", "z"] as AxisName[]).filter((axis) => axis !== normalAxis);
  const [uAxis, vAxis] = planeAxes;
  const normalValue = surfaceAxisValue(bounds, direction, normalAxis);
  const uSpan = axisSpan(bounds, uAxis);
  const vSpan = axisSpan(bounds, vAxis);
  const targetSpacing = Math.max(Math.max(uSpan, vSpan, 1) / 6, 1);
  const uCount = distributedCount(uSpan, targetSpacing, 3, 9);
  const vCount = distributedCount(vSpan, targetSpacing, 3, 8);
  const targets: THREE.Vector3[] = [];
  for (const u of distributedAxisValues(bounds, uAxis, uCount)) {
    for (const v of distributedAxisValues(bounds, vAxis, vCount)) {
      const target = vectorFromAxisValues({
        [normalAxis]: normalValue,
        [uAxis]: u,
        [vAxis]: v
      } as Record<AxisName, number>);
      if (!isInsidePlateHole(scene, bounds, target, normalAxis)) {
        targets.push(target);
      }
    }
  }
  return targets.length > 0
    ? targets
    : [midpointVector(bounds).setComponent(AXIS_INDEX[normalAxis], normalValue)];
}

function lineLoadOrigins(bounds: SceneBounds, direction: THREE.Vector3, tailDistance: number) {
  const origins: THREE.Vector3[] = [];
  const count = 7;
  const z = (bounds.min[2] + bounds.max[2]) / 2;
  for (let index = 0; index < count; index += 1) {
    const x = bounds.min[0] + ((index + 0.5) / count) * (bounds.max[0] - bounds.min[0]);
    const target = new THREE.Vector3(x, surfaceAxisValue(bounds, direction, "y"), z);
    origins.push(target.add(direction.clone().multiplyScalar(-tailDistance)));
  }
  return origins;
}

function pointLoadOrigins(
  bounds: SceneBounds,
  region: string,
  direction: THREE.Vector3,
  tailDistance: number
) {
  const x =
    region.includes("root") || region.includes("left")
      ? bounds.min[0]
      : bounds.max[0];
  const target = new THREE.Vector3(
    x,
    (bounds.min[1] + bounds.max[1]) / 2,
    (bounds.min[2] + bounds.max[2]) / 2
  ).add(direction.clone().multiplyScalar(-tailDistance));
  return [target];
}

function endFaceLoadOrigins(
  bounds: SceneBounds,
  region: string,
  direction: THREE.Vector3,
  tailDistance: number
) {
  const x =
    region.includes("root") || region.includes("left")
      ? bounds.min[0]
      : bounds.max[0];
  const yValues = [
    bounds.min[1] + (bounds.max[1] - bounds.min[1]) * 0.3,
    bounds.min[1] + (bounds.max[1] - bounds.min[1]) * 0.7
  ];
  const zValues = [
    bounds.min[2] + (bounds.max[2] - bounds.min[2]) * 0.3,
    bounds.min[2] + (bounds.max[2] - bounds.min[2]) * 0.7
  ];
  const origins: THREE.Vector3[] = [];
  for (const y of yValues) {
    for (const z of zValues) {
      origins.push(new THREE.Vector3(x, y, z).add(direction.clone().multiplyScalar(-tailDistance)));
    }
  }
  return origins;
}

function dominantAxis(direction: THREE.Vector3): AxisName {
  const axes: AxisName[] = ["x", "y", "z"];
  return axes.reduce((selected, axis) =>
    Math.abs(direction[axis]) > Math.abs(direction[selected]) ? axis : selected
  );
}

function surfaceAxisValue(bounds: SceneBounds, direction: THREE.Vector3, axis: AxisName) {
  const index = AXIS_INDEX[axis];
  return direction[axis] < 0 ? bounds.max[index] : bounds.min[index];
}

function axisSpan(bounds: SceneBounds, axis: AxisName) {
  const index = AXIS_INDEX[axis];
  return Math.max(bounds.max[index] - bounds.min[index], 0);
}

function distributedCount(span: number, spacing: number, minCount: number, maxCount: number) {
  if (span <= 1e-9) {
    return 1;
  }
  return Math.max(minCount, Math.min(maxCount, Math.round(span / spacing) + 1));
}

function distributedAxisValues(bounds: SceneBounds, axis: AxisName, count: number) {
  const index = AXIS_INDEX[axis];
  const min = bounds.min[index];
  const max = bounds.max[index];
  if (count <= 1 || Math.abs(max - min) <= 1e-9) {
    return [(min + max) / 2];
  }
  const values: number[] = [];
  for (let indexValue = 0; indexValue < count; indexValue += 1) {
    values.push(min + ((indexValue + 0.5) / count) * (max - min));
  }
  return values;
}

function vectorFromAxisValues(values: Record<AxisName, number>) {
  return new THREE.Vector3(values.x, values.y, values.z);
}

function midpointVector(bounds: SceneBounds) {
  return new THREE.Vector3(
    (bounds.min[0] + bounds.max[0]) / 2,
    (bounds.min[1] + bounds.max[1]) / 2,
    (bounds.min[2] + bounds.max[2]) / 2
  );
}

function isInsidePlateHole(
  scene: VisualizationScene,
  bounds: SceneBounds,
  target: THREE.Vector3,
  normalAxis: AxisName
) {
  if (normalAxis !== "y" || scene.geometry_type.toLowerCase() !== "plate") {
    return false;
  }
  const length = positive(scene.dimensions.length, axisSpan(bounds, "x"));
  const width = positive(scene.dimensions.width, axisSpan(bounds, "z"));
  const holes = plateHoles(scene.dimensions, length, width);
  if (holes.length === 0) {
    return false;
  }
  const xSpan = Math.max(axisSpan(bounds, "x"), 1e-9);
  const zSpan = Math.max(axisSpan(bounds, "z"), 1e-9);
  const plateX = ((target.x - bounds.min[0]) / xSpan) * length;
  const plateY = ((target.z - bounds.min[2]) / zSpan) * width;
  return holes.some((hole) => {
    const dx = plateX - hole.centerX;
    const dy = plateY - hole.centerY;
    return Math.hypot(dx, dy) <= hole.radius * 1.12;
  });
}

function buildCylinderBetween(
  start: THREE.Vector3,
  end: THREE.Vector3,
  radius: number,
  color: string,
  opacity: number
) {
  const direction = end.clone().sub(start);
  const length = direction.length();
  const geometry = new THREE.CylinderGeometry(radius, radius, Math.max(length, 1e-6), 12);
  const material = new THREE.MeshStandardMaterial({
    color,
    transparent: true,
    opacity,
    roughness: 0.42,
    metalness: 0.02
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.copy(start.clone().add(end).multiplyScalar(0.5));
  mesh.quaternion.copy(
    new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize())
  );
  return mesh;
}

function viewDirection(scene: VisualizationScene, direction: [number, number, number]) {
  const mapped = viewVector(scene, direction);
  const vector = new THREE.Vector3(mapped[0], mapped[1], mapped[2]);
  if (vector.length() <= 1e-9) {
    return new THREE.Vector3(0, -1, 0);
  }
  return vector.normalize();
}

function viewVector(
  scene: VisualizationScene,
  vector: [number, number, number]
): [number, number, number] {
  const geometryType = scene.geometry_type.toLowerCase();
  if (geometryType === "plate" || geometryType === "solid") {
    return [vector[0], vector[2], vector[1]];
  }
  return vector;
}

function normalizeToken(value: string) {
  return value.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

function isEndFaceRegion(region: string) {
  const tokens = region.split("_").filter(Boolean);
  return tokens.includes("face") && !tokens.includes("surface");
}

function buildMeshActor(
  scene: VisualizationScene,
  deformed: boolean,
  field: SceneField
): THREE.Object3D {
  if (scene.geometry_type.toLowerCase() === "beam") {
    return buildBeamFieldActor(scene, deformed, field);
  }

  const group = new THREE.Group();
  const points = new Map(scene.nodes.map((node) => [node.id, node]));
  const positions: number[] = [];
  const colors: number[] = [];
  const linePositions: number[] = [];
  const scalarRange = field.max - field.min || 1;
  const surfacePositions: number[] = [];
  const surfaceColors: number[] = [];

  for (const element of scene.elements) {
    const triangles = elementSurfaceTriangles(element.nodes);
    for (const triangle of triangles) {
      for (const nodeIndex of triangle) {
        const node = points.get(nodeIndex);
        if (!node) {
          continue;
        }
        const position = viewNodePosition(scene, node, deformed);
        surfacePositions.push(...position);
        if (deformed) {
          const color = scalarColor(nodeFieldValue(node, field), field.min, scalarRange);
          surfaceColors.push(color.r, color.g, color.b);
        } else {
          surfaceColors.push(0.86, 0.91, 0.96);
        }
      }
    }
  }

  if (surfacePositions.length > 0) {
    const surfaceGeometry = new THREE.BufferGeometry();
    surfaceGeometry.setAttribute("position", new THREE.Float32BufferAttribute(surfacePositions, 3));
    surfaceGeometry.setAttribute("color", new THREE.Float32BufferAttribute(surfaceColors, 3));
    surfaceGeometry.computeVertexNormals();
    const surface = new THREE.Mesh(
      surfaceGeometry,
      new THREE.MeshBasicMaterial({
        side: THREE.DoubleSide,
        transparent: true,
        vertexColors: true,
        opacity: deformed ? (field.kind === "stress" ? 0.92 : 0.78) : 0.08,
        depthWrite: false
      })
    );
    surface.renderOrder = deformed ? 1 : 0;
    group.add(surface);
  }

  for (const element of scene.elements) {
    const edges = elementEdges(element.nodes);
    for (const [startIndex, endIndex] of edges) {
      const start = points.get(startIndex);
      const end = points.get(endIndex);
      if (!start || !end) {
        continue;
      }
      const startPosition = viewNodePosition(scene, start, deformed);
      const endPosition = viewNodePosition(scene, end, deformed);
      linePositions.push(...startPosition, ...endPosition);
    }
  }

  const lineGeometry = new THREE.BufferGeometry();
  lineGeometry.setAttribute("position", new THREE.Float32BufferAttribute(linePositions, 3));
  const lineMaterial = new THREE.LineBasicMaterial({
    color: deformed ? (field.kind === "stress" ? 0x334155 : GEOMETRY_COLORS.result) : GEOMETRY_COLORS.edge,
    transparent: true,
    opacity: deformed ? (field.kind === "stress" ? 0.26 : 0.72) : 0.98,
    depthTest: deformed,
    depthWrite: false
  });
  const lineSegments = new THREE.LineSegments(lineGeometry, lineMaterial);
  lineSegments.renderOrder = deformed ? 2 : 3;
  group.add(lineSegments);

  for (const node of scene.nodes) {
    const position = viewNodePosition(scene, node, deformed);
    positions.push(...position);
    const color = scalarColor(nodeFieldValue(node, field), field.min, scalarRange);
    colors.push(color.r, color.g, color.b);
  }

  const pointGeometry = new THREE.BufferGeometry();
  pointGeometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  if (deformed) {
    pointGeometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  }
  const pointMaterial = new THREE.PointsMaterial({
    color: deformed ? 0xffffff : GEOMETRY_COLORS.edge,
    size: deformed ? 4.5 : 2.2,
    sizeAttenuation: true,
    vertexColors: deformed,
    transparent: true,
    opacity: deformed ? 0.92 : 0.48,
    depthTest: deformed,
    depthWrite: false
  });
  const nodePoints = new THREE.Points(pointGeometry, pointMaterial);
  nodePoints.renderOrder = deformed ? 3 : 4;
  group.add(nodePoints);

  return group;
}

type PlateHole = {
  radius: number;
  centerX: number;
  centerY: number;
};

type PlateSlot = {
  length: number;
  width: number;
  centerX: number;
  centerY: number;
};

function buildPerforatedPlateGeometry(
  length: number,
  width: number,
  thickness: number,
  holes: PlateHole[],
  slots: PlateSlot[]
) {
  const shape = new THREE.Shape();
  shape.moveTo(-length / 2, -width / 2);
  shape.lineTo(length / 2, -width / 2);
  shape.lineTo(length / 2, width / 2);
  shape.lineTo(-length / 2, width / 2);
  shape.lineTo(-length / 2, -width / 2);

  for (const item of holes) {
    const hole = new THREE.Path();
    hole.absarc(
      item.centerX - length / 2,
      item.centerY - width / 2,
      item.radius,
      0,
      Math.PI * 2,
      true
    );
    shape.holes.push(hole);
  }
  for (const item of slots) {
    const slot = new THREE.Path();
    const radius = item.width / 2;
    const straight = Math.max(item.length - item.width, 0);
    const centerX = item.centerX - length / 2;
    const centerY = item.centerY - width / 2;
    if (straight <= 1e-9) {
      slot.absarc(centerX, centerY, radius, 0, Math.PI * 2, true);
    } else {
      const left = centerX - straight / 2;
      const right = centerX + straight / 2;
      slot.moveTo(left, centerY - radius);
      slot.lineTo(right, centerY - radius);
      slot.absarc(right, centerY, radius, -Math.PI / 2, Math.PI / 2, false);
      slot.lineTo(left, centerY + radius);
      slot.absarc(left, centerY, radius, Math.PI / 2, -Math.PI / 2, false);
    }
    shape.holes.push(slot);
  }

  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: thickness,
    bevelEnabled: false,
    curveSegments: 48
  });
  geometry.center();
  geometry.rotateX(-Math.PI / 2);
  return geometry;
}

function plateHoles(
  dims: Record<string, number | undefined>,
  length: number,
  width: number
): PlateHole[] {
  const count = Math.max(0, Math.round(positive(dims.hole_count, 0)));
  if (count > 0) {
    const holes: PlateHole[] = [];
    for (let index = 1; index <= count; index += 1) {
      const radius = positive(dims[`hole_${index}_radius`], 0);
      const centerX = positive(dims[`hole_${index}_center_x`], NaN);
      const centerY = positive(dims[`hole_${index}_center_y`], NaN);
      if (radius > 0 && Number.isFinite(centerX) && Number.isFinite(centerY)) {
        holes.push({ radius, centerX, centerY });
      }
    }
    if (holes.length === count) {
      return holes;
    }
    return [];
  }

  const radius = positive(dims.hole_radius, 0);
  if (radius <= 0) {
    return [];
  }
  return [
    {
      radius,
      centerX: positive(dims.hole_center_x, length / 2),
      centerY: positive(dims.hole_center_y, width / 2)
    }
  ];
}

function plateSlots(
  dims: Record<string, number | undefined>,
  length: number,
  width: number
): PlateSlot[] {
  const count = Math.max(0, Math.round(positive(dims.slot_count, 0)));
  if (count > 0) {
    const slots: PlateSlot[] = [];
    for (let index = 1; index <= count; index += 1) {
      const slotLength = positive(dims[`slot_${index}_length`], 0);
      const slotWidth = positive(dims[`slot_${index}_width`], 0);
      const centerX = positive(dims[`slot_${index}_center_x`], NaN);
      const centerY = positive(dims[`slot_${index}_center_y`], NaN);
      if (
        slotLength > slotWidth &&
        slotWidth > 0 &&
        Number.isFinite(centerX) &&
        Number.isFinite(centerY)
      ) {
        slots.push({ length: slotLength, width: slotWidth, centerX, centerY });
      }
    }
    if (slots.length === count) {
      return slots;
    }
    return [];
  }

  const slotLength = positive(dims.slot_length, 0);
  const slotWidth = positive(dims.slot_width, 0);
  if (slotLength <= slotWidth || slotWidth <= 0) {
    return [];
  }
  return [
    {
      length: slotLength,
      width: slotWidth,
      centerX: positive(dims.slot_center_x, length / 2),
      centerY: positive(dims.slot_center_y, width / 2)
    }
  ];
}

function buildBeamFieldActor(
  scene: VisualizationScene,
  deformed: boolean,
  field: SceneField
): THREE.Object3D {
  const group = new THREE.Group();
  const orderedNodes = [...scene.nodes].sort((left, right) => left.position[0] - right.position[0]);
  const bounds = viewBounds(scene, "geometry");
  const span = Math.max(
    bounds.max[0] - bounds.min[0],
    bounds.max[1] - bounds.min[1],
    bounds.max[2] - bounds.min[2],
    1
  );
  const section = beamSection(scene, span);
  const originalPoints = orderedNodes.map((node) => vectorFromArray(viewPosition(scene, node.position)));
  const fieldPoints = orderedNodes.map((node) => {
    return vectorFromArray(viewNodePosition(scene, node, deformed));
  });

  if (deformed) {
    group.add(buildSegmentedBeamBody(originalPoints, orderedNodes, field, section, false, true));
  }

  group.add(
    buildSegmentedBeamBody(
      fieldPoints,
      orderedNodes,
      field,
      section,
      deformed,
      false
    )
  );
  if (!deformed) {
    group.add(buildBeamNodeMarkers(fieldPoints, section.nodeSize));
  }

  const firstPoint = originalPoints[0] ?? new THREE.Vector3();
  group.add(buildBeamFixedMarker(firstPoint, section, span));

  return group;
}

type BeamSection = {
  width: number;
  height: number;
  nodeSize: number;
};

function beamSection(scene: VisualizationScene, span: number): BeamSection {
  const width = Math.max(positive(scene.dimensions.width, 0), span * 0.016, 1);
  const height = Math.max(
    positive(scene.dimensions.height, positive(scene.dimensions.thickness, 0)),
    span * 0.016,
    1
  );
  return {
    width,
    height,
    nodeSize: Math.max(Math.min(width, height) * 0.18, 2.8)
  };
}

function buildSegmentedBeamBody(
  points: THREE.Vector3[],
  nodes: SceneNode[],
  field: SceneField,
  section: BeamSection,
  deformed: boolean,
  reference: boolean
): THREE.Object3D {
  const group = new THREE.Group();
  const scalarRange = field.max - field.min || 1;
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    const direction = end.clone().sub(start);
    const length = direction.length();
    if (length <= 1e-9) {
      continue;
    }
    const tangent = direction.normalize();
    const center = start.clone().add(end).multiplyScalar(0.5);
    const startValue = nodes[index] ? nodeFieldValue(nodes[index], field) : field.min;
    const endValue = nodes[index + 1] ? nodeFieldValue(nodes[index + 1], field) : startValue;
    const averageValue = (startValue + endValue) / 2;
    const color = reference
      ? new THREE.Color("#8798aa")
      : deformed
        ? scalarColor(averageValue, field.min, scalarRange)
        : new THREE.Color("#9bc3e8");
    group.add(buildBeamSegmentPrism(center, tangent, length, section, color, deformed, reference));
  }
  return group;
}

function buildBeamSegmentPrism(
  center: THREE.Vector3,
  tangent: THREE.Vector3,
  length: number,
  section: BeamSection,
  color: THREE.Color,
  deformed: boolean,
  reference: boolean
): THREE.Object3D {
  const group = new THREE.Group();
  const quaternion = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(1, 0, 0), tangent);
  const bodyMaterial = deformed
    ? new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.96,
        toneMapped: false,
        depthWrite: false
      })
    : new THREE.MeshStandardMaterial({
      color,
      roughness: 0.38,
      metalness: 0.03,
      transparent: true,
        opacity: reference ? 0.16 : 0.42,
      flatShading: true,
      depthWrite: false
      });
  const body = new THREE.Mesh(new THREE.BoxGeometry(length, section.width, section.height), bodyMaterial);
  body.position.copy(center);
  body.quaternion.copy(quaternion);
  body.renderOrder = reference ? 1 : deformed ? 3 : 2;
  group.add(body);

  if (!deformed || reference) {
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(length, section.width, section.height)),
      new THREE.LineBasicMaterial({
        color: reference ? "#6b7c8f" : "#0f4c81",
        transparent: true,
        opacity: reference ? 0.2 : 0.86,
        depthTest: false,
        depthWrite: false
      })
    );
    edges.position.copy(center);
    edges.quaternion.copy(quaternion);
    edges.renderOrder = reference ? 2 : 7;
    group.add(edges);
  }
  return group;
}

function buildBeamNodeMarkers(
  points: THREE.Vector3[],
  nodeSize: number
): THREE.Object3D {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(points.flatMap((point) => [point.x, point.y, point.z]), 3)
  );
  const nodes = new THREE.Points(
    geometry,
    new THREE.PointsMaterial({
      color: "#0b4d8f",
      size: nodeSize,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.84,
      depthTest: false,
      depthWrite: false
    })
  );
  nodes.renderOrder = 8;
  return nodes;
}

function buildBeamFixedMarker(
  rootPoint: THREE.Vector3,
  section: BeamSection,
  span: number
): THREE.Object3D {
  const group = new THREE.Group();
  const markerThickness = Math.max(span * 0.006, 2.0);
  const marker = new THREE.Mesh(
    new THREE.BoxGeometry(markerThickness, section.width * 1.16, section.height * 1.16),
    new THREE.MeshStandardMaterial({
      color: "#24364d",
      roughness: 0.5,
      metalness: 0.02,
      transparent: true,
      opacity: 0.92
    })
  );
  marker.position.set(rootPoint.x - markerThickness * 0.55, rootPoint.y, rootPoint.z);
  marker.renderOrder = 9;
  group.add(marker);

  const lineGeometry = new THREE.BufferGeometry();
  const y0 = rootPoint.y - section.width * 0.58;
  const z0 = rootPoint.z - section.height * 0.58;
  const positions: number[] = [];
  for (let index = 0; index < 5; index += 1) {
    const y = y0 + (section.width * index) / 4;
    positions.push(
      rootPoint.x - markerThickness * 1.12,
      y,
      z0,
      rootPoint.x - markerThickness * 1.12,
      y + section.width * 0.12,
      z0 - section.height * 0.18
    );
  }
  lineGeometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const hatch = new THREE.LineSegments(
    lineGeometry,
    new THREE.LineBasicMaterial({
      color: "#24364d",
      transparent: true,
      opacity: 0.62,
      depthTest: false,
      depthWrite: false
    })
  );
  hatch.renderOrder = 10;
  group.add(hatch);
  return group;
}

function nodePosition(
  node: VisualizationScene["nodes"][number],
  deformed: boolean,
  deformationScale: number
): [number, number, number] {
  if (!deformed) {
    return node.position;
  }
  return [
    node.position[0] + node.displacement[0] * deformationScale,
    node.position[1] + node.displacement[1] * deformationScale,
    node.position[2] + node.displacement[2] * deformationScale
  ];
}

function viewNodePosition(
  scene: VisualizationScene,
  node: VisualizationScene["nodes"][number],
  deformed: boolean
): [number, number, number] {
  return viewPosition(scene, nodePosition(node, deformed, scene.deformation_scale));
}

function viewPosition(
  scene: VisualizationScene,
  position: [number, number, number]
): [number, number, number] {
  const geometryType = scene.geometry_type.toLowerCase();
  if (geometryType === "plate" || geometryType === "solid") {
    return [position[0], position[2], position[1]];
  }
  return position;
}

function vectorFromArray(point: [number, number, number]) {
  return new THREE.Vector3(point[0], point[1], point[2]);
}

function viewBounds(scene: VisualizationScene, mode: RenderMode) {
  const deformed = mode === "result";
  const points = scene.nodes.map((node) => viewNodePosition(scene, node, deformed));
  if (points.length === 0) {
    const bounds = mode === "result" ? scene.bounds.deformed : scene.bounds.original;
    return {
      min: viewPosition(scene, bounds.min),
      max: viewPosition(scene, bounds.max)
    };
  }
  return {
    min: [
      Math.min(...points.map((point) => point[0])),
      Math.min(...points.map((point) => point[1])),
      Math.min(...points.map((point) => point[2]))
    ] as [number, number, number],
    max: [
      Math.max(...points.map((point) => point[0])),
      Math.max(...points.map((point) => point[1])),
      Math.max(...points.map((point) => point[2]))
    ] as [number, number, number]
  };
}

function elementEdges(nodes: number[]): Array<[number, number]> {
  if (nodes.length === 2) {
    return [[nodes[0], nodes[1]]];
  }
  if (nodes.length === 3) {
    return [
      [nodes[0], nodes[1]],
      [nodes[1], nodes[2]],
      [nodes[2], nodes[0]]
    ];
  }
  if (nodes.length === 4) {
    return [
      [nodes[0], nodes[1]],
      [nodes[1], nodes[2]],
      [nodes[2], nodes[3]],
      [nodes[3], nodes[0]]
    ];
  }
  if (nodes.length >= 8) {
    return [
      [nodes[0], nodes[1]],
      [nodes[1], nodes[2]],
      [nodes[2], nodes[3]],
      [nodes[3], nodes[0]],
      [nodes[4], nodes[5]],
      [nodes[5], nodes[6]],
      [nodes[6], nodes[7]],
      [nodes[7], nodes[4]],
      [nodes[0], nodes[4]],
      [nodes[1], nodes[5]],
      [nodes[2], nodes[6]],
      [nodes[3], nodes[7]]
    ];
  }
  const edges: Array<[number, number]> = [];
  for (let index = 0; index < nodes.length - 1; index += 1) {
    edges.push([nodes[index], nodes[index + 1]]);
  }
  return edges;
}

function elementSurfaceTriangles(nodes: number[]): Array<[number, number, number]> {
  if (nodes.length === 3) {
    return [[nodes[0], nodes[1], nodes[2]]];
  }
  if (nodes.length === 4) {
    return [
      [nodes[0], nodes[1], nodes[2]],
      [nodes[0], nodes[2], nodes[3]]
    ];
  }
  if (nodes.length >= 8) {
    const faces = [
      [nodes[0], nodes[1], nodes[2], nodes[3]],
      [nodes[4], nodes[5], nodes[6], nodes[7]],
      [nodes[0], nodes[1], nodes[5], nodes[4]],
      [nodes[1], nodes[2], nodes[6], nodes[5]],
      [nodes[2], nodes[3], nodes[7], nodes[6]],
      [nodes[3], nodes[0], nodes[4], nodes[7]]
    ];
    return faces.flatMap((face) => [
      [face[0], face[1], face[2]] as [number, number, number],
      [face[0], face[2], face[3]] as [number, number, number]
    ]);
  }
  if (nodes.length > 4) {
    const triangles: Array<[number, number, number]> = [];
    for (let index = 1; index < nodes.length - 1; index += 1) {
      triangles.push([nodes[0], nodes[index], nodes[index + 1]]);
    }
    return triangles;
  }
  return [];
}

function resultFields(scene: VisualizationScene): SceneField[] {
  if (scene.fields && scene.fields.length > 0) {
    return scene.fields;
  }
  return [
    {
      key: "scalar",
      name: scene.scalar.name,
      unit: scene.scalar.unit,
      kind: "result",
      min: scene.scalar.min,
      max: scene.scalar.max
    }
  ];
}

function defaultField(scene: VisualizationScene): SceneField {
  return resultFields(scene)[0];
}

function fieldByKey(scene: VisualizationScene, key: string): SceneField {
  const fields = resultFields(scene);
  return fields.find((field) => field.key === key) ?? fields[0];
}

function nodeFieldValue(
  node: VisualizationScene["nodes"][number],
  field: SceneField
): number {
  const value = node.fields?.[field.key];
  return typeof value === "number" && Number.isFinite(value) ? value : node.scalar;
}

function orientCamera(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  scene: VisualizationScene,
  mode: RenderMode,
  view: ViewPreset
) {
  const directions: Record<ViewPreset, [number, number, number]> = {
    iso: cameraOffset(scene.geometry_type, mode),
    top: [0.0, 1.0, 0.0001],
    front: [0.0, 0.0001, 1.0],
    right: [1.0, 0.0001, 0.0]
  };
  applyCameraFit(camera, controls, scene, mode, normalizeDirection(directions[view]));
}

// 调整相机距离以完整框住模型，保留当前视角方向（用于尺寸变化时重新适配）。
function refitCameraDistance(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  scene: VisualizationScene,
  mode: RenderMode
) {
  const direction = normalizeDirection([
    camera.position.x - controls.target.x,
    camera.position.y - controls.target.y,
    camera.position.z - controls.target.z
  ]);
  applyCameraFit(camera, controls, scene, mode, direction);
}

// 按当前视口宽高比与垂直 FOV 计算包围球完整可见的距离，使模型完整居中。
function applyCameraFit(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  scene: VisualizationScene,
  mode: RenderMode,
  direction: [number, number, number]
) {
  const bounds = viewBounds(scene, mode);
  const center = midpoint(bounds.min, bounds.max);
  const radius = boundingRadius(bounds);
  const distance = fitDistance(camera, radius);
  camera.position.set(
    center[0] + direction[0] * distance,
    center[1] + direction[1] * distance,
    center[2] + direction[2] * distance
  );
  camera.near = Math.max(distance / 200, 0.05);
  camera.far = (distance + radius) * 6;
  camera.updateProjectionMatrix();
  controls.target.set(center[0], center[1], center[2]);
  controls.update();
}

function fitDistance(camera: THREE.PerspectiveCamera, radius: number) {
  const verticalFov = THREE.MathUtils.degToRad(camera.fov);
  const aspect = Math.max(camera.aspect, 1e-4);
  const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * aspect);
  const limitingFov = Math.min(verticalFov, horizontalFov);
  return (radius / Math.sin(limitingFov / 2)) * 1.15;
}

function boundingRadius(bounds: { min: [number, number, number]; max: [number, number, number] }) {
  const dx = bounds.max[0] - bounds.min[0];
  const dy = bounds.max[1] - bounds.min[1];
  const dz = bounds.max[2] - bounds.min[2];
  return Math.max(0.5 * Math.hypot(dx, dy, dz), 0.5);
}

function normalizeDirection(direction: [number, number, number]): [number, number, number] {
  const length = Math.hypot(direction[0], direction[1], direction[2]);
  if (length < 1e-9) {
    const fallback = Math.hypot(1, 0.8, 0.8);
    return [1 / fallback, 0.8 / fallback, 0.8 / fallback];
  }
  return [direction[0] / length, direction[1] / length, direction[2] / length];
}

function sceneSummary(scene: VisualizationScene, mode: RenderMode, field: SceneField) {
  const modeLabel =
    mode === "geometry"
      ? "几何"
      : mode === "mesh"
        ? "网格拓扑"
        : field.kind === "stress"
          ? "应力云图"
          : "位移云图";
  const scalarLabel = `${field.name} ${field.unit ? `(${field.unit})` : ""}`.trim();
  const meshSource = scene.has_real_mesh ? "真实网格" : "示意网格";
  return {
    label: `${modeLabel} · ${scene.geometry_type}`,
    mesh: `${meshSource} · ${scene.mesh.node_count} 节点 / ${scene.mesh.element_count} 单元`,
    result: `${scalarLabel} · ${formatScalar(field.min)} ~ ${formatScalar(field.max)}`,
    scalarLabel
  };
}

function formatScalar(value: number) {
  if (!Number.isFinite(value)) {
    return "N/A";
  }
  return Math.abs(value) >= 1 ? value.toFixed(4) : value.toExponential(3);
}

function formatScale(value: number) {
  if (!Number.isFinite(value)) {
    return "1";
  }
  if (value >= 100) {
    return value.toFixed(0);
  }
  if (value >= 10) {
    return value.toFixed(1);
  }
  return value.toFixed(2);
}

function positive(value: number | null | undefined, fallback: number) {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value;
  }
  return fallback;
}

function midpoint(minPoint: [number, number, number], maxPoint: [number, number, number]) {
  return [
    (minPoint[0] + maxPoint[0]) / 2,
    (minPoint[1] + maxPoint[1]) / 2,
    (minPoint[2] + maxPoint[2]) / 2
  ] as [number, number, number];
}

function cameraOffset(geometryType: string, mode: RenderMode): [number, number, number] {
  const normalized = geometryType.toLowerCase();
  if (normalized === "beam") {
    return mode === "result" ? [1.34, 1.02, 0.7] : [1.0, 0.72, 0.52];
  }
  if (normalized === "plate") {
    return [0.9, 0.9, 1.02];
  }
  return [1.02, 0.78, 0.66];
}

function scalarColor(value: number, min: number, range: number) {
  const clamped = Math.min(Math.max((value - min) / Math.max(range, 1e-9), 0), 1);
  const color = new THREE.Color();
  color.setHSL(0.62 - 0.62 * clamped, 0.85, 0.52);
  return color;
}

function disposeObject(object: THREE.Object3D) {
  const anyObject = object as THREE.Object3D & {
    geometry?: THREE.BufferGeometry;
    material?: THREE.Material | THREE.Material[];
  };
  anyObject.geometry?.dispose();
  const material = anyObject.material;
  if (Array.isArray(material)) {
    material.forEach((item) => disposeMaterial(item));
  } else {
    if (material) {
      disposeMaterial(material);
    }
  }
  for (const child of [...object.children]) {
    disposeObject(child);
  }
}

function disposeMaterial(material: THREE.Material) {
  const texturedMaterial = material as THREE.Material & {
    map?: THREE.Texture | null;
  };
  texturedMaterial.map?.dispose();
  material.dispose();
}
