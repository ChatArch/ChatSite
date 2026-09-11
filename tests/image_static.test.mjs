import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { setImmediate } from "node:timers/promises";
import vm from "node:vm";

const SCRIPT = readFileSync(new URL("../src/chatsite/image_static/image.js", import.meta.url), "utf8");
const HTML = readFileSync(new URL("../src/chatsite/image_static/index.html", import.meta.url), "utf8");
const CSS = readFileSync(new URL("../src/chatsite/image_static/image.css", import.meta.url), "utf8");

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

class Element {
  constructor(id) {
    this.id = id;
    this.tagName = id;
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.value = "";
    this.href = "#";
    this.src = "";
    this.className = "";
    this._html = "";
    this.download = "";
    this.alt = "";
    this.style = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.children = [];
    this.nodes = new Map();
    this.classList = {
      toggle: (name, force) => {
        const parts = new Set(this.className.split(/\s+/).filter(Boolean));
        if (force) parts.add(name); else parts.delete(name);
        this.className = [...parts].join(" ");
      },
      contains: (name) => this.className.split(/\s+/).includes(name),
    };
  }

  addEventListener(name, fn) {
    this.listeners.set(name, fn);
  }

  dispatch(name) {
    const fn = this.listeners.get(name);
    assert.ok(fn, `${this.id} missing ${name} listener`);
    return fn({ preventDefault() {} });
  }

  append(node) {
    this.children.push(node);
  }

  appendChild(node) {
    this.children.push(node);
    return node;
  }

  replaceChildren() {
    this.children = [];
  }

  querySelector(selector) {
    if (selector === ".wait-bar span") return this.nodes.get(".wait-bar span") || null;
    if (selector === ".waiting-message") return this.nodes.get(".waiting-message") || null;
    if (selector === ".elapsed") return this.nodes.get(".elapsed") || null;
    if (selector === "p" || selector === "time" || selector === "button[type=\"submit\"]") {
      if (!this.nodes.has(selector)) this.nodes.set(selector, new Element(selector));
      return this.nodes.get(selector);
    }
    if (!this.nodes.has(selector)) {
      this.nodes.set(selector, new Element(selector));
    }
    return this.nodes.get(selector);
  }

  querySelectorAll(selector) {
    if (selector === ".step") return this.nodes.get(".step[]") || [];
    return [];
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
    this[name] = value;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === "href") this.href = "";
  }

  focus() {}
  select() {}

  set innerHTML(_html) {
    this._html = _html;
    this.nodes.set("p", new Element("p"));
    this.nodes.set("time", new Element("time"));
    this.nodes.set(".waiting-message", new Element(".waiting-message"));
    this.nodes.set(".elapsed", new Element(".elapsed"));
    this.nodes.set(".wait-bar span", new Element(".wait-bar span"));
    this.nodes.set(".step[]", [new Element(".step0"), new Element(".step1"), new Element(".step2")]);
  }

  get innerHTML() {
    return this._html;
  }
}

function response(ok, body, status = ok ? 200 : 500) {
  return { ok, status, json: async () => body };
}

