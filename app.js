const STORAGE_KEY = "fire-assistant.profile.v1";
const BOOLEAN_FIELDS = [
  "is_important_public_building",
  "is_elderly_facility",
  "is_inpatient",
  "is_kindergarten",
  "has_basement",
  "has_garage",
  "has_large_atrium",
  "has_equipment_room",
  "has_fire_control_room",
  "has_fire_pump_room",
  "dual_municipal_water",
  "municipal_outdoor_flow_ok",
  "power_dual_supply",
  "has_central_ac",
];
const NUMBER_FIELDS = [
  "height_m",
  "floors_above",
  "floor_area_sqm",
  "total_area_sqm",
  "clear_height_m",
  "max_occupants",
  "corridor_length_m",
  "max_single_floor_area",
  "floors_below",
  "environment_temp",
  "garage_parking_spots",
  "garage_total_area",
  "water_tank_volume",
];

const form = document.querySelector("#assessmentForm");
const pages = [...document.querySelectorAll("[data-step-page]")];
const railItems = [...document.querySelectorAll("#stepRail [data-step]")];
const previousButton = document.querySelector("#previousButton");
const nextButton = document.querySelector("#nextButton");
const evaluateButton = document.querySelector("#evaluateButton");
const confirmation = document.querySelector("#accuracyConfirmation");
const results = document.querySelector("#results");
const toast = document.querySelector("#toast");

let currentStep = 0;
let engineReady = false;
let currentRuleset = "";
let rulesetReleaseReady = false;
let rulesetNormativeAffected = 0;
let lastResult = null;
let deferredInstallPrompt = null;
let pendingEvaluation = null;
let pendingDocxExport = null;
let requestSequence = 0;
let saveTimer = null;

function field(name) {
  return form.elements.namedItem(name);
}

function radioValue(name) {
  return form.querySelector(`[name="${name}"]:checked`)?.value || "";
}

function setField(name, value) {
  const controls = [...form.querySelectorAll(`[name="${name}"]`)];
  if (!controls.length) return;
  if (controls[0].type === "radio") {
    controls.forEach((control) => { control.checked = control.value === String(value); });
  } else if (controls[0].type === "checkbox") {
    controls[0].checked = Boolean(value);
  } else {
    controls[0].value = value ?? "";
  }
}

function updateConditionalSections() {
  const buildingType = radioValue("building_type") || "civil";
  const civilSubtype = field("civil_subtype")?.value || "public";
  document.querySelector('[data-section="civil"]').hidden = buildingType !== "civil";
  document.querySelector('[data-section="industrial"]').hidden = buildingType !== "industrial";
  document.querySelector('[data-section="public"]').hidden = !(buildingType === "civil" && civilSubtype === "public");
  document.querySelector('[data-section="public-special"]').hidden = !(buildingType === "civil" && civilSubtype === "public");

  const garage = Boolean(field("has_garage")?.checked);
  if (garage) field("has_basement").checked = true;
  document.querySelector("#basementFields").hidden = !field("has_basement")?.checked;
  document.querySelector("#garageFields").hidden = !garage;
}

function validateCurrentStep() {
  const page = pages[currentStep];
  const controls = [...page.querySelectorAll("input[required], select[required]")]
    .filter((control) => !control.closest("[hidden]") && control.offsetParent !== null);
  for (const control of controls) {
    if (!control.checkValidity()) {
      control.reportValidity();
      control.focus();
      return false;
    }
  }
  return true;
}

