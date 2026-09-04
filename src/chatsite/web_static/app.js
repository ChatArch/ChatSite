const state = {
  user: null,
  settings: {},
  projects: [],
  files: [],
  selectedProject: null,
  selectedFile: null,
  conversation: null,
};

const $ = (id) => document.getElementById(id);

const messages = {
  zh: {
    featureEyebrow: 'ChatSite 功能',
    loginTitle: 'Overleaf 编辑工作台',
    loginLede: '通过 ChatOL 连接 Overleaf：列出项目、编辑 TeX 文件、保存到实时协作通道，并编译 PDF/log 输出。',
    emailLabel: '邮箱',
    passwordLabel: '密码',
    enterWorkspace: '进入工作区',
    featureRoute: 'ChatSite / Overleaf',
    appTitle: '对话式 LaTeX 编辑',
    homeLink: 'ChatSite 首页',
    settingsButton: '设置',
    logoutButton: '退出',
    conversationsTitle: '对话',
    newButton: '新建',
    projectsTitle: '项目',
    refreshButton: '刷新',
    casesTitle: '实际案例',
    caseOpenSmoke: '打开 Smoke Test 的 main.tex',
    caseOpenSmokeMeta: '加载示例项目和 TeX 源文件',
    caseCompileSmoke: '编译 Smoke Test',
    caseCompileSmokeMeta: '运行编译并预览 PDF/log 链接',
    casePromptEdit: '填入编辑提示',
    casePromptEditMeta: '准备一个可运行的对话案例',
    chatPlaceholder: '让 ChatSite 检查、编辑或编译当前 Overleaf 文件……',
    sendButton: '发送',
    fileEditorTitle: '文件编辑器',
    compileButton: '编译',
    selectProjectFirst: '请先选择项目',
    reloadButton: '重载',
    editorPlaceholder: '从项目列表打开一个 TeX 文件。',
    noFileSelected: '尚未选择文件',
    saveButton: '保存到 Overleaf',
    connectionEyebrow: '连接设置',
    settingsTitle: 'Overleaf 与模型访问',
    closeButton: '关闭',
    overleafEndpointLabel: 'Overleaf 入口',
    overleafEmailLabel: 'Overleaf 邮箱',
    overleafPasswordLabel: 'Overleaf 密码',
    keepSecretPlaceholder: '留空表示保留当前 secret',
    sessionCookieLabel: 'Session cookie',
    optionalSecretPlaceholder: '可选；留空表示保留当前 secret',
    cookieNameLabel: 'Cookie 名称',
    modelLabel: 'OpenAI 模型',
    openaiKeyLabel: 'OpenAI API key',
    testOverleafButton: '测试 Overleaf',
    saveSettingsButton: '保存设置',
    signedIn: '已登录',
    emptyConversation: '选择项目和文件后，可以让我解释、编辑或编译它。',
    conversationDefault: 'Overleaf 对话',
    noProjects: '没有加载项目。请检查设置，然后刷新。',
    noFiles: '没有找到文件',
    loading: '加载中',
    loadingFiles: '正在加载文件……',
    filesLoaded: '{count} 个文件已加载',
    loadingFile: '正在加载 {path}……',
    fileReady: '{path} 已就绪',
    fileReadOnly: '{path} 已打开（只读）',
    saving: '保存中',
    saved: '已保存 {path}',
    savedMismatch: '已保存 {path}，但回读校验不一致',
    compiling: '编译中',
    compilingOverleaf: '正在 Overleaf 编译……',
    compileStatus: '编译状态：{status}',
    thinking: '正在使用 Overleaf 工具思考……',
    errorPrefix: '错误：{message}',
    settingsSaved: '设置已保存。',
    testing: '测试中',
    overleafOk: 'Overleaf 正常：可见 {count} 个项目。',
    secretSummary: 'Overleaf 密码：{overleaf}; session cookie：{cookie}; OpenAI key：{openai}',
    set: '已设置',
    missing: '未设置',
    smokeMissing: '没有找到示例项目 “Overleaf Deployment Smoke Test”。',
    caseOpenDone: '已打开示例项目 main.tex。',
    caseCompileDone: '示例项目编译完成。',
    casePromptReady: '已填入编辑提示；如果已配置 OpenAI key，可直接发送。',
    casePromptText: '请检查当前 main.tex 的结构，给出一个很小的改进建议；如果需要修改，只改一句说明文字，不要重写整篇。',
  },
  en: {
    featureEyebrow: 'ChatSite Feature',
    loginTitle: 'Overleaf Editor Workspace',
    loginLede: 'Use ChatOL to connect Overleaf: list projects, edit TeX files, save through the realtime collaboration channel, and compile PDF/log output.',
    emailLabel: 'Email',
    passwordLabel: 'Password',
    enterWorkspace: 'Enter Workspace',
    featureRoute: 'ChatSite / Overleaf',
    appTitle: 'Conversational LaTeX Editing',
    homeLink: 'ChatSite Home',
    settingsButton: 'Settings',
    logoutButton: 'Logout',
    conversationsTitle: 'Conversations',
    newButton: 'New',
    projectsTitle: 'Projects',
    refreshButton: 'Refresh',
    casesTitle: 'Real Cases',
    caseOpenSmoke: 'Open Smoke Test main.tex',
    caseOpenSmokeMeta: 'Load the demo project and TeX source',
    caseCompileSmoke: 'Compile Smoke Test',
    caseCompileSmokeMeta: 'Run compile and preview PDF/log links',
    casePromptEdit: 'Fill Edit Prompt',
    casePromptEditMeta: 'Prepare a runnable chat case',
    chatPlaceholder: 'Ask ChatSite to inspect, edit, or compile the selected Overleaf file...',
    sendButton: 'Send',
    fileEditorTitle: 'File Editor',
    compileButton: 'Compile',
    selectProjectFirst: 'Select a project first',
    reloadButton: 'Reload',
    editorPlaceholder: 'Open a TeX file from the project list.',
    noFileSelected: 'No file selected',
    saveButton: 'Save to Overleaf',
    connectionEyebrow: 'Connection Settings',
    settingsTitle: 'Overleaf and Model Access',
    closeButton: 'Close',
    overleafEndpointLabel: 'Overleaf Endpoint',
    overleafEmailLabel: 'Overleaf Email',
    overleafPasswordLabel: 'Overleaf Password',
    keepSecretPlaceholder: 'Leave blank to keep current secret',
    sessionCookieLabel: 'Session cookie',
    optionalSecretPlaceholder: 'Optional; leave blank to keep current secret',
    cookieNameLabel: 'Cookie Name',
    modelLabel: 'OpenAI Model',
    openaiKeyLabel: 'OpenAI API key',
    testOverleafButton: 'Test Overleaf',
    saveSettingsButton: 'Save Settings',
    signedIn: 'signed in',
    emptyConversation: 'Select a project and file, then ask me to explain, edit, or compile it.',
    conversationDefault: 'Overleaf chat',
    noProjects: 'No projects loaded. Check Settings, then refresh.',
    noFiles: 'No files found',
    loading: 'Loading',
    loadingFiles: 'Loading files...',
    filesLoaded: '{count} files loaded',
    loadingFile: 'Loading {path}...',
    fileReady: '{path} ready',
    fileReadOnly: '{path} opened read-only',
    saving: 'Saving',
    saved: 'Saved {path}',
    savedMismatch: 'Saved {path}, but readback verification mismatched',
    compiling: 'Compiling',
    compilingOverleaf: 'Compiling in Overleaf...',
    compileStatus: 'Compile status: {status}',
    thinking: 'Thinking with the Overleaf tool...',
    errorPrefix: 'Error: {message}',
    settingsSaved: 'Settings saved.',
    testing: 'Testing',
    overleafOk: 'Overleaf OK: {count} project(s) visible.',
    secretSummary: 'Overleaf password: {overleaf}; session cookie: {cookie}; OpenAI key: {openai}',
    set: 'set',
    missing: 'missing',
    smokeMissing: 'Demo project “Overleaf Deployment Smoke Test” was not found.',
    caseOpenDone: 'Demo project main.tex is open.',
    caseCompileDone: 'Demo project compile completed.',
    casePromptReady: 'Edit prompt is ready; send it if an OpenAI key is configured.',
    casePromptText: 'Inspect the current main.tex structure and suggest one very small improvement. If editing is needed, only change one explanatory sentence; do not rewrite the paper.',
  },
};

