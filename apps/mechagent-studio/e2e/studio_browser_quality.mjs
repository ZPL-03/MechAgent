import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoDir = resolve(appDir, "../..");
const evidenceDir = resolve(repoDir, "dist/studio-browser-evidence");
const previewPort = await freePort();
const previewUrl = `http://127.0.0.1:${previewPort}`;
const checks = [];
const jobs = new Map();
let jobSequence = 0;
let preview;

function assertCondition(condition, message) {
  if (!condition) throw new Error(message);
}

async function record(name, check) {
  await check();
  checks.push({ name, status: "passed" });
}

function jsonResponse(route, body, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json; charset=utf-8",
    body: JSON.stringify(body),
  });
}

function diagnosticPayload() {
  return {
    ok: true,
    config_path: "config/mechagent.yaml",
    checks: [
      {
        key: "python",
        label: "Python",
        ok: true,
        required: true,
        details: { version: "3.13" },
      },
      {
        key: "calculix",
        label: "CalculiX",
        ok: true,
        required: true,
        details: { version: "2.23" },
      },
    ],
    summary: {
      required_passed: 2,
      required_total: 2,
      optional_passed: 0,
      optional_total: 0,
    },
  };
}

function inspectionPayload(request) {
  return {
    success: true,
    ready: true,
    request,
    tasks: [
      {
        task_id: "TASK_01",
        case_id: "TC-BROWSER",
        capability_id: "structural_static",
        title: "矩形薄板 · 浏览器验收",
        analysis_type: "static",
        complete: true,
        missing_fields: [],
        geometry_type: "plate",
        confidence: 0.98,
        source: "deterministic-parser",
      },
    ],
    errors: [],
  };
}

function sceneFor(taskId) {
  return {
    task_id: taskId,
    task_title: "矩形薄板 · 浏览器验收",
    mode: "result",
    geometry_type: "plate",
    dimensions: { length: 100, width: 60, thickness: 4 },
    mesh: {
      element_type: "S4",
      seed_size: 10,
      node_count: 4,
      element_count: 1,
      source: "fixture",
    },
    nodes: [
      { id: 1, position: [0, 0, 0], displacement: [0, 0, 0], scalar: 0 },
      { id: 2, position: [100, 0, 0], displacement: [0, 0, -0.2], scalar: 0.2 },
      { id: 3, position: [100, 60, 0], displacement: [0, 0, -0.3], scalar: 0.3 },
      { id: 4, position: [0, 60, 0], displacement: [0, 0, -0.1], scalar: 0.1 },
    ],
    elements: [{ id: 1, nodes: [1, 2, 3, 4] }],
    scalar: { name: "U", unit: "mm", min: 0, max: 0.3 },
    fields: [{ key: "U", name: "U 位移模量", unit: "mm", kind: "scalar", min: 0, max: 0.3 }],
    loads: [{ type: "pressure", magnitude: 0.01, region: "top", direction: [0, 0, -1] }],
    boundary_conditions: [{ type: "simply_supported", region: "edge", dofs: ["UZ"], values: [0] }],
    deformation_scale: 10,
    bounds: {
      original: { min: [0, 0, 0], max: [100, 60, 0] },
      deformed: { min: [0, 0, -0.3], max: [100, 60, 0] },
    },
    camera: { position: [140, 120, 120], target: [50, 30, 0], up: [0, 0, 1] },
    result: {
      quantity: "center_deflection",
      unit: "mm",
      predicted: 0.3,
      reference: 0.3,
      relative_error: 0,
      tolerance: 0.02,
      passed: true,
      verification_status: "passed",
    },
    has_real_mesh: true,
    has_real_results: true,
  };
}