function showStep(index) {
  currentStep = Math.max(0, Math.min(pages.length - 1, index));
  pages.forEach((page, pageIndex) => {
    const active = pageIndex === currentStep;
    page.hidden = !active;
    page.classList.toggle("active", active);
  });
  railItems.forEach((item, itemIndex) => {
    item.classList.toggle("active", itemIndex === currentStep);
    item.classList.toggle("complete", itemIndex < currentStep);
  });
  previousButton.hidden = currentStep === 0;
  nextButton.hidden = currentStep === pages.length - 1;
  evaluateButton.hidden = currentStep !== pages.length - 1;
  if (currentStep === pages.length - 1) renderReview();
  updateEvaluateAvailability();
  document.querySelector(".main-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function collectProfile() {
  const profile = {};
  const data = new FormData(form);
  for (const [key, value] of data.entries()) profile[key] = value;
  for (const key of BOOLEAN_FIELDS) profile[key] = Boolean(field(key)?.checked);
  for (const key of NUMBER_FIELDS) {
    const value = Number(field(key)?.value || 0);
    profile[key] = Number.isFinite(value) ? value : 0;
  }

  profile.building_type = radioValue("building_type") || "civil";
  profile.civil_subtype = field("civil_subtype")?.value || "public";
  profile.industrial_subtype = field("industrial_subtype")?.value || "workshop";
  profile.public_building_type = field("public_building_type")?.value || "";
  profile.fire_risk = field("fire_risk")?.value || "";
  profile.fire_resistance = field("fire_resistance")?.value || "";
  profile.sprinkler_coverage = field("sprinkler_coverage")?.value || "不设置";
  profile.has_sprinkler_design = ["局部设置", "全部设置"].includes(profile.sprinkler_coverage);

  const publicBuilding = profile.building_type === "civil" && profile.civil_subtype === "public";
  profile.is_medical = publicBuilding && profile.public_building_type === "医疗建筑";
  profile.is_education = publicBuilding && profile.public_building_type === "教育建筑";
  profile.is_shop_exhibition = publicBuilding && profile.public_building_type === "商业建筑";
  profile.is_kindergarten = profile.is_education && profile.is_kindergarten;
  profile.is_inpatient = profile.is_medical && profile.is_inpatient;
  if (profile.building_type !== "civil") {
    profile.civil_subtype = "";
    profile.public_building_type = "";
    profile.is_medical = false;
    profile.is_education = false;
    profile.is_shop_exhibition = false;
    profile.is_kindergarten = false;
    profile.is_inpatient = false;
    profile.is_elderly_facility = false;
    profile.is_important_public_building = false;
  } else {
    profile.industrial_subtype = "";
    profile.fire_risk = "";
    profile.substances = "";
  }

  profile.has_basement = profile.has_basement || profile.has_garage;
  if (!profile.total_area_sqm && profile.floor_area_sqm && profile.floors_above) {
    profile.total_area_sqm = profile.floor_area_sqm * profile.floors_above;
  }
  profile.building_volume = profile.total_area_sqm * (profile.clear_height_m || 3);
  return profile;
}

function saveProfile() {
  const payload = { schema: 1, savedAt: new Date().toISOString(), profile: collectProfile() };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  const state = document.querySelector("#autosaveState");
  state.textContent = "已在本机保存";
}

function scheduleSave() {
  const state = document.querySelector("#autosaveState");
  state.textContent = "正在保存…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveProfile, 250);
}

function restoreSavedProfile() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (!saved?.profile) return;
    for (const [key, value] of Object.entries(saved.profile)) setField(key, value);
  } catch (error) {
    console.warn("Saved profile could not be restored", error);
  }
}

function applyDemo(name) {
  const base = {
    fire_resistance: "一级",
    total_area_sqm: 0,
    max_occupants: 300,
    corridor_length_m: 24,
    sprinkler_coverage: "全部设置",
  };
  const demos = {
    residential: {
      ...base, building_type: "civil", civil_subtype: "residential", height_m: 60,
      floors_above: 20, floor_area_sqm: 800, clear_height_m: 2.9,
      has_basement: true, has_garage: true, floors_below: 1,
      garage_parking_spots: 200, garage_total_area: 5000,
    },
    hospital: {
      ...base, building_type: "civil", civil_subtype: "public", public_building_type: "医疗建筑",
      is_inpatient: true, height_m: 36, floors_above: 10, floor_area_sqm: 1800,
      clear_height_m: 3.5, max_occupants: 900, has_basement: true, floors_below: 1,
    },
    workshop: {
      ...base, building_type: "industrial", industrial_subtype: "workshop", fire_risk: "丙",
      substances: "木材", height_m: 15, floors_above: 3, floor_area_sqm: 3000,
      clear_height_m: 5, max_occupants: 120, has_basement: false, has_garage: false,
    },
  };
  const profile = demos[name];
  if (!profile) return;
  for (const [key, value] of Object.entries(profile)) setField(key, value);
  updateConditionalSections();
  scheduleSave();
  showToast("已载入演示画像，可继续修改");
}