let lang = localStorage.getItem('chatsite_lang') || 'zh';

function t(key, vars = {}) {
  let text = messages[lang][key] || messages.zh[key] || key;
  for (const [name, value] of Object.entries(vars)) {
    text = text.replaceAll(`{${name}}`, String(value));
  }
  return text;
}

function applyLang() {
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  for (const node of document.querySelectorAll('[data-i18n]')) {
    const key = node.dataset.i18n;
    if (messages[lang][key]) node.textContent = messages[lang][key];
  }
  for (const node of document.querySelectorAll('[data-i18n-placeholder]')) {
    const key = node.dataset.i18nPlaceholder;
    if (messages[lang][key]) node.setAttribute('placeholder', messages[lang][key]);
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
  renderConversations();
  renderProjects();
  renderFiles();
  loadSettings().catch(() => undefined);
}

async function api(path, options = {}) {
  const opts = { credentials: 'same-origin', ...options };
  if (opts.body && typeof opts.body !== 'string') {
    opts.headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.body);
  }
  const response = await fetch(path, opts);
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_error) { data = { message: text }; }
  if (response.status === 401 && path !== '/api/me') {
    showLogin();
  }
  if (!response.ok) {
    throw new Error(data.message || data.error || `HTTP ${response.status}`);
  }
  return data;
}