function resultPayload(kind, request) {
  const taskId = "TASK_01";
  const unverified = kind === "unverified";
  return {
    success: true,
    report: `# 工程报告\n\n请求：${request}\n\n状态：${unverified ? "未验证" : "通过"}`,
    summary: {
      success: true,
      work_dir: "jobs/browser-fixture",
      report_path: "jobs/browser-fixture/report.md",
      tasks: [
        {
          task_id: taskId,
          case_id: "TC-BROWSER",
          capability_id: "structural_static",
          title: "矩形薄板 · 浏览器验收",
          analysis_type: "static",
          model_params: {
            geometry: { type: "plate", dimensions: { length: 100, width: 60, thickness: 4 } },
            material: { name: "steel" },
            loads: [{ type: "pressure", magnitude: 0.01 }],
            bcs: [{ type: "simply_supported" }],
            mesh: { element_type: "S4", seed_size: 10 },
          },
          mesh_result: {
            success: true,
            mesh_file: "jobs/browser-fixture/plate_mesh.inp",
            element_count: 1,
            node_count: 4,
            quality: { min_sicn: 0.91 },
            metadata: { quality_gate: { status: "passed" } },
          },
          solver_result: {
            success: true,
            model_case_id: "TC-BROWSER",
            quantity: "center_deflection",
            unit: "mm",
            predicted: 0.3,
            reference: unverified ? null : 0.3,
            relative_error: unverified ? null : 0,
            tolerance: unverified ? null : 0.02,
            passed: unverified ? false : true,
            verification_status: unverified ? "unverified" : "passed",
            solver: "CalculiX",
            mesh_file: "jobs/browser-fixture/plate_mesh.inp",
            output_files: ["jobs/browser-fixture/plate.frd"],
            equilibrium: { status: "unverified", reason: "fixture" },
          },
          post_summary: { field_count: 1 },
        },
      ],
      errors: [],
    },
    visualizations: [
      {
        task_id: taskId,
        title: "矩形薄板 · 浏览器验收",
        kind: "scene",
        svg: '<svg viewBox="0 0 240 140" role="img" aria-label="fixture plate"><rect x="20" y="20" width="200" height="100" fill="#245fc0" fill-opacity="0.25" stroke="#82aaf0" stroke-width="2" /></svg>',
        caption: "位移云图",
        scene: sceneFor(taskId),
      },
    ],
    metadata: { duration_ms: 120 },
  };
}

function jobPayload(id, request, kind) {
  const failed = kind === "failed";
  return {
    job_id: id,
    status: failed ? "failed" : "succeeded",
    request,
    use_llm_agents: false,
    created_at: "2026-11-14T00:00:00+00:00",
    started_at: "2026-11-14T00:00:00+00:00",
    finished_at: "2026-11-14T00:00:01+00:00",
    duration_ms: 120,
    result: failed ? null : resultPayload(kind, request),
    error: failed ? "求解器返回失败：fixture" : null,
    error_code: failed ? "solver_failed" : null,
    worker_exit_code: failed ? 1 : 0,
    events: [
      { stage: "planner", status: "complete", message: "任务识别", timestamp: "2026-11-14T00:00:00+00:00" },
      { stage: "solver", status: failed ? "failed" : "complete", message: failed ? "求解执行失败" : "求解执行", timestamp: "2026-11-14T00:00:01+00:00" },
    ],
  };
}