function valueLabel(value, suffix = "") {
  if (value === true) return "是";
  if (value === false || value === "" || value == null) return "否 / 未设置";
  return `${value}${suffix}`;
}

function renderReview() {
  const profile = collectProfile();
  const type = profile.building_type === "civil"
    ? `${profile.civil_subtype === "residential" ? "住宅建筑" : profile.public_building_type}`
    : `${profile.fire_risk}类${profile.industrial_subtype === "workshop" ? "厂房" : "仓库"}`;
  const items = [
    ["建筑类型", type],
    ["高度与层数", `${profile.height_m}m · 地上${profile.floors_above}层${profile.has_basement ? ` · 地下${profile.floors_below}层` : ""}`],
    ["建筑规模", `典型层${profile.floor_area_sqm}㎡ · 总面积${profile.total_area_sqm}㎡`],
    ["耐火等级", profile.fire_resistance || "由系统按画像建议"],
    ["地下汽车库", profile.has_garage ? `${profile.garage_parking_spots}辆 · ${profile.garage_total_area}㎡` : "无"],
    ["自动喷水", profile.sprinkler_coverage],
    ["市政供水", profile.dual_municipal_water ? "两路可靠供水" : "非两路可靠供水"],
    ["消防水池", profile.water_pool_type || "尚未确定"],
    ["特殊构造", [profile.has_large_atrium && "中庭", profile.has_equipment_room && "重要设备用房", profile.has_fire_control_room && "消防控制室"].filter(Boolean).join("、") || "未选择"],
  ];
  const grid = document.querySelector("#reviewGrid");
  grid.replaceChildren(...items.map(([label, value]) => {
    const card = document.createElement("div");
    card.className = "review-item";
    const caption = document.createElement("span");
    caption.textContent = label;
    const content = document.createElement("strong");
    content.textContent = value;
    card.append(caption, content);
    return card;
  }));
}

function setEngineStatus(state, title, detail, progress = "") {
  const banner = document.querySelector("#engineBanner");
  banner.classList.remove("loading", "error");
  if (state !== "ready") banner.classList.add(state);
  document.querySelector("#engineTitle").textContent = title;
  document.querySelector("#engineDetail").textContent = detail;
  document.querySelector("#engineProgress").textContent = progress;
}

function updateEvaluateAvailability() {
  evaluateButton.disabled = !engineReady || !confirmation.checked;
}

