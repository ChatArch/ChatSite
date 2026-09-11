const root = document.querySelector(".shell");
const form = document.querySelector("#generateForm");
const promptEl = document.querySelector("#prompt");
const modelEl = document.querySelector("#model");
const sizeEl = document.querySelector("#size");
const statusEl = document.querySelector("#status");
const preview = document.querySelector("#preview");
const empty = document.querySelector("#empty");
const download = document.querySelector("#download");
const share = document.querySelector("#share");
const loginLink = document.querySelector("#loginLink");
const logout = document.querySelector("#logout");
const historyToggle = document.querySelector("#historyToggle");
const historyBox = document.querySelector("#history");
const historyList = document.querySelector("#historyList");
const generateButton = form.querySelector("button[type=\"submit\"]");
let csrfToken = null;
let currentFilename = null;
let generating = false;
let sharing = false;

async function refreshSession() {
  const response = await fetch("login/session", { credentials: "same-origin" });
  const data = await response.json();
  if (data.authenticated) {
    csrfToken = data.csrf_token;
    loginLink.hidden = true;
    logout.hidden = false;
    historyToggle.hidden = false;
  }
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
  return data.error?.message || data.error || fallback;
}

function clearPrivateHistory() {
  historyList.textContent = "";
  if (historyList.replaceChildren) historyList.replaceChildren();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (generating) return;
  generating = true;
  generateButton.disabled = true;
  statusEl.textContent = "正在生成...";
  try {
    const payload = { prompt: promptEl.value, model: modelEl.value, size: sizeEl.value };
    const response = await fetch("api/generate", {
      method: "POST",
      headers: headers(),
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
    const data = await readJson(response);
    if (!response.ok) {
      statusEl.textContent = messageFrom(data, "生成失败，请稍后手动重试");
      return;
    }
    currentFilename = data.filename;
    preview.src = data.image_url;
    preview.hidden = false;
    empty.hidden = true;
    download.href = data.image_url;
    download.hidden = false;
    share.hidden = false;
    statusEl.textContent = "生成完成";
  } catch (_error) {
    statusEl.textContent = "网络异常，生成请求未完成";
  } finally {
    generating = false;
    generateButton.disabled = false;
  }
});

historyToggle.addEventListener("click", async () => {
  historyBox.hidden = !historyBox.hidden;
  if (historyBox.hidden) return;
  const response = await fetch("api/history", { credentials: "same-origin" });
  const data = await response.json();
  historyList.textContent = "";
  for (const item of data.items || []) {
    const node = document.createElement("article");
    node.className = "history-item";
    node.innerHTML = `<img alt="" src="${item.image_url}"><div><p></p><time></time></div>`;
    node.querySelector("p").textContent = item.prompt;
    node.querySelector("time").textContent = new Date(item.created_at * 1000).toLocaleString();
    historyList.append(node);
  }
});

logout.addEventListener("click", async () => {
  try {
    const response = await fetch("api/logout", { method: "POST", headers: headers(), credentials: "same-origin" });
    const data = await readJson(response);
    if (!response.ok) {
      statusEl.textContent = messageFrom(data, "退出失败，请刷新会话后重试");
      logout.hidden = false;
      historyToggle.hidden = false;
      return;
    }
    csrfToken = null;
    loginLink.hidden = false;
    logout.hidden = true;
    historyToggle.hidden = true;
    historyBox.hidden = true;
    clearPrivateHistory();
    statusEl.textContent = "已退出登录";
  } catch (_error) {
    statusEl.textContent = "网络异常，退出未完成";
    logout.hidden = false;
    historyToggle.hidden = false;
  }
});

share.addEventListener("click", async () => {
  if (!currentFilename) return;
  if (sharing) return;
  sharing = true;
  share.disabled = true;
  try {
    const response = await fetch("api/share", {
      method: "POST",
      headers: headers(),
      credentials: "same-origin",
      body: JSON.stringify({ filename: currentFilename }),
    });
    const data = await readJson(response);
    statusEl.textContent = response.ok ? `分享链接：${data.url}` : messageFrom(data, "分享失败");
  } catch (_error) {
    statusEl.textContent = "网络异常，分享未完成";
  } finally {
    sharing = false;
    share.disabled = false;
  }
});

refreshSession();
