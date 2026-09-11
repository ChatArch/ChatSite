import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { setImmediate } from "node:timers/promises";
import vm from "node:vm";

const SCRIPT = readFileSync(new URL("../src/chatsite/image_static/image.js", import.meta.url), "utf8");

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

class Element {
  constructor(id) {
    this.id = id;
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.value = "";
    this.href = "#";
    this.src = "";
    this.className = "";
    this.listeners = new Map();
    this.children = [];
    this.nodes = new Map();
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

  replaceChildren() {
    this.children = [];
  }

  querySelector(selector) {
    if (!this.nodes.has(selector)) {
      this.nodes.set(selector, new Element(selector));
    }
    return this.nodes.get(selector);
  }

  set innerHTML(_html) {
    this.nodes.set("p", new Element("p"));
    this.nodes.set("time", new Element("time"));
  }

  get innerHTML() {
    return "";
  }
}

function response(ok, body, status = ok ? 200 : 500) {
  return { ok, status, json: async () => body };
}

async function loadApp(fetchImpl) {
  const elements = new Map();
  const ids = [
    ".shell", "#generateForm", "#prompt", "#model", "#size", "#status", "#preview",
    "#empty", "#download", "#share", "#logout", "#historyToggle", "#history", "#historyList",
    "#loginLink",
  ];
  for (const id of ids) elements.set(id, new Element(id));
  elements.get("#prompt").value = "测试提示词";
  elements.get("#model").value = "gpt-image-2-low";
  elements.get("#size").value = "1024x1024";
  elements.get("#logout").hidden = true;
  elements.get("#historyToggle").hidden = true;
  elements.get("#history").hidden = true;

  const context = {
    document: { querySelector: (selector) => elements.get(selector) },
    fetch: fetchImpl,
    Date,
  };
  vm.runInNewContext(SCRIPT, context);
  await setImmediate();
  return elements;
}

test("generation submit is synchronously guarded while in flight and recovers", async () => {
  const pending = deferred();
  let calls = 0;
  const elements = await loadApp((url) => {
    if (url === "login/session") return Promise.resolve(response(true, { authenticated: false }));
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
  }));
  await Promise.all([first, second]);
  assert.equal(elements.get("#generateForm").querySelector("button[type=\"submit\"]").disabled, false);
  assert.equal(elements.get("#status").textContent, "生成完成");
});

test("failed logout does not hide authenticated controls or clear private history", async () => {
  const elements = await loadApp((url) => {
    if (url === "login/session") {
      return Promise.resolve(response(true, { authenticated: true, csrf_token: "csrf" }));
    }
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
      return Promise.resolve(response(true, { authenticated: true, csrf_token: "csrf" }));
    }
    if (url === "api/logout") {
      return Promise.resolve(response(true, { ok: true }));
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  assert.equal(elements.get("#loginLink").hidden, true);
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
