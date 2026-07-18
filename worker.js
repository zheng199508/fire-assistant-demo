/* Runs the reviewed Python engine off the browser's main UI thread. */

// Keep the Python/WebAssembly runtime in the same static app bundle. This is
// deliberately not a CDN URL: first launch and later offline launches must not
// depend on an external service.
const PYODIDE_INDEX = new URL("./vendor/pyodide/", self.location.href).href;

let runtimePromise;
let evaluateProfileJson;
let buildDocxBase64;

function send(type, payload = {}) {
  self.postMessage({ type, ...payload });
}

async function sha256Hex(bytes) {
  if (!self.crypto?.subtle) return null;
  const digest = await self.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

async function installRuntimeFiles(pyodide) {
  const runtimeRoot = new URL("./runtime/", self.location.href);
  const manifestResponse = await fetch(new URL("runtime-manifest.json", runtimeRoot), { cache: "no-cache" });
  if (!manifestResponse.ok) throw new Error(`无法加载运行清单（${manifestResponse.status}）`);
  const manifest = await manifestResponse.json();
  const total = manifest.files.length;

  for (let index = 0; index < total; index += 1) {
    const item = manifest.files[index];
    const response = await fetch(new URL(item.path, runtimeRoot));
    if (!response.ok) throw new Error(`无法加载专业内核文件：${item.path}`);
    const bytes = await response.arrayBuffer();
    const digest = await sha256Hex(bytes);
    if (digest && digest !== item.sha256) throw new Error(`专业内核文件校验失败：${item.path}`);

    const target = `/app/${item.path}`;
    const directory = target.slice(0, target.lastIndexOf("/"));
    pyodide.FS.mkdirTree(directory);
    pyodide.FS.writeFile(target, new Uint8Array(bytes));
    send("progress", {
      progress: Math.round(24 + ((index + 1) / total) * 68),
      detail: `正在装载规则与计算模块（${index + 1}/${total}）`,
    });
  }
  return manifest;
}

async function initialize() {
  send("progress", { progress: 4, detail: "正在载入浏览器 Python 运行组件" });
  importScripts(`${PYODIDE_INDEX}pyodide.js`);
  send("progress", { progress: 14, detail: "正在启动本地计算环境" });
  const pyodide = await self.loadPyodide({ indexURL: PYODIDE_INDEX });
  send("progress", { progress: 24, detail: "正在校验专业内核" });
  const manifest = await installRuntimeFiles(pyodide);
  pyodide.runPython(`
import os
import sys
os.chdir('/app')
if '/app' not in sys.path:
    sys.path.insert(0, '/app')
`);
  evaluateProfileJson = pyodide.runPython(`
from engine.browser_api import evaluate_profile_json
evaluate_profile_json
`);
  buildDocxBase64 = pyodide.runPython(`
from engine.ooxml_exporter import build_docx_base64
build_docx_base64
`);
  send("ready", {
    progress: 100,
    ruleset: manifest.ruleset,
    releaseReadiness: manifest.release_readiness || {},
    normativeAudit: manifest.normative_audit || {},
  });
  return pyodide;
}

function ensureRuntime() {
  if (!runtimePromise) {
    runtimePromise = initialize().catch((error) => {
      send("fatal", { message: error?.message || String(error) });
      throw error;
    });
  }
  return runtimePromise;
}

self.addEventListener("message", async (event) => {
  const message = event.data || {};
  if (!["evaluate", "export-docx"].includes(message.type)) return;
  try {
    await ensureRuntime();
    if (message.type === "evaluate") {
      send("evaluation-started", { requestId: message.requestId });
      const resultJson = evaluateProfileJson(JSON.stringify(message.profile));
      send("evaluation-result", { requestId: message.requestId, result: JSON.parse(resultJson) });
      return;
    }
    const content = buildDocxBase64(String(message.report || ""));
    send("docx-result", { requestId: message.requestId, content });
  } catch (error) {
    send(message.type === "export-docx" ? "docx-error" : "evaluation-error", {
      requestId: message.requestId,
      message: error?.message || String(error),
      stack: error?.stack || "",
    });
  }
});

ensureRuntime();
