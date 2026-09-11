const examples = [
  "一枚温暖纸张质感的产品图标，绿色叶片和发光镜头，白色背景",
  "一只透明玻璃小狐狸坐在清晨的苔藓上，柔和自然光，极简构图",
  "复古植物学海报风格的蓝色立方体和红苹果，精致阴影，奶油色背景",
];

const root = document.querySelector(".shell");
const form = document.querySelector("#generateForm");
const promptEl = document.querySelector("#prompt");
const counter = document.querySelector("#counter");
const statusEl = document.querySelector("#status");
const canvas = document.querySelector("#canvas");
const meta = document.querySelector("#meta");
const button = document.querySelector("#submit") || form.querySelector("button[type=\"submit\"]");
const modelEl = document.querySelector("#model");
const sizeEl = document.querySelector("#size");
const qualityEl = document.querySelector("#quality");
const capabilitiesEl = document.querySelector("#capabilities");
const chips = document.querySelector("#chips");
const loginLink = document.querySelector("#loginLink");
const identity = document.querySelector("#identity");
const logout = document.querySelector("#logout");
const guestReset = document.querySelector("#guestReset");
const historyToggle = document.querySelector("#historyToggle");
const historyBox = document.querySelector("#history");
const historyList = document.querySelector("#historyList");
const download = document.querySelector("#download");
const shareButton = document.querySelector("#share-button");
const shareHint = document.querySelector("#share-hint");
const shareResult = document.querySelector("#share-result");
const shareUrl = document.querySelector("#share-url");
const shareStatus = document.querySelector("#share-status");
const copyShare = document.querySelector("#copy-share");
const openShare = document.querySelector("#open-share");

let csrfToken = null;
let currentFilename = null;
let generationBusy = false;
let shareBusy = false;
let queryImageBusy = false;
let imageVersion = 0;
let authEpoch = 0;
let waitTimer = null;
let waitStartedAt = 0;

const waitMessages = [
  "正在把 prompt 拆成画面线索。",
  "正在连接服务端的 ChatImg / CRS 生成通道。",
  "模型正在铺光、定构图、生成细节。",
  "正在整理最终图片和安全元数据。",
];

function apiPath(path) {
  return path;
}

function readHref(url) {
  return url || "#";
}

function headers() {
  const value = { "Content-Type": "application/json" };
  if (csrfToken) value["X-CSRF-Token"] = csrfToken;
  return value;
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (_error) {
    return {};
  }
}

function messageFrom(data, fallback) {
  if (data && data.error && typeof data.error === "object") return data.error.message || fallback;
  if (data && typeof data.error === "string") return data.error;
  return fallback;
}

function syncActionButtons() {
  button.disabled = generationBusy || shareBusy || queryImageBusy;
  button.textContent = generationBusy ? "生成中..." : "生成图片";
  shareButton.disabled = !currentFilename || generationBusy || shareBusy || queryImageBusy;
  shareButton.textContent = shareBusy ? "上传中..." : "Share";
}

function clearPrivateHistory() {
  historyList.textContent = "";
  if (historyList.replaceChildren) historyList.replaceChildren();
}

function showGuestSession() {
  csrfToken = null;
  loginLink.hidden = false;
  identity.hidden = true;
  identity.textContent = "";
  logout.hidden = true;
  historyToggle.hidden = true;
  historyBox.hidden = true;
  guestReset.hidden = true;
  clearPrivateHistory();
}

function showAuthenticatedSession(data) {
  csrfToken = data.csrf_token || null;
  loginLink.hidden = true;
  identity.hidden = false;
  identity.textContent = data.email || data.username || data.account || "已登录";
  logout.hidden = false;
  historyToggle.hidden = false;
  guestReset.hidden = true;
}

async function refreshSession() {
  try {
    const response = await fetch(apiPath("login/session"), { credentials: "same-origin" });
    const data = await readJson(response);
    if (response.ok && data.authenticated) {
      showAuthenticatedSession(data);
    } else {
      showGuestSession();
    }
  } catch (_error) {
    showGuestSession();
  }
}

