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

function setBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = label || 'Working...';
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
  roleNode.textContent = role;
  node.appendChild(roleNode);
  node.appendChild(document.createTextNode(content));
  return node;
}

function renderMessages(messages) {
  const box = $('messages');
  box.innerHTML = '';
  if (!messages.length) {
    box.appendChild(messageNode('assistant', 'Select a project and file, then ask me to edit, explain, or compile it.'));
  } else {
    for (const msg of messages) box.appendChild(messageNode(msg.role, msg.content));
  }
  box.scrollTop = box.scrollHeight;
}

function renderConversations() {
  const box = $('conversationList');
  box.innerHTML = '';
  for (const conv of state.conversations || []) {
    const btn = document.createElement('button');
    btn.className = state.conversation?.id === conv.id ? 'active' : '';
    btn.textContent = conv.title || 'Overleaf chat';
    const stamp = document.createElement('span');
    stamp.textContent = new Date((conv.updated_at || conv.created_at) * 1000).toLocaleString();
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
    box.innerHTML = '<p class="muted">No projects loaded. Check Settings, then refresh.</p>';
  }
}

function renderFiles() {
  const select = $('fileSelect');
  select.innerHTML = '';
  if (!state.files.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = state.selectedProject ? 'No files found' : 'Select a project first';
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
  $('userBadge').textContent = me.email;
  showApp();
  await Promise.all([loadSettings(), loadConversations(), loadProjects()]);
}

async function loadSettings() {
  const data = await api('/api/settings');
  state.settings = data.settings || {};
  $('settingOverleafBaseUrl').value = state.settings.overleaf_base_url || '';
  $('settingOverleafEmail').value = state.settings.overleaf_email || '';
  $('settingOverleafCookieName').value = state.settings.overleaf_cookie_name || 'overleaf_session2';
  $('settingOpenAIModel').value = state.settings.openai_model || 'gpt-4.1-mini';
  $('secretSummary').textContent = `Overleaf password: ${state.settings.overleaf_password_configured ? 'set' : 'missing'}; session cookie: ${state.settings.overleaf_session_cookie_configured ? 'set' : 'missing'}; OpenAI key: ${state.settings.openai_api_key_configured ? 'set' : 'missing'}`;
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
  const data = await api('/api/conversations', { method: 'POST', body: { title: 'New Overleaf chat' } });
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
  setBusy(button, true, 'Loading');
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
  $('fileStatus').textContent = 'Loading files...';
  renderProjects();
  try {
    const data = await api(`/api/projects/${encodeURIComponent(project.id)}/files`);
    state.files = data.files || [];
    renderFiles();
    $('fileStatus').textContent = `${state.files.length} files loaded`;
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
  $('fileStatus').textContent = `Loading ${path}...`;
  try {
    const data = await api(`/api/projects/${encodeURIComponent(state.selectedProject.id)}/files/content?path=${encodeURIComponent(path)}`);
    state.selectedFile = data.file;
    $('editor').value = data.file.content || '';
    $('fileStatus').textContent = data.file.editable ? `${path} ready` : `${path} opened read-only`;
  } catch (error) {
    $('fileStatus').textContent = error.message;
  }
}

async function saveFile() {
  if (!state.selectedProject || !$('fileSelect').value) return;
  const button = $('saveFileButton');
  setBusy(button, true, 'Saving');
  try {
    const path = $('fileSelect').value;
    const data = await api(`/api/projects/${encodeURIComponent(state.selectedProject.id)}/files/content`, {
      method: 'PUT',
      body: { path, content: $('editor').value },
    });
    await selectProject(state.selectedProject);
    $('fileSelect').value = path;
    await openSelectedFile();
    $('fileStatus').textContent = data.result.verified ? `Saved ${path}` : `Saved ${path}; verify returned a mismatch`;
  } catch (error) {
    $('fileStatus').textContent = error.message;
  } finally {
    setBusy(button, false);
  }
}

async function compileProject() {
  if (!state.selectedProject) return;
  const button = $('compileButton');
  setBusy(button, true, 'Compiling');
  $('compileStatus').textContent = 'Compiling in Overleaf...';
  $('pdfFrame').classList.add('hidden');
  try {
    const data = await api(`/api/projects/${encodeURIComponent(state.selectedProject.id)}/compile`, { method: 'POST', body: {} });
    const links = (data.artifacts || []).map((artifact) => `<a href="${artifact.url}" target="_blank" rel="noreferrer">${escapeHtml(artifact.name)}</a>`).join(' ');
    $('compileStatus').innerHTML = `Compile status: ${escapeHtml(data.status)} ${links}`;
    const pdf = (data.artifacts || []).find((artifact) => artifact.name.toLowerCase().endsWith('.pdf'));
    if (pdf) {
      $('pdfFrame').src = pdf.url;
      $('pdfFrame').classList.remove('hidden');
    }
  } catch (error) {
    $('compileStatus').innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
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
  box.appendChild(messageNode('assistant', 'Thinking with the Overleaf tool...'));
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
    if (data.message && /save|saved|compile|compiled|edit/i.test(data.message.content || '')) {
      const previousPath = state.selectedFile?.path || $('fileSelect').value;
      if (state.selectedProject) await selectProject(state.selectedProject);
      if (previousPath) {
        $('fileSelect').value = previousPath;
        await openSelectedFile();
      }
    }
  } catch (error) {
    await loadMessages();
    box.appendChild(messageNode('assistant', `Error: ${error.message}`));
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const button = event.submitter || event.target.querySelector('button[type="submit"]');
  setBusy(button, true, 'Saving');
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
    $('settingsStatus').textContent = 'Settings saved.';
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
  setBusy(button, true, 'Testing');
  try {
    const data = await api('/api/overleaf/test', { method: 'POST', body: {} });
    $('settingsStatus').textContent = `Overleaf OK: ${data.projects} project(s) visible.`;
  } catch (error) {
    $('settingsStatus').textContent = error.message;
  } finally {
    setBusy(button, false);
  }
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
}

bind();
loadMe().catch(() => showLogin());