async function loadApp(fetchImpl) {
  const elements = new Map();
  const ids = [
    ".shell", "#generateForm", "#form", "#prompt", "#model", "#size", "#quality", "#status", "#preview",
    "#empty", "#download", "#share", "#submit", "#logout", "#historyToggle", "#history", "#historyList",
    "#loginLink", "#guestReset", "#counter", "#chips", "#canvas", "#meta", "#capabilities",
    "#share-button", "#share-hint", "#share-result", "#share-url", "#share-status", "#copy-share",
    "#open-share", "#identity",
  ];
  for (const id of ids) elements.set(id, new Element(id));
  elements.set("main", elements.get(".shell"));
  elements.get("#prompt").value = "测试提示词";
  elements.get("#model").value = "gpt-image-2-low";
  elements.get("#size").value = "1024x1024";
  elements.get("#quality").value = "";
  elements.get("#logout").hidden = true;
  elements.get("#historyToggle").hidden = true;
  elements.get("#history").hidden = true;
  elements.get("#guestReset").hidden = true;
  elements.get("#share-button").disabled = true;
  elements.get("#generateForm").nodes.set("button[type=\"submit\"]", elements.get("#submit"));
  elements.get("#form").nodes.set("button[type=\"submit\"]", elements.get("#submit"));

  const context = {
    document: {
      querySelector: (selector) => elements.get(selector),
      getElementById: (id) => elements.get(`#${id}`),
      createElement: (tagName) => new Element(tagName),
      execCommand: () => true,
    },
    window: {
      location: { search: "", pathname: "/", hash: "" },
      history: { replaceState() {} },
      setInterval,
      clearInterval,
    },
    history: { replaceState() {} },
    fetch: fetchImpl,
    Date,
    Image: class extends Element {
      constructor() { super("img"); }
    },
    URL,
    URLSearchParams,
    navigator: { clipboard: { writeText: async () => {} } },
  };
  vm.runInNewContext(SCRIPT, context);
  await setImmediate();
  return elements;
}

test("static page preserves the mature ChatImg visual and interaction affordances", () => {
  assert.match(HTML, /brand-logo/);
  assert.match(HTML, /logo\.png/);
  assert.match(HTML, /github\.com\/ChatArch\/ChatImg/);
  assert.match(HTML, /把一句话变成一张图/);
  assert.match(HTML, /id="counter"/);
  assert.match(HTML, /id="chips"/);
  assert.match(HTML, /id="quality"/);
  assert.match(HTML, /id="canvas"/);
  assert.match(HTML, /id="share-button"/);
  assert.match(HTML, /id="share-result"/);
  assert.match(HTML, /id="loginLink"/);
  assert.match(HTML, /id="history"/);
  assert.doesNotMatch(HTML, /高级编辑|多轮|房间|上传参考图/);
});

test("stylesheet keeps warm paper forest clay system and waiting progress UI", () => {
  for (const token of ["--paper", "--leaf", "--clay", ".masthead", ".brand-logo", ".chip", ".waiting", ".wait-orbit", ".wait-bar", ".elapsed"]) {
    assert.match(CSS, new RegExp(token.replace(".", "\\.")));
  }
  assert.match(CSS, /@media \(max-width: 560px\)/);
});

test("prompt chips fill textarea and update counter", async () => {
  const elements = await loadApp((url) => {
    if (url === "login/session") return Promise.resolve(response(true, { authenticated: false }));
    if (url === "api/capabilities") return Promise.resolve(response(true, { ok: true, provider: "openai", api_mode: "responses", image_model: "gpt-image-2" }));
    throw new Error(`unexpected fetch ${url}`);
  });

  assert.ok(elements.get("#chips").children.length >= 3);
  const chip = elements.get("#chips").children[0];
  chip.dispatch("click");
  assert.equal(elements.get("#prompt").value, chip.textContent);
  assert.equal(elements.get("#counter").textContent, `${chip.textContent.length} / 1800`);
});

test("waiting state shows staged progress and is cleaned up after generation", async () => {
  const pending = deferred();
  const elements = await loadApp((url) => {
    if (url === "login/session") return Promise.resolve(response(true, { authenticated: false }));
    if (url === "api/capabilities") return Promise.resolve(response(true, { ok: true, provider: "openai", api_mode: "responses", image_model: "gpt-image-2" }));
    if (url === "api/generate") return pending.promise;
    throw new Error(`unexpected fetch ${url}`);
  });

  const run = elements.get("#generateForm").dispatch("submit");
  assert.match(elements.get("#canvas").innerHTML, /正在生成/);
  assert.equal(elements.get("#submit").disabled, true);
  pending.resolve(response(true, {
    ok: true,
    filename: "20260912T000000Z-1234567890.png",
    image_url: "/generated/20260912T000000Z-1234567890.png",
    width: 1024,
    height: 1024,
    bytes: 2048,
    model: "gpt-image-2-low",
    sha256_12: "abcdef123456",
    elapsed_sec: 2,
  }));
  await run;
  assert.equal(elements.get("#submit").disabled, false);
  assert.equal(elements.get("#status").textContent, "完成，用时 2s。");
  assert.equal(elements.get("#meta").children.length, 4);
});