async function loadCapabilities() {
  try {
    const response = await fetch(apiPath("api/capabilities"), { credentials: "same-origin" });
    const data = await readJson(response);
    if (!response.ok || !data.ok) throw new Error("capabilities unavailable");
    const mode = data.api_mode === "responses" ? "Responses" : data.api_mode === "images" ? "Images" : "自动路由";
    const carrier = data.host_model ? `载体 ${data.host_model}` : "";
    const preset = Array.isArray(data.models) ? data.models[0] : "";
    const imageModel = data.image_model ? `图像 ${data.image_model}` : preset ? `预设 ${preset}` : "";
    capabilitiesEl.textContent = [data.provider || "未知提供商", mode, carrier, imageModel].filter(Boolean).join(" · ");
  } catch (_error) {
    capabilitiesEl.textContent = "暂时无法读取生成通道，请稍后重试。";
  }
}

function waitingMarkup(message) {
  return `
    <div class="waiting">
      <div class="wait-orbit"><span class="wait-dot"></span></div>
      <strong>正在生成</strong>
      <p class="waiting-message">${message}</p>
      <div class="wait-steps">
        <span class="step active" data-step="0">理解 prompt</span>
        <span class="step" data-step="1">绘制画面</span>
        <span class="step" data-step="2">保存结果</span>
      </div>
      <div class="wait-bar"><span></span></div>
      <div class="elapsed">已等待 0s</div>
    </div>`;
}

function stopWaiting() {
  if (waitTimer) {
    window.clearInterval(waitTimer);
    waitTimer = null;
  }
}

function startWaiting() {
  stopWaiting();
  waitStartedAt = Date.now();
  canvas.innerHTML = waitingMarkup(waitMessages[0]);
  waitTimer = window.setInterval(() => {
    const elapsed = Math.max(0, Math.floor((Date.now() - waitStartedAt) / 1000));
    const message = waitMessages[Math.min(waitMessages.length - 1, Math.floor(elapsed / 30))];
    const activeStep = Math.min(2, Math.floor(elapsed / 45));
    const progress = Math.min(100, Math.round((elapsed / 90) * 100));
    const messageNode = canvas.querySelector(".waiting-message");
    const elapsedNode = canvas.querySelector(".elapsed");
    const progressNode = canvas.querySelector(".wait-bar span");
    if (messageNode) messageNode.textContent = message;
    if (elapsedNode) elapsedNode.textContent = `已等待 ${elapsed}s`;
    if (progressNode) progressNode.style.width = `${progress}%`;
    canvas.querySelectorAll(".step").forEach((step, index) => {
      step.classList.toggle("active", index <= activeStep);
    });
  }, 1000);
}

function updateCounter() {
  counter.textContent = `${promptEl.value.length} / 1800`;
  if (promptEl.value.trim() && statusEl.textContent === "请先输入 prompt。") {
    statusEl.textContent = "";
  }
}

function clearShareState() {
  currentFilename = null;
  imageVersion += 1;
  shareHint.textContent = "生成图片后可分享";
  shareResult.hidden = true;
  shareUrl.value = "";
  shareStatus.textContent = "";
  openShare.removeAttribute("href");
  download.hidden = true;
  download.href = "#";
  syncActionButtons();
}

function imageUrlFrom(data) {
  return data.image_url || `generated/${encodeURIComponent(data.filename)}`;
}

function addMeta(label, value) {
  if (value === undefined || value === null || value === "") return;
  const card = document.createElement("div");
  card.textContent = label;
  const detail = document.createElement("b");
  detail.textContent = value;
  card.appendChild(detail);
  meta.appendChild(card);
}

function applyCurrentImage(data, updateQuery) {
  if (!/^\d{8}T\d{6}Z-[0-9a-f]{10}\.png$/.test(data.filename || "")) {
    throw new Error("图片文件名无效");
  }
  currentFilename = data.filename;
  imageVersion += 1;
  const img = new Image();
  img.className = "result";
  img.alt = "生成图片";
  img.src = readHref(imageUrlFrom(data));
  canvas.textContent = "";
  if (canvas.replaceChildren) canvas.replaceChildren(img);
  else {
    canvas.textContent = "";
    canvas.appendChild(img);
  }
  meta.style.display = "grid";
  meta.textContent = "";
  if (meta.replaceChildren) meta.replaceChildren();
  addMeta("尺寸", data.width && data.height ? `${data.width} x ${data.height}` : "");
  addMeta("大小", typeof data.bytes === "number" ? `${(data.bytes / 1024 / 1024).toFixed(2)} MB` : "");
  addMeta("模型", data.model || modelEl.value);
  addMeta("SHA256", data.sha256_12);
  download.href = imageUrlFrom(data);
  download.download = data.filename;
  download.hidden = false;
  shareHint.textContent = "点击 Share 会将当前图片公开发布到 ChatShare";
  shareResult.hidden = true;
  shareUrl.value = "";
  shareStatus.textContent = "";
  if (updateQuery && typeof window !== "undefined" && window.history && window.location) {
    const params = new URLSearchParams(window.location.search);
    params.set("image", data.filename);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
  }
  syncActionButtons();
}