async function installApiRoutes(page) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path.endsWith("/health")) {
      return jsonResponse(route, {
        ok: true,
        product: "MechAgent Studio",
        config: "config/mechagent.yaml",
        python_executable: "python",
        static_ready: true,
      });
    }
    if (path.endsWith("/diagnostics")) return jsonResponse(route, diagnosticPayload());
    if (path.endsWith("/capabilities")) {
      return jsonResponse(route, {
        capabilities: [{
          capability_id: "structural_static",
          task_case_id: "TC-BROWSER",
          title: "结构线弹性静力",
          analysis_type: "static",
          physics_domain: "structural",
          solver_name: "CalculiX",
          mesher_name: "Gmsh",
          model_case_ids: ["TC-BROWSER"],
          example_requests: ["矩形薄板静力分析"],
          planner_description: "fixture",
        }],
      });
    }
    if (path.endsWith("/examples")) {
      return jsonResponse(route, {
        examples: [{
          example_id: "browser-fixture",
          case_id: "TC-BROWSER",
          title: "矩形板 · 均布压力",
          request: "长100mm、宽60mm、厚4mm钢板，四边简支，承受0.01MPa向下均布压力的静力响应",
          capability_id: "structural_static",
          geometry_type: "plate",
          load_type: "pressure",
          model_case_id: "TC-BROWSER",
          tags: ["plate"],
        }],
      });
    }
    if (path.endsWith("/inspect") && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}");
      return jsonResponse(route, inspectionPayload(String(body.request ?? "")));
    }
    if (path.endsWith("/jobs") && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}");
      const text = String(body.request ?? "");
      const kind = text.includes("失败") ? "failed" : text.includes("未验证") ? "unverified" : "passed";
      const id = `browser-${String(++jobSequence).padStart(3, "0")}`;
      const job = jobPayload(id, text, kind);
      jobs.set(id, job);
      return jsonResponse(route, job, 202);
    }
    if (path.endsWith("/jobs") && request.method() === "GET") {
      return jsonResponse(route, {
        jobs: [...jobs.values()],
        pagination: { limit: 10, next_cursor: null, has_more: false },
      });
    }
    const jobMatch = path.match(/\/jobs\/([^/]+)(?:\/(cancel|retry|evidence))?$/);
    if (jobMatch) {
      const job = jobs.get(jobMatch[1]);
      if (!job) return jsonResponse(route, { code: "not_found", detail: "作业不存在。" }, 404);
      const action = jobMatch[2];
      if (action === "evidence") return jsonResponse(route, { valid: true, errors: [] });
      if (action === "retry") {
        const retryId = `browser-${String(++jobSequence).padStart(3, "0")}`;
        const retry = jobPayload(retryId, job.request, "passed");
        jobs.set(retryId, retry);
        return jsonResponse(route, retry, 202);
      }
      return jsonResponse(route, job);
    }
    return route.continue();
  });
}

async function waitForServer(url) {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The preview process may still be binding its port.
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100));
  }
  throw new Error(`Studio preview 未在限定时间内启动：${url}`);
}

