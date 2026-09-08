/* Node-only controller regression tests; not browser/visual acceptance. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const appPath = path.resolve(__dirname, '../../src/chatsite/todo_static/app.js');
const context = {window:{}, structuredClone, crypto:require('node:crypto').webcrypto, setTimeout, clearTimeout, Response};
vm.runInNewContext(fs.readFileSync(path.join(path.dirname(appPath),'core.js'),'utf8'),context);
const core = context.window.TodoCore;
const exists = fs.existsSync(appPath);
const exported = exists ? require(appPath) : {};
const node = (id='n', title='original') => ({id, title, parent_id:null, status:'pending', body:'body', order:0});
const board = (id='a', revision=1, title='original') => ({id,title:id,revision,nodes:[node('n',title)],view:{},view_revision:0});
function harness(api) {
  assert.equal(typeof exported.Controller, 'function', 'complete controller must exist');
  const elements = new Map();
  const doc = {getElementById(id) {if(!elements.has(id)) elements.set(id,{value:'',textContent:'',hidden:false,disabled:false, dataset:{},classList:{add(){},remove(){},toggle(){}},setAttribute(){}});return elements.get(id);}};
  const ctl = new exported.Controller({core,doc,win:{},api:api || {request:async()=>({})}});
  for (const name of ['renderBoard','renderDetail','renderMessages','renderControls','renderScope','renderConflict','renderBoardList','renderSaveStatus']) ctl[name]=()=>{};
  ctl.notice=()=>{};
  ctl.setError=(id,error)=>{doc.getElementById(id).textContent=error?.message || error || '';};
  ctl.board=board(); ctl.view=core.normalizeView(ctl.board); ctl.epoch=4;
  return ctl;
}

test('controller file exists and exports its testable state boundary',()=>{
  assert.ok(exists,'app.js must implement the workbench, not a placeholder');
  assert.equal(typeof exported.Controller,'function');
});
test('late results cannot change another tree or a revisited tree epoch',()=>{
  const c=harness(), captured=c.capture();
  c.board=board('b');
  assert.equal(c.acceptBoard(board('a',2),captured),false);
  assert.equal(c.board.id,'b');
  c.board=board('a'); c.epoch++;
  assert.equal(c.acceptBoard(board('a',3),captured),false);
  assert.equal(c.board.revision,1);
});
test('same/older revisions cannot roll back nodes or local view',()=>{
  const c=harness(); c.board.revision=5; c.view.pan.x=123;
  assert.equal(c.acceptBoard(board('a',4,'stale'),c.capture()),false);
  assert.equal(c.acceptBoard(board('a',5,'equal'),c.capture()),false);
  assert.equal(c.board.nodes[0].title,'original');
  assert.equal(c.view.pan.x,123);
});
test('model results preserve an active document draft and current canvas position',()=>{
  const c=harness(); c.selectedId='n'; c.editing=true;
  c.draft={boardId:'a',nodeId:'n',base:exported.editable(node()),values:{...exported.editable(node()),body:'unsaved human text'},baseRevision:1};
  c.view.positions.n={x:919,y:821};
  assert.equal(c.acceptBoard(board('a',2,'model title'),c.capture(),{highlight:true}),true);
  assert.equal(c.draft.values.body,'unsaved human text');
  assert.equal(c.draft.baseRevision,1);
  assert.deepEqual(JSON.parse(JSON.stringify(c.view.positions.n)),{x:919,y:821});
  assert.equal(c.board.nodes[0].title,'model title');
});
test('a clean but actively edited document is not overwritten by model response',()=>{
  const c=harness(); c.selectedId='n'; c.editing=true;
  c.draft={boardId:'a',nodeId:'n',base:exported.editable(node()),values:exported.editable(node()),baseRevision:1};
  c.acceptBoard(board('a',2,'remote edit'),c.capture());
  assert.equal(c.draft.values.title,'original');
});
test('field patches include only human changes, preserving unrelated remote edits',()=>{
  const base=exported.editable(node());
  const draft={base,values:{...base,body:'new body'}};
  assert.deepEqual(exported.draftPatch(draft),{body:'new body'});
  assert.equal(exported.isDirty(draft),true);
  assert.equal(exported.isDirty({base,values:{...base}}),false);
});
test('move candidates exclude self and every descendant',()=>{
  const nodes=[node('a'),{...node('b'),parent_id:'a'},{...node('c'),parent_id:'b'},node('d')];
  assert.deepEqual(exported.parentChoices(core,nodes,'a').map(n=>n.id),['d']);
});
test('failed mutation is never automatically repeated and draft survives 409',async()=>{
  let calls=0;
  const c=harness({request:async()=>{calls++;throw new core.APIError(409,'revision_conflict','conflict');}});
  c.draft={boardId:'a',nodeId:'n',base:exported.editable(node()),values:{...exported.editable(node()),title:'human'},baseRevision:1};
  const result=await c.mutate([{op:'update',id:'n',fields:{title:'human'}}]);
  assert.equal(result,null); assert.equal(calls,1); assert.equal(c.draft.values.title,'human');
  assert.ok(c.conflict); assert.equal(c.mutating,false);
});
test('chat response captured on a previous tree never replaces active nodes or input',async()=>{
  let release;
  const c=harness({request:()=>new Promise(resolve=>{release=resolve;})});
  c.settings={configured:true}; c.el('chat-input').value='split this';
  const pending=c.sendChat();
  assert.equal(typeof release,'function');
  c.board=board('b'); c.epoch++; c.el('chat-input').value='draft for b';
  release({board:board('a',2),message:{role:'assistant',content:'done'}});
  await pending;
  assert.equal(c.board.id,'b'); assert.equal(c.el('chat-input').value,'draft for b');
});
test('source uses safe DOM sinks and implements lifecycle guards',()=>{
  assert.ok(exists); const source=fs.readFileSync(appPath,'utf8');
  assert.doesNotMatch(source,/\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write|localStorage|sessionStorage/);
  for(const token of ['beforeunload','visibilitychange','pointercancel','ViewSaver','confirm_destructive','proposal_id','base_revision','selected_node_id','view_revision']) assert.ok(source.includes(token),token);
});