function failurePlaceholder() {
  canvas.innerHTML = '<p class="placeholder"><span class="orb"></span><strong>生成失败</strong>可以调整 prompt 后再试。</p>';
}

async function resetToGuest() {
  const response = await fetch(apiPath("api/guest/reset"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
  });
  const data = await readJson(response);
  if (!response.ok) {
    statusEl.textContent = messageFrom(data, "当前登录仍有效，请使用退出登录");
    return false;
  }
  authEpoch += 1;
  showGuestSession();
  statusEl.textContent = "已切换为访客";
  return true;
}

async function loadImageFromQuery() {
  if (typeof window === "undefined" || !window.location) return;
  const filename = new URLSearchParams(window.location.search).get("image");
  if (filename === null) return;
  if (!/^\d{8}T\d{6}Z-[0-9a-f]{10}\.png$/.test(filename)) {
    clearShareState();
    statusEl.textContent = "链接中的图片无效或不存在。";
    return;
  }
  const queryVersion = imageVersion;
  queryImageBusy = true;
  syncActionButtons();
  try {
    const response = await fetch(apiPath(`api/images/${encodeURIComponent(filename)}`), { credentials: "same-origin" });
    const data = await readJson(response);
    if (!response.ok || data.ok === false) throw new Error("not found");
    if (imageVersion !== queryVersion) return;
    applyCurrentImage(data, false);
    statusEl.textContent = "已打开此前生成的图片。";
  } catch (_error) {
    if (imageVersion !== queryVersion) return;
    clearShareState();
    statusEl.textContent = "链接中的图片无效或不存在。";
  } finally {
    queryImageBusy = false;
    syncActionButtons();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (generationBusy || shareBusy || queryImageBusy) return;
  const prompt = promptEl.value.trim();
  if (!prompt) {
    statusEl.textContent = "请先输入 prompt。";
    return;
  }
  generationBusy = true;
  syncActionButtons();
  statusEl.textContent = "正在生成图片，通常需要 30 秒到 3 分钟。";
  meta.style.display = "none";
  if (meta.replaceChildren) meta.replaceChildren();
  clearShareState();
  if (typeof window !== "undefined" && window.history && window.location) {
    const nextQuery = new URLSearchParams(window.location.search);
    nextQuery.delete("image");
    window.history.replaceState(null, "", `${window.location.pathname}${nextQuery.toString() ? `?${nextQuery}` : ""}${window.location.hash}`);
  }
  startWaiting();
  try {
    const body = {
      prompt,
      model: modelEl.value,
      size: sizeEl.value,
      quality: qualityEl.value || null,
    };
    const response = await fetch(apiPath("api/generate"), {
      method: "POST",
      headers: headers(),
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    const data = await readJson(response);
    if (!response.ok || data.ok === false) {
      if (data.error && data.error.code === "session_expired") guestReset.hidden = false;
      throw new Error(messageFrom(data, "生成失败，请稍后手动重试。"));
    }
    stopWaiting();
    applyCurrentImage(data, true);
    statusEl.textContent = typeof data.elapsed_sec === "number" ? `完成，用时 ${data.elapsed_sec}s。` : "生成完成";
  } catch (error) {
    stopWaiting();
    if (!currentFilename) failurePlaceholder();
    statusEl.textContent = error.message || "生成失败，请稍后手动重试。";
  } finally {
    generationBusy = false;
    syncActionButtons();
  }
});

historyToggle.addEventListener("click", async () => {
  historyBox.hidden = !historyBox.hidden;
  if (historyBox.hidden) return;
  const epoch = authEpoch;
  historyList.textContent = "正在读取...";
  try {
    const response = await fetch(apiPath("api/history"), { credentials: "same-origin" });
    const data = await readJson(response);
    if (epoch !== authEpoch || !csrfToken) return;
    clearPrivateHistory();
    for (const item of data.items || []) {
      const node = document.createElement("article");
      node.className = "history-item";
      node.innerHTML = '<img alt=""><div><p></p><time></time></div>';
      const image = node.querySelector("img");
      if (image) image.src = item.image_url || "";
      node.querySelector("p").textContent = item.prompt || "";
      node.querySelector("time").textContent = item.created_at ? new Date(item.created_at * 1000).toLocaleString() : "";
      historyList.append(node);
    }
    if ((data.items || []).length === 0) historyList.textContent = "还没有登录后的生成记录。";
  } catch (_error) {
    if (epoch === authEpoch && csrfToken) historyList.textContent = "历史读取失败，请稍后重试。";
  }
});

logout.addEventListener("click", async () => {
  try {
    const response = await fetch(apiPath("api/logout"), { method: "POST", headers: headers(), credentials: "same-origin" });
    const data = await readJson(response);
    if (!response.ok) {
      statusEl.textContent = messageFrom(data, "退出失败，请刷新会话后重试");
      logout.hidden = false;
      historyToggle.hidden = false;
      return;
    }
    authEpoch += 1;
    showGuestSession();
    statusEl.textContent = "已退出登录";
  } catch (_error) {
    statusEl.textContent = "网络异常，退出未完成";
    logout.hidden = false;
    historyToggle.hidden = false;
  }
});

guestReset.addEventListener("click", async () => {
  await resetToGuest();
});

shareButton.addEventListener("click", async () => {
  if (!currentFilename || generationBusy || shareBusy || queryImageBusy) return;
  const sharingFilename = currentFilename;
  const sharingVersion = imageVersion;
  shareBusy = true;
  syncActionButtons();
  shareHint.textContent = "正在发布原图，请稍候。";
  shareStatus.textContent = "";
  try {
    const response = await fetch(apiPath("api/share"), {
      method: "POST",
      headers: headers(),
      credentials: "same-origin",
      body: JSON.stringify({ filename: sharingFilename }),
    });
    const data = await readJson(response);
    if (currentFilename !== sharingFilename || imageVersion !== sharingVersion) return;
    if (!response.ok || data.ok === false) throw new Error(messageFrom(data, "分享失败，请稍后手动重试。"));
    const publicUrl = new URL(data.url);
    if (publicUrl.protocol !== "https:") throw new Error("分享链接无效。");
    shareUrl.value = publicUrl.href;
    openShare.href = publicUrl.href;
    shareResult.hidden = false;
    shareStatus.textContent = data.reused ? "已复用相同图片的公开链接。" : "图片已公开发布。";
    shareHint.textContent = "当前图片已公开分享";
  } catch (error) {
    if (currentFilename !== sharingFilename || imageVersion !== sharingVersion) return;
    shareResult.hidden = false;
    shareUrl.value = "";
    openShare.removeAttribute("href");
    shareStatus.textContent = error.message || "分享失败，请稍后手动重试。";
    shareHint.textContent = "分享失败，可手动重试";
  } finally {
    shareBusy = false;
    syncActionButtons();
  }
});

copyShare.addEventListener("click", async () => {
  if (!shareUrl.value) return;
  let copied = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(shareUrl.value);
      copied = true;
    }
  } catch (_error) {
    copied = false;
  }
  if (!copied) {
    shareUrl.focus();
    shareUrl.select();
    try {
      copied = document.execCommand("copy") === true;
    } catch (_error) {
      copied = false;
    }
  }
  shareStatus.textContent = copied ? "链接已复制。" : "未能自动复制，请手动选择链接复制。";
});

for (const example of examples) {
  const chip = document.createElement("button");
  chip.className = "chip";
  chip.type = "button";
  chip.textContent = example;
  chip.addEventListener("click", () => {
    promptEl.value = example;
    updateCounter();
    promptEl.focus();
  });
  chips.appendChild(chip);
}

promptEl.addEventListener("input", updateCounter);
updateCounter();
refreshSession();
loadCapabilities();
loadImageFromQuery();

if (typeof window !== "undefined") {
  window.__chatimgStartWaiting = startWaiting;
  const query = new URLSearchParams(window.location.search);
  if (query.get("guest") === "1") {
    resetToGuest().then((ok) => {
      if (ok && window.history && window.history.replaceState) {
        window.history.replaceState(null, "", window.location.pathname + window.location.hash);
      }
    });
  }
}