function startPreview() {
  const viteCli = resolve(appDir, "node_modules/vite/bin/vite.js");
  preview = spawn(process.execPath, [viteCli, "preview", "--host", "127.0.0.1", "--port", String(previewPort)], {
    cwd: appDir,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  preview.stdout.on("data", (chunk) => process.stdout.write(chunk));
  preview.stderr.on("data", (chunk) => process.stderr.write(chunk));
  preview.on("exit", (code) => {
    if (code && !process.exitCode) process.exitCode = code;
  });
}

async function freePort() {
  const server = createServer();
  await new Promise((resolvePromise, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolvePromise);
  });
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  await new Promise((resolvePromise) => server.close(resolvePromise));
  return port;
}

async function main() {
  await rm(evidenceDir, { recursive: true, force: true });
  await mkdir(evidenceDir, { recursive: true });
  startPreview();
  await waitForServer(previewUrl);

  const browser = await chromium.launch(browserLaunchOptions());
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    colorScheme: "light",
  });
  await context.addInitScript(() => localStorage.clear());
  const page = await context.newPage();
  await installApiRoutes(page);

  try {
    await page.goto(previewUrl, { waitUntil: "networkidle" });
    await page.locator('textarea[name="simulation-request"]').waitFor();

    await record("initial-language-and-skip-link", async () => {
      assertCondition(await page.locator("html").getAttribute("lang") === "zh-CN", "初始语言不是 zh-CN。");
      await page.keyboard.press("Tab");
      assertCondition(await page.locator(".skip-link").evaluate((node) => node === document.activeElement), "首个焦点未落在跳转链接。");
    });

    await record("language-switch", async () => {
      await page.getByRole("button", { name: "切换为英文" }).click();
      assertCondition(await page.locator("html").getAttribute("lang") === "en", "英文切换未更新 html lang。");
      assertCondition(await page.getByLabel("Engineering request in natural language").count() === 1, "英文文案未更新请求输入标签。");
      await page.getByRole("button", { name: "Switch to Chinese" }).click();
    });

    await record("theme-cycle", async () => {
      const theme = page.getByRole("button", { name: /主题：/ });
      await page.waitForFunction(() => Boolean(document.documentElement.dataset.themePreference));
      const initial = await page.locator("html").getAttribute("data-theme-preference");
      await theme.click();
      const second = await page.locator("html").getAttribute("data-theme-preference");
      await theme.click();
      const third = await page.locator("html").getAttribute("data-theme-preference");
      assertCondition(initial === "dark" && second === "system" && third === "light", `主题循环顺序不符合 light/dark/system 契约：${initial} -> ${second} -> ${third}`);
      await theme.click();
    });

    const readyRequest = "长100mm、宽60mm、厚4mm钢板，四边简支，承受0.01MPa向下均布压力的静力响应";
    await page.getByLabel("自然语言仿真请求").fill(readyRequest);
    await page.getByText("可执行", { exact: true }).waitFor();

    await record("desktop-layout", async () => {
      const dimensions = await page.evaluate(() => ({
        viewport: window.innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }));
      assertCondition(dimensions.scrollWidth <= dimensions.viewport + 1, `桌面布局出现横向溢出：${JSON.stringify(dimensions)}`);
    });

    await record("passed-result-and-report", async () => {
      await page.getByRole("button", { name: "运行仿真" }).click();
      await page.getByText("结果满足验收", { exact: true }).waitFor();
      await page.locator("canvas.three-canvas").waitFor({ state: "visible" });
      assertCondition((await page.locator(".markdown-body").innerText()).includes("工程报告"), "通过结果缺少工程报告。");
      await page.screenshot({ path: resolve(evidenceDir, "desktop-passed-state.png"), fullPage: true });
    });

    await record("unverified-result", async () => {
      await page.getByLabel("自然语言仿真请求").fill(`${readyRequest} 未验证`);
      await page.getByText("可执行", { exact: true }).waitFor();
      await page.getByRole("button", { name: "运行仿真" }).click();
      await page.getByText("求解完成，未参考验收", { exact: true }).waitFor();
    });

    await record("failed-result", async () => {
      await page.getByLabel("自然语言仿真请求").fill(`${readyRequest} 失败`);
      await page.getByText("可执行", { exact: true }).waitFor();
      await page.getByRole("button", { name: "运行仿真" }).click();
      await page.getByText("结果未通过", { exact: true }).waitFor();
      await page.getByText("等待结果场", { exact: true }).waitFor();
      assertCondition((await page.locator(".verdict-card").innerText()).includes("求解器返回失败"), "失败结果未保留服务端诊断。");
    });

    await record("mobile-layout", async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      const dimensions = await page.evaluate(() => ({
        viewport: window.innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        grid: getComputedStyle(document.querySelector(".studio-layout")).gridTemplateColumns,
      }));
      assertCondition(dimensions.scrollWidth <= dimensions.viewport + 1, `窄屏布局出现横向溢出：${JSON.stringify(dimensions)}`);
      assertCondition(dimensions.grid.trim().split(/\s+/).length === 1, `窄屏未切换为单列布局：${dimensions.grid}`);
      await page.screenshot({ path: resolve(evidenceDir, "mobile-failed-state.png"), fullPage: true });
    });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({ path: resolve(evidenceDir, "desktop-failed-state.png"), fullPage: true });
  } finally {
    await browser.close();
  }

  await writeFile(
    resolve(evidenceDir, "manifest.json"),
    JSON.stringify({
      schema: "mechagent.studio-browser-evidence.v1",
      status: "passed",
      base_url: previewUrl,
      viewport_checks: ["1440x1000", "390x844"],
      api_mode: "deterministic-contract-fixture",
      solver_validation: "covered by independent Python and real-solver gates",
      checks,
    }, null, 2) + "\n",
    "utf8",
  );
}

function browserLaunchOptions() {
  const options = { headless: true };
  if (process.platform === "win32" && !process.env.CI) {
    const candidates = [
      process.env.MECHAGENT_BROWSER_PATH,
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    ].filter(Boolean);
    const executablePath = candidates.find((candidate) => existsSync(candidate));
    if (executablePath) options.executablePath = executablePath;
  }
  return options;
}

try {
  await main();
  console.log(`Studio browser quality gate passed: ${checks.length} checks.`);
} catch (error) {
  const message = error instanceof Error ? error.stack ?? error.message : String(error);
  await writeFile(
    resolve(evidenceDir, "manifest.json"),
    JSON.stringify({ schema: "mechagent.studio-browser-evidence.v1", status: "failed", error: message, checks }, null, 2) + "\n",
    "utf8",
  ).catch(() => undefined);
  console.error(message);
  process.exitCode = 1;
} finally {
  if (preview && !preview.killed) preview.kill();
}
