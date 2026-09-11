const $ = (id) => document.getElementById(id);
let csrfToken = null;

const messages = {
  zh: {
    hubEyebrow: 'ChatSite / ChatArch 系列',
    hubLoginTitle: 'ChatArch 工作台',
    hubLoginLede: 'ChatSite 是 ChatArch / Chat 系列的统一 Web 入口。使用已配置的站点账号登录后，可以进入各个功能工作区。',
    emailLabel: '邮箱',
    passwordLabel: '密码',
    enterChatSite: '进入 ChatSite',
    logout: '退出',
    hubLede: '统一承载 ChatArch 工具、工作流和协作功能的服务入口。',
    featureEyebrow: '功能 01',
    overleafTitle: 'Overleaf 编辑器',
    overleafDesc: '通过 ChatOL 调用 Overleaf：浏览项目、编辑 TeX、编译 PDF/log，并为每个对话隔离模型上下文。',
    openOverleaf: '打开 Overleaf 工作区',
    casesEyebrow: '可运行案例',
    casesTitle: '上线后可直接验证',
    casesDesc: '进入 Overleaf 工作区后，可以一键打开 Smoke Test 的 main.tex、编译项目，并填入真实编辑提示。',
    runCases: '进入案例',
    serviceMapEyebrow: '服务地图',
    sitesTitle: 'ChatArch Sites',
    sitesDesc: '服务清单、public/local 入口和可用性状态由部署工作区与 ChatGlance 维护。',
    openSites: '打开站点看板',
    badLogin: '登录失败，请检查账号或密码。',
  },
  en: {
    hubEyebrow: 'ChatSite / ChatArch Series',
    hubLoginTitle: 'ChatArch Command Deck',
    hubLoginLede: 'ChatSite is the shared web entry for the ChatArch / Chat series. Sign in with the configured site account to open feature workspaces.',
    emailLabel: 'Email',
    passwordLabel: 'Password',
    enterChatSite: 'Enter ChatSite',
    logout: 'Logout',
    hubLede: 'A shared service surface for ChatArch tools, workflows, and collaboration features.',
    featureEyebrow: 'Feature 01',
    overleafTitle: 'Overleaf Editor',
    overleafDesc: 'Use ChatOL to operate Overleaf: browse projects, edit TeX, compile PDF/log output, and isolate model context per conversation.',
    openOverleaf: 'Open Overleaf Workspace',
    casesEyebrow: 'Real Cases',
    casesTitle: 'Ready-to-run checks',
    casesDesc: 'Open the Overleaf workspace to load Smoke Test/main.tex, compile the project, and prepare a real edit prompt.',
    runCases: 'Run Cases',
    serviceMapEyebrow: 'Service Map',
    sitesTitle: 'ChatArch Sites',
    sitesDesc: 'Service inventory, public/local entrypoints, and availability are maintained by the deployment workspace and ChatGlance.',
    openSites: 'Open Sites Dashboard',
    badLogin: 'Login failed. Check the account or password.',
  },
};

let lang = localStorage.getItem('chatsite_lang') || 'zh';

function applyLang() {
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  for (const node of document.querySelectorAll('[data-i18n]')) {
    const key = node.dataset.i18n;
    if (messages[lang][key]) node.textContent = messages[lang][key];
  }
  for (const id of ['languageToggle', 'languageToggleLogin']) {
    const button = $(id);
    if (button) button.textContent = lang === 'zh' ? 'EN' : '中文';
  }
}

function toggleLang() {
  lang = lang === 'zh' ? 'en' : 'zh';
  localStorage.setItem('chatsite_lang', lang);
  applyLang();
}

async function api(path, options = {}) {
  const opts = { credentials: 'same-origin', ...options };
  const method = (opts.method || 'GET').toUpperCase();
  if (opts.body && typeof opts.body !== 'string') {
    opts.headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.body);
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    opts.headers = { ...(opts.headers || {}), 'X-CSRF-Token': csrfToken };
  }
  const response = await fetch(path, opts);
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_error) { data = { message: text }; }
  if (!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
  return data;
}

function showLogin() {
  $('loginView').classList.remove('hidden');
  $('appView').classList.add('hidden');
}

function showApp(email) {
  $('userBadge').textContent = email || 'signed in';
  $('loginView').classList.add('hidden');
  $('appView').classList.remove('hidden');
}

async function loadMe() {
  const me = await api('/login/session');
  if (me.authenticated) {
    csrfToken = me.csrf_token || null;
    showApp(me.email);
  } else {
    csrfToken = null;
    showLogin();
  }
}

$('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('loginError').textContent = '';
  try {
    const data = await api('/api/login', {
      method: 'POST',
      body: { email: $('loginEmail').value, password: $('loginPassword').value },
    });
    csrfToken = data.csrf_token || null;
    showApp(data.email);
  } catch (error) {
    $('loginError').textContent = messages[lang].badLogin || error.message;
  }
});

$('logoutButton').addEventListener('click', async () => {
  await api('/api/logout', { method: 'POST', body: {} });
  csrfToken = null;
  showLogin();
});

$('languageToggle')?.addEventListener('click', toggleLang);
$('languageToggleLogin')?.addEventListener('click', toggleLang);
applyLang();
loadMe().catch(() => showLogin());