function createEngineWorker() {
  if (!("Worker" in window)) {
    setEngineStatus("error", "当前浏览器不支持本地专业内核", "请使用新版 Chrome、Edge 或 Safari", "错误");
    return;
  }
  const worker = new Worker("./worker.js");
  worker.addEventListener("message", (event) => {
    const message = event.data || {};
    if (message.type === "progress") {
      setEngineStatus("loading", "正在准备专业内核", message.detail, `${message.progress || 0}%`);
    } else if (message.type === "ready") {
      engineReady = true;
      currentRuleset = message.ruleset || "";
      rulesetReleaseReady = Boolean(message.releaseReadiness?.public_release_ready);
      rulesetNormativeAffected = Number(message.normativeAudit?.affected_rules || 0);
      const reviewLabel = rulesetReleaseReady ? "已发布" : "专业审核中";
      const auditLabel = rulesetNormativeAffected
        ? ` · ${rulesetNormativeAffected} 条规则待按通用规范复核`
        : "";
      setEngineStatus("ready", `专业内核已就绪 · ${reviewLabel}`, `规则包 ${currentRuleset}${auditLabel} · 全部计算在当前设备完成`, "可用");
      updateEvaluateAvailability();
    } else if (message.type === "fatal") {
      engineReady = false;
      setEngineStatus("error", "专业内核加载失败", message.message || "请检查网络后刷新", "不可用");
      updateEvaluateAvailability();
    } else if (message.type === "evaluation-result" && pendingEvaluation?.requestId === message.requestId) {
      pendingEvaluation.resolve(message.result);
      pendingEvaluation = null;
    } else if (message.type === "evaluation-error" && pendingEvaluation?.requestId === message.requestId) {
      pendingEvaluation.reject(new Error(message.message || "评估失败"));
      pendingEvaluation = null;
    } else if (message.type === "docx-result" && pendingDocxExport?.requestId === message.requestId) {
      pendingDocxExport.resolve(message.content);
      pendingDocxExport = null;
    } else if (message.type === "docx-error" && pendingDocxExport?.requestId === message.requestId) {
      pendingDocxExport.reject(new Error(message.message || "Word 报告生成失败"));
      pendingDocxExport = null;
    }
  });
  worker.addEventListener("error", (event) => {
    setEngineStatus("error", "专业内核异常", event.message || "请刷新后重试", "错误");
  });
  return worker;
}

const engineWorker = createEngineWorker();

function evaluateProfile(profile) {
  if (!engineReady || !engineWorker) return Promise.reject(new Error("专业内核尚未就绪"));
  if (pendingEvaluation) return Promise.reject(new Error("已有评估正在进行"));
  const requestId = `evaluation-${Date.now()}-${++requestSequence}`;
  return new Promise((resolve, reject) => {
    pendingEvaluation = { requestId, resolve, reject };
    engineWorker.postMessage({ type: "evaluate", requestId, profile });
  });
}

