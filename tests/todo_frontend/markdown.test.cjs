const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../../src/chatsite/todo_static');
const marked = require(path.join(root, 'vendor/marked.umd.js'));

test('real Markdown parser supports ordinary headings and paragraphs', () => {
  let rendered = '';
  const context = {window: {}, marked, structuredClone, crypto: require('node:crypto').webcrypto,
    DOMPurify: {sanitize(html) { return {html, querySelectorAll() { return []; }}; }},
    setTimeout, clearTimeout};
  vm.runInNewContext(fs.readFileSync(path.join(root, 'core.js'), 'utf8'), context);
  context.window.TodoCore.renderMarkdown({replaceChildren(fragment) { rendered = fragment.html; }}, '# 标题\n\n普通段落');
  assert.match(rendered, /<h1>标题<\/h1>/);
  assert.match(rendered, /<p>普通段落<\/p>/);
});