function showLogin() {
  $('loginView').classList.remove('hidden');
  $('appView').classList.add('hidden');
}

function showApp() {
  $('loginView').classList.add('hidden');
  $('appView').classList.remove('hidden');
}

function setBusy(button, busy, labelKey) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = labelKey ? t(labelKey) : t('loading');
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

function messageNode(role, content) {
  const node = document.createElement('div');
  node.className = `message ${role}`;
  const roleNode = document.createElement('span');
  roleNode.className = 'role';
  roleNode.textContent = role === 'user' ? (lang === 'zh' ? '用户' : 'user') : (lang === 'zh' ? '助手' : 'assistant');
  node.appendChild(roleNode);
  node.appendChild(document.createTextNode(content));
  return node;
}

function renderMessages(messagesList) {
  const box = $('messages');
  box.innerHTML = '';
  if (!messagesList.length) {
    box.appendChild(messageNode('assistant', t('emptyConversation')));
  } else {
    for (const msg of messagesList) box.appendChild(messageNode(msg.role, msg.content));
  }
  box.scrollTop = box.scrollHeight;
}

function renderConversations() {
  const box = $('conversationList');
  box.innerHTML = '';
  for (const conv of state.conversations || []) {
    const btn = document.createElement('button');
    btn.className = state.conversation?.id === conv.id ? 'active' : '';
    btn.textContent = conv.title || t('conversationDefault');
    const stamp = document.createElement('span');
    stamp.textContent = new Date((conv.updated_at || conv.created_at) * 1000).toLocaleString(lang === 'zh' ? 'zh-CN' : 'en-US');
    btn.appendChild(stamp);
    btn.addEventListener('click', () => selectConversation(conv));
    box.appendChild(btn);
  }
}