test("generation submit is synchronously guarded while in flight and recovers", async () => {
  const pending = deferred();
  let calls = 0;
  const elements = await loadApp((url) => {
    if (url === "login/session") return Promise.resolve(response(true, { authenticated: false }));
    if (url === "api/capabilities") return Promise.resolve(response(true, { ok: true, provider: "openai", api_mode: "responses", image_model: "gpt-image-2" }));
    if (url === "api/generate") {
      calls += 1;
      return pending.promise;
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  const first = elements.get("#generateForm").dispatch("submit");
  const second = elements.get("#generateForm").dispatch("submit");
  assert.equal(calls, 1);
  assert.equal(elements.get("#generateForm").querySelector("button[type=\"submit\"]").disabled, true);

  pending.resolve(response(true, {
    filename: "20260912T000000Z-1234567890.png",
    image_url: "/generated/20260912T000000Z-1234567890.png",
    width: 1024,
    height: 1024,
    bytes: 2048,
    model: "gpt-image-2-low",
    sha256_12: "abcdef123456",
    elapsed_sec: 1,
  }));
  await Promise.all([first, second]);
  assert.equal(elements.get("#generateForm").querySelector("button[type=\"submit\"]").disabled, false);
  assert.equal(elements.get("#status").textContent, "完成，用时 1s。");
});

test("failed logout does not hide authenticated controls or clear private history", async () => {
  const elements = await loadApp((url) => {
    if (url === "login/session") {
      return Promise.resolve(response(true, { authenticated: true, email: "owner@example.test", csrf_token: "csrf" }));
    }
    if (url === "api/capabilities") return Promise.resolve(response(true, { ok: true, provider: "openai", api_mode: "responses", image_model: "gpt-image-2" }));
    if (url === "api/logout") {
      return Promise.resolve(response(false, { error: { message: "会话校验失败" } }, 403));
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  elements.get("#historyList").children.push(new Element("private-record"));

  await elements.get("#logout").dispatch("click");
  assert.equal(elements.get("#logout").hidden, false);
  assert.equal(elements.get("#historyToggle").hidden, false);
  assert.equal(elements.get("#historyList").children.length, 1);
  assert.match(elements.get("#status").textContent, /会话校验失败/);
});

test("authenticated session hides login link and successful logout restores it", async () => {
  const elements = await loadApp((url) => {
    if (url === "login/session") {
      return Promise.resolve(response(true, { authenticated: true, email: "owner@example.test", csrf_token: "csrf" }));
    }
    if (url === "api/capabilities") return Promise.resolve(response(true, { ok: true, provider: "openai", api_mode: "responses", image_model: "gpt-image-2" }));
    if (url === "api/logout") {
      return Promise.resolve(response(true, { ok: true }));
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  assert.equal(elements.get("#loginLink").hidden, true);
  assert.equal(elements.get("#identity").hidden, false);
  assert.equal(elements.get("#identity").textContent, "owner@example.test");
  assert.equal(elements.get("#logout").hidden, false);
  assert.equal(elements.get("#historyToggle").hidden, false);

  await elements.get("#logout").dispatch("click");
  assert.equal(elements.get("#loginLink").hidden, false);
  assert.equal(elements.get("#logout").hidden, true);
  assert.equal(elements.get("#historyToggle").hidden, true);
});

test("successful logout clears csrf controls and private history DOM", async () => {
  const elements = await loadApp((url) => {
    if (url === "login/session") {
      return Promise.resolve(response(true, { authenticated: true, csrf_token: "csrf" }));
    }
    if (url === "api/capabilities") return Promise.resolve(response(true, { ok: true, provider: "openai", api_mode: "responses", image_model: "gpt-image-2" }));
    if (url === "api/logout") {
      return Promise.resolve(response(true, { ok: true }));
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  elements.get("#history").hidden = false;
  elements.get("#historyList").children.push(new Element("private-record"));

  await elements.get("#logout").dispatch("click");
  assert.equal(elements.get("#logout").hidden, true);
  assert.equal(elements.get("#historyToggle").hidden, true);
  assert.equal(elements.get("#history").hidden, true);
  assert.equal(elements.get("#historyList").children.length, 0);
});

test("history response that arrives after logout cannot repopulate private DOM", async () => {
  const history = deferred();
  const elements = await loadApp((url) => {
    if (url === "login/session") {
      return Promise.resolve(response(true, { authenticated: true, csrf_token: "csrf" }));
    }
    if (url === "api/capabilities") return Promise.resolve(response(true, { ok: true, provider: "openai", api_mode: "responses", image_model: "gpt-image-2" }));
    if (url === "api/history") {
      return history.promise;
    }
    if (url === "api/logout") {
      return Promise.resolve(response(true, { ok: true }));
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  elements.get("#history").hidden = true;
  const loading = elements.get("#historyToggle").dispatch("click");
  await elements.get("#logout").dispatch("click");
  history.resolve(response(true, {
    items: [{
      prompt: "不应恢复的私有历史",
      image_url: "/generated/20260912T000000Z-1234567890.png",
      created_at: 1789142400,
    }],
  }));
  await loading;

  assert.equal(elements.get("#history").hidden, true);
  assert.equal(elements.get("#historyList").children.length, 0);
});

test("invalid cookie guest reset preserves prompt and restores guest controls without reload", async () => {
  const elements = await loadApp((url) => {
    if (url === "login/session") return Promise.resolve(response(true, { authenticated: true, csrf_token: "csrf" }));
    if (url === "api/capabilities") return Promise.resolve(response(true, { ok: true, provider: "openai", api_mode: "responses", image_model: "gpt-image-2" }));
    if (url === "api/generate") return Promise.resolve(response(false, { error: { code: "session_expired", message: "登录已失效" } }, 401));
    if (url === "api/guest/reset") return Promise.resolve(response(true, { ok: true, next: "/" }));
    throw new Error(`unexpected fetch ${url}`);
  });

  elements.get("#prompt").value = "保留下来的 prompt";
  await elements.get("#generateForm").dispatch("submit");
  assert.equal(elements.get("#guestReset").hidden, false);
  await elements.get("#guestReset").dispatch("click");
  assert.equal(elements.get("#prompt").value, "保留下来的 prompt");
  assert.equal(elements.get("#loginLink").hidden, false);
  assert.equal(elements.get("#logout").hidden, true);
  assert.equal(elements.get("#historyToggle").hidden, true);
  assert.equal(elements.get("#guestReset").hidden, true);
});

test("share is synchronously guarded while in flight", async () => {
  const pending = deferred();
  let calls = 0;
  const elements = await loadApp((url) => {
    if (url === "login/session") return Promise.resolve(response(true, { authenticated: false }));
    if (url === "api/capabilities") return Promise.resolve(response(true, { ok: true, provider: "openai", api_mode: "responses", image_model: "gpt-image-2" }));
    if (url === "api/generate") {
      return Promise.resolve(response(true, {
        ok: true,
        filename: "20260912T000000Z-1234567890.png",
        image_url: "/generated/20260912T000000Z-1234567890.png",
        width: 1024,
        height: 1024,
        bytes: 2048,
        model: "gpt-image-2-low",
        sha256_12: "abcdef123456",
        elapsed_sec: 1,
      }));
    }
    if (url === "api/share") {
      calls += 1;
      return pending.promise;
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  await elements.get("#generateForm").dispatch("submit");
  const first = elements.get("#share-button").dispatch("click");
  const second = elements.get("#share-button").dispatch("click");
  assert.equal(calls, 1);
  assert.equal(elements.get("#share-button").disabled, true);
  pending.resolve(response(true, { ok: true, url: "https://share.example.test/image.png" }));
  await Promise.all([first, second]);
  assert.equal(elements.get("#share-button").disabled, false);
  assert.equal(elements.get("#share-url").value, "https://share.example.test/image.png");
});
