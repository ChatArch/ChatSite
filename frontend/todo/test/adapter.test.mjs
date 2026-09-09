import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const map=fs.readFileSync(new URL('../src/Map.jsx',import.meta.url),'utf8');
const app=fs.readFileSync(new URL('../src/App.jsx',import.meta.url),'utf8');
const chat=fs.readFileSync(new URL('../src/Chat.jsx',import.meta.url),'utf8');

test('native adapter commits unthrottled text before host actions',()=>{
  assert.match(map,/hideEditTextBox\(\)/);
  assert.match(map,/originAddHistory\(\)/);
  assert.ok(map.indexOf('hideEditTextBox()')<map.indexOf('originAddHistory()'));
});

test('native expand commands also publish view state',()=>{
  assert.match(map,/original\(name,\.\.\.args\).*SET_NODE_EXPAND.*emitView\(true\)/s);
  assert.match(map,/persistCollapse===true.*mergeCollapsed/s);
});

test('native back and forward delegate to authoritative host history',()=>{
  assert.match(map,/name==='BACK'/);assert.match(map,/latest\.current\.onUndo/);
  assert.match(map,/name==='FORWARD'/);assert.match(map,/latest\.current\.onRedo/);
});

test('adapter is plain-text, touch/drag capable, and cache free',()=>{
  for(const plugin of ['Drag','Select','TouchEvent','KeyboardNavigation'])assert.ok(map.includes(plugin));
  assert.match(map,/richText:false/);
  assert.doesNotMatch(map+app,/localStorage|sessionStorage|Quill|RichText/);
});

test('view adapter preserves other roots, domain zoom limits, and timer ownership',()=>{
  for(const token of ['mergeCollapsed','minZoomRatio:20','maxZoomRatio:250','clearTimeout(layoutTimer.current)','instance.current!==m'])assert.ok(map.includes(token),token);
});

test('host exposes independent view and presentation CAS plus exact retries',()=>{
  for(const token of ['/presentation','view_revision','request_id','unresolved','retryUnknown','protectRecovered'])assert.ok(app.includes(token),token);
});

test('composer explains the missing-board prerequisite',()=>{
  assert.match(app,/ready=\{Boolean\(board\)\}/);
  assert.match(chat,/disabled=\{!ready\}/);
  assert.ok(chat.includes('先新建或选择画布'));
});

test('Ant Design X chat has completed markdown and cancelled proposals return false',()=>{
  for(const token of ['Bubble.List','<Sender','<XMarkdown','hasNextChunk:false','result===false'])assert.ok(chat.includes(token),token);
  assert.doesNotMatch(chat,/regenerate|cancelRun|stopGenerating/);
});