function renderProjects() {
  const box = $('projectList');
  box.innerHTML = '';
  for (const project of state.projects) {
    const btn = document.createElement('button');
    btn.className = state.selectedProject?.id === project.id ? 'active' : '';
    btn.textContent = project.name || project.id;
    const meta = document.createElement('span');
    meta.textContent = project.id;
    btn.appendChild(meta);
    btn.addEventListener('click', () => selectProject(project));
    box.appendChild(btn);
  }
  if (!state.projects.length) {
    box.innerHTML = `<p class="muted">${escapeHtml(t('noProjects'))}</p>`;
  }
}

function renderFiles() {
  const select = $('fileSelect');
  select.innerHTML = '';
  if (!state.files.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = state.selectedProject ? t('noFiles') : t('selectProjectFirst');
    select.appendChild(opt);
    return;
  }
  for (const file of state.files) {
    const opt = document.createElement('option');
    opt.value = file.path;
    opt.textContent = `${file.editable ? '*' : '-'} ${file.path}`;
    select.appendChild(opt);
  }
  if (state.selectedFile) select.value = state.selectedFile.path;
}

async function loadMe() {
  const me = await api('/api/me');
  if (!me.authenticated) {
    showLogin();
    return;
  }
  state.user = me;
  $('userBadge').textContent = me.email || t('signedIn');
  showApp();
  await Promise.all([loadSettings(), loadConversations(), loadProjects()]);
}

async function loadSettings() {
  const data = await api('/api/settings');
  state.settings = data.settings || {};
  $('settingOverleafBaseUrl').value = state.settings.overleaf_base_url || '';
  $('settingOverleafEmail').value = state.settings.overleaf_email || '';
  $('settingOverleafCookieName').value = state.settings.overleaf_cookie_name || 'overleaf_session2';
  $('settingOpenAIModel').value = state.settings.openai_model || 'gpt-5.5';
  $('secretSummary').textContent = t('secretSummary', {
    overleaf: state.settings.overleaf_password_configured ? t('set') : t('missing'),
    cookie: state.settings.overleaf_session_cookie_configured ? t('set') : t('missing'),
    openai: state.settings.openai_api_key_configured ? t('set') : t('missing'),
  });
}

async function loadConversations() {
  const data = await api('/api/conversations');
  state.conversations = data.conversations || [];
  if (!state.conversation && state.conversations.length) {
    state.conversation = state.conversations[0];
    await loadMessages();
  } else if (!state.conversation) {
    await newConversation();
  }
  renderConversations();
}

async function selectConversation(conv) {
  state.conversation = conv;
  renderConversations();
  await loadMessages();
}

async function newConversation() {
  const data = await api('/api/conversations', { method: 'POST', body: { title: t('conversationDefault') } });
  state.conversation = data.conversation;
  await loadConversations();
  renderMessages([]);
}

async function loadMessages() {
  if (!state.conversation) return renderMessages([]);
  const data = await api(`/api/conversations/${state.conversation.id}/messages`);
  renderMessages(data.messages || []);
}

async function loadProjects() {
  const button = $('refreshProjectsButton');
  setBusy(button, true, 'loading');
  try {
    const data = await api('/api/projects');
    state.projects = data.projects || [];
    renderProjects();
  } catch (error) {
    $('projectList').innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  } finally {
    setBusy(button, false);
  }
}

async function selectProject(project) {
  state.selectedProject = project;
  state.selectedFile = null;
  $('editor').value = '';
  $('fileStatus').textContent = t('loadingFiles');
  renderProjects();
  try {
    const data = await api(`/api/projects/${encodeURIComponent(project.id)}/files`);
    state.files = data.files || [];
    renderFiles();
    $('fileStatus').textContent = t('filesLoaded', { count: state.files.length });
  } catch (error) {
    state.files = [];
    renderFiles();
    $('fileStatus').textContent = error.message;
  }
}