function exportDocx(report) {
  if (!engineReady || !engineWorker) return Promise.reject(new Error("专业内核尚未就绪"));
  if (pendingDocxExport) return Promise.reject(new Error("已有 Word 报告正在生成"));
  const requestId = `docx-${Date.now()}-${++requestSequence}`;
  return new Promise((resolve, reject) => {
    pendingDocxExport = { requestId, resolve, reject };
    engineWorker.postMessage({ type: "export-docx", requestId, report });
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function formatInline(value) {
  return escapeHtml(value)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function tableCells(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replace(/\r/g, "").split("\n");
  const html = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (line.trim().startsWith("|") && lines[index + 1]?.match(/^\s*\|?[\s:|-]+\|/)) {
      const headers = tableCells(line);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) rows.push(tableCells(lines[index++]));
      html.push(`<table><thead><tr>${headers.map((cell) => `<th>${formatInline(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${formatInline(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      html.push(`<h${level}>${formatInline(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }
    if (line.startsWith(">")) {
      const quote = [];
      while (index < lines.length && lines[index].startsWith(">")) quote.push(lines[index++].replace(/^>\s?/, ""));
      html.push(`<blockquote>${quote.map(formatInline).join("<br>")}</blockquote>`);
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index])) items.push(lines[index++].replace(/^[-*]\s+/, ""));
      html.push(`<ul>${items.map((item) => `<li>${formatInline(item)}</li>`).join("")}</ul>`);
      continue;
    }
    if (!line.trim()) {
      index += 1;
      continue;
    }
    html.push(`<p>${formatInline(line)}</p>`);
    index += 1;
  }
  return html.join("\n");
}

function scopeLabel(scope) {
  const labels = {
    fire_hydrant: "消火栓", sprinkler: "自动喷水", fire_alarm: "火灾报警",
    smoke_control: "防排烟", extinguisher: "灭火器", lighting: "应急照明",
    power: "消防电源", garage: "汽车库", "civil.public": "公共建筑",
    "civil.residential": "住宅建筑", "industrial.workshop": "厂房",
    "industrial.warehouse": "仓库",
  };
  return labels[scope] || "其他";
}

function renderResults(result) {
  lastResult = result;
  form.hidden = true;
  results.hidden = false;
  const profile = result.profile || {};
  const calculation = result.calculation || {};
  const conclusions = result.conclusions || [];
  document.querySelector("#resultTitle").textContent = rulesetReleaseReady
    ? "消防设施配置建议"
    : "消防设施配置建议（审核版）";
  document.querySelector("#resultMeta").textContent = `${profile.building_class || "未分类"} · ${profile.fire_resistance || "耐火等级未定"} · 规则包 ${result.ruleset || currentRuleset}`;
  document.querySelector("#waterMetric").textContent = Number(calculation.total_water_m3 || 0).toFixed(0);
  document.querySelector("#tankMetric").textContent = Number(calculation.water_tank_m3 || 0).toFixed(0);
  document.querySelector("#compartmentMetric").textContent = Number(calculation.compartment_limit_with_sprinkler || calculation.compartment_limit || 0).toFixed(0);
  const core = conclusions.filter((item) => item.priority >= 85 && ["required", "prohibited"].includes(item.conclusion_type));
  document.querySelector("#conclusionMetric").textContent = String(core.length);

  const risks = [];
  if (!rulesetReleaseReady) {
    const countLabel = rulesetNormativeAffected ? `${rulesetNormativeAffected} 条规则` : "部分规则";
    risks.push(`规则包仍在专业审核：${countLabel}需按现行通用规范复核，当前输出不可直接作为正式设计依据`);
  }
  if (String(profile.building_class || "").includes("违规")) risks.push(profile.building_class);
  if (calculation.compartment_is_exceeded) risks.push(`防火分区超限：实际 ${calculation.compartment_actual_area || 0}㎡，限值 ${calculation.compartment_limit_with_sprinkler || 0}㎡`);
  const riskBanner = document.querySelector("#riskBanner");
  riskBanner.hidden = risks.length === 0;
  riskBanner.textContent = risks.join("；");

  document.querySelector("#conclusionCards").innerHTML = core.slice(0, 12).map((item) => `
    <article class="conclusion-card ${item.conclusion_type === "prohibited" ? "prohibited" : ""}">
      <span class="mark">${item.conclusion_type === "prohibited" ? "!" : "✓"}</span>
      <div><strong>${escapeHtml(item.conclusion)}</strong><small>${escapeHtml(item.citation || "条文待补充")}</small></div>
      <small>${escapeHtml(scopeLabel(item.scope))}</small>
    </article>
  `).join("");
  document.querySelector("#reportContent").innerHTML = markdownToHtml(result.report);
  results.scrollIntoView({ behavior: "smooth", block: "start" });
  saveProfile();
}

function downloadBlob(content, type, filename) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function base64ToBytes(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function dateStamp() {
  const date = new Date();
  return `${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, "0")}${String(date.getDate()).padStart(2, "0")}`;
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 3000);
}

form.addEventListener("input", () => {
  updateConditionalSections();
  if (currentStep === pages.length - 1) renderReview();
  scheduleSave();
});
form.addEventListener("change", () => {
  updateConditionalSections();
  scheduleSave();
});
previousButton.addEventListener("click", () => showStep(currentStep - 1));
nextButton.addEventListener("click", () => {
  if (validateCurrentStep()) showStep(currentStep + 1);
});
confirmation.addEventListener("change", updateEvaluateAvailability);
document.querySelectorAll("[data-demo]").forEach((button) => button.addEventListener("click", () => applyDemo(button.dataset.demo)));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!validateCurrentStep() || !confirmation.checked) return;
  evaluateButton.disabled = true;
  evaluateButton.textContent = "正在评估…";
  try {
    const result = await evaluateProfile(collectProfile());
    renderResults(result);
  } catch (error) {
    console.error(error);
    showToast(`评估失败：${error.message}`);
  } finally {
    evaluateButton.textContent = "生成专业报告";
    updateEvaluateAvailability();
  }
});

document.querySelector("#editProfileButton").addEventListener("click", () => {
  results.hidden = true;
  form.hidden = false;
  showStep(4);
});
document.querySelector("#downloadWord").addEventListener("click", async (event) => {
  if (!lastResult) return;
  const button = event.currentTarget;
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "正在生成…";
  try {
    const content = await exportDocx(lastResult.report);
    downloadBlob(
      base64ToBytes(content),
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      `消防方案报告_${dateStamp()}.docx`,
    );
    showToast("Word 报告已生成");
  } catch (error) {
    console.error(error);
    showToast(`Word 报告生成失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
});
document.querySelector("#downloadMarkdown").addEventListener("click", () => {
  if (lastResult) downloadBlob(lastResult.report, "text/markdown;charset=utf-8", `消防方案报告_${dateStamp()}.md`);
});
document.querySelector("#downloadJson").addEventListener("click", () => {
  const payload = { schema: 1, exportedAt: new Date().toISOString(), profile: collectProfile(), result: lastResult };
  downloadBlob(JSON.stringify(payload, null, 2), "application/json;charset=utf-8", `消防项目_${dateStamp()}.json`);
});
document.querySelector("#printReport").addEventListener("click", () => window.print());
const importProjectButton = document.querySelector("#importProjectButton");
const importProjectInput = document.querySelector("#importProjectInput");
importProjectButton.addEventListener("click", () => importProjectInput.click());
importProjectInput.addEventListener("change", async () => {
  const [file] = importProjectInput.files;
  importProjectInput.value = "";
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) {
    showToast("导入失败：文件超过 20MB");
    return;
  }
  try {
    const payload = JSON.parse(await file.text());
    const profile = payload?.profile;
    if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
      throw new Error("文件中没有有效的建筑画像");
    }
    for (const [key, value] of Object.entries(profile)) setField(key, value);
    lastResult = null;
    results.hidden = true;
    form.hidden = false;
    updateConditionalSections();
    saveProfile();
    showStep(0);
    showToast(`已导入：${file.name}`);
  } catch (error) {
    console.error(error);
    showToast(`导入失败：${error.message || "文件格式不正确"}`);
  }
});
document.querySelector("#newProjectButton").addEventListener("click", () => {
  if (window.confirm("新建项目会清除当前设备上保存的建筑画像，是否继续？")) {
    localStorage.removeItem(STORAGE_KEY);
    window.location.reload();
  }
});

function updateNetworkStatus() {
  const status = document.querySelector("#networkStatus");
  status.textContent = navigator.onLine ? "在线" : "离线模式";
  status.classList.toggle("offline", !navigator.onLine);
}
window.addEventListener("online", updateNetworkStatus);
window.addEventListener("offline", updateNetworkStatus);

const installButton = document.querySelector("#installButton");
const installHelp = document.querySelector("#installHelp");
function openInstallHelp() {
  if (typeof installHelp.showModal === "function") {
    installHelp.showModal();
  } else {
    window.alert("请打开浏览器菜单，选择“添加到桌面 / 添加到主屏幕”。vivo 浏览器也可先收藏本页，再在收藏列表长按并选择“添加至桌面”。");
  }
}
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  installButton.hidden = false;
  installButton.textContent = "安装应用";
});
installButton.addEventListener("click", async () => {
  if (deferredInstallPrompt) {
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    installButton.hidden = true;
  } else {
    openInstallHelp();
  }
});
document.querySelector("#closeInstallHelp").addEventListener("click", () => installHelp.close());
document.querySelector("#confirmInstallHelp").addEventListener("click", () => installHelp.close());
installHelp.addEventListener("click", (event) => {
  if (event.target === installHelp) installHelp.close();
});
window.addEventListener("appinstalled", () => { installButton.hidden = true; });
if (window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone) {
  installButton.hidden = true;
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js").catch((error) => console.warn("Service worker registration failed", error)));
}

restoreSavedProfile();
updateConditionalSections();
updateNetworkStatus();
showStep(0);