async function openSelectedFile() {
  const path = $('fileSelect').value;
  if (!state.selectedProject || !path) return;
  const file = state.files.find((item) => item.path === path) || { path };
  state.selectedFile = file;
  $('fileStatus').textContent = t('loadingFile', { path });
  try {
    const data = await api(`/api/projects/${encodeURIComponent(state.selectedProject.id)}/files/content?path=${encodeURIComponent(path)}`);
    state.selectedFile = data.file;
    $('editor').value = data.file.content || '';
    $('fileStatus').textContent = data.file.editable ? t('fileReady', { path }) : t('fileReadOnly', { path });
  } catch (error) {
    $('fileStatus').textContent = error.message;
  }
}

async function saveFile() {
  if (!state.selectedProject || !$('fileSelect').value) return;
  const button = $('saveFileButton');
  setBusy(button, true, 'saving');
  try {
    const path = $('fileSelect').value;
    const data = await api(`/api/projects/${encodeURIComponent(state.selectedProject.id)}/files/content`, {
      method: 'PUT',
      body: { path, content: $('editor').value },
    });
    await selectProject(state.selectedProject);
    $('fileSelect').value = path;
    await openSelectedFile();
    $('fileStatus').textContent = data.result.verified ? t('saved', { path }) : t('savedMismatch', { path });
  } catch (error) {
    $('fileStatus').textContent = error.message;
  } finally {
    setBusy(button, false);
  }
}

async function compileProject() {
  if (!state.selectedProject) return false;
  const button = $('compileButton');
  setBusy(button, true, 'compiling');
  $('compileStatus').textContent = t('compilingOverleaf');
  $('pdfFrame').classList.add('hidden');
  try {
    const data = await api(`/api/projects/${encodeURIComponent(state.selectedProject.id)}/compile`, { method: 'POST', body: {} });
    const links = (data.artifacts || []).map((artifact) => `<a href="${artifact.url}" target="_blank" rel="noreferrer">${escapeHtml(artifact.name)}</a>`).join(' ');
    $('compileStatus').innerHTML = `${escapeHtml(t('compileStatus', { status: data.status }))} ${links}`;
    const pdf = (data.artifacts || []).find((artifact) => artifact.name.toLowerCase().endsWith('.pdf'));
    if (pdf) {
      $('pdfFrame').src = pdf.url;
      $('pdfFrame').classList.remove('hidden');
    }
    return true;
  } catch (error) {
    $('compileStatus').innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
    return false;
  } finally {
    setBusy(button, false);
  }
}

async function sendChat(event) {
  event.preventDefault();
  const input = $('chatInput');
  const text = input.value.trim();
  if (!text || !state.conversation) return;
  input.value = '';
  const box = $('messages');
  box.appendChild(messageNode('user', text));
  box.appendChild(messageNode('assistant', t('thinking')));
  box.scrollTop = box.scrollHeight;
  try {
    const data = await api(`/api/conversations/${state.conversation.id}/messages`, {
      method: 'POST',
      body: {
        content: text,
        context: {
          project: state.selectedProject || {},
          file: { ...(state.selectedFile || {}), path: $('fileSelect').value, content: $('editor').value },
        },
      },
    });
    await loadMessages();
    if (data.message && /save|saved|compile|compiled|edit|保存|编译|修改/i.test(data.message.content || '')) {
      const previousPath = state.selectedFile?.path || $('fileSelect').value;
      if (state.selectedProject) await selectProject(state.selectedProject);
      if (previousPath) {
        $('fileSelect').value = previousPath;
        await openSelectedFile();
      }
    }
  } catch (error) {
    await loadMessages();
    box.appendChild(messageNode('assistant', t('errorPrefix', { message: error.message })));
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const button = event.submitter || event.target.querySelector('button[type="submit"]');
  setBusy(button, true, 'saving');
  try {
    const body = {
      overleaf_base_url: $('settingOverleafBaseUrl').value,
      overleaf_email: $('settingOverleafEmail').value,
      overleaf_cookie_name: $('settingOverleafCookieName').value,
      openai_model: $('settingOpenAIModel').value,
      overleaf_password: $('settingOverleafPassword').value,
      overleaf_session_cookie: $('settingOverleafSession').value,
      openai_api_key: $('settingOpenAIKey').value,
    };
    const data = await api('/api/settings', { method: 'PUT', body });
    state.settings = data.settings;
    $('settingOverleafPassword').value = '';
    $('settingOverleafSession').value = '';
    $('settingOpenAIKey').value = '';
    $('settingsStatus').textContent = t('settingsSaved');
    await loadSettings();
    await loadProjects();
  } catch (error) {
    $('settingsStatus').textContent = error.message;
  } finally {
    setBusy(button, false);
  }
}

async function testOverleaf() {
  const button = $('testOverleafButton');
  setBusy(button, true, 'testing');
  try {
    const data = await api('/api/overleaf/test', { method: 'POST', body: {} });
    $('settingsStatus').textContent = t('overleafOk', { count: data.projects });
  } catch (error) {
    $('settingsStatus').textContent = error.message;
  } finally {
    setBusy(button, false);
  }
}

async function openSmokeCase() {
  $('caseStatus').textContent = t('loading');
  if (!state.projects.length) await loadProjects();
  const project = state.projects.find((item) => item.name === 'Overleaf Deployment Smoke Test')
    || state.projects.find((item) => /smoke/i.test(item.name || ''));
  if (!project) {
    $('caseStatus').textContent = t('smokeMissing');
    return false;
  }
  await selectProject(project);
  const file = state.files.find((item) => item.path === 'main.tex') || state.files.find((item) => item.editable);
  if (file) {
    $('fileSelect').value = file.path;
    await openSelectedFile();
  }
  $('caseStatus').textContent = t('caseOpenDone');
  return true;
}

async function compileSmokeCase() {
  const opened = await openSmokeCase();
  if (!opened) return;
  const ok = await compileProject();
  if (ok) $('caseStatus').textContent = t('caseCompileDone');
}

function fillEditPromptCase() {
  $('chatInput').value = t('casePromptText');
  $('chatInput').focus();
  $('caseStatus').textContent = t('casePromptReady');
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));
}

function bind() {
  $('loginForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    $('loginError').textContent = '';
    try {
      const data = await api('/api/login', { method: 'POST', body: { email: $('loginEmail').value, password: $('loginPassword').value } });
      state.user = data;
      await loadMe();
    } catch (error) {
      $('loginError').textContent = error.message;
    }
  });
  $('logoutButton').addEventListener('click', async () => { await api('/api/logout', { method: 'POST', body: {} }); showLogin(); });
  $('settingsButton').addEventListener('click', () => $('settingsDialog').showModal());
  $('closeSettingsButton').addEventListener('click', () => $('settingsDialog').close());
  $('settingsForm').addEventListener('submit', saveSettings);
  $('testOverleafButton').addEventListener('click', testOverleaf);
  $('refreshProjectsButton').addEventListener('click', loadProjects);
  $('newConversationButton').addEventListener('click', newConversation);
  $('fileSelect').addEventListener('change', openSelectedFile);
  $('reloadFileButton').addEventListener('click', openSelectedFile);
  $('saveFileButton').addEventListener('click', saveFile);
  $('compileButton').addEventListener('click', compileProject);
  $('chatForm').addEventListener('submit', sendChat);
  $('caseOpenSmoke').addEventListener('click', openSmokeCase);
  $('caseCompileSmoke').addEventListener('click', compileSmokeCase);
  $('casePromptEdit').addEventListener('click', fillEditPromptCase);
  $('languageToggle')?.addEventListener('click', toggleLang);
  $('languageToggleLogin')?.addEventListener('click', toggleLang);
}

applyLang();
bind();
loadMe().catch(() => showLogin());
