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
test('ambiguous mutation keeps exact request identity and waits for explicit retry',async()=>{
  const calls=[];
  const c=harness({request:async(path,method,payload)=>{calls.push({path,method,payload:structuredClone(payload)});if(calls.length===1)throw new core.APIError(0,'network','unknown outcome');return {board:board('a',2,'created'),change:{id:'c'}};}});
  const operations=[{op:'create',node:{...node('created'),body:'exact payload'}}];
  assert.equal(await c.mutate(operations),null);
  assert.equal(calls.length,1); assert.ok(c.unresolvedWrite); assert.ok(c.conflict?.reapply);
  await c.mutate([{op:'create',node:node('different')}]);
  assert.equal(calls.length,1,'new writes stay blocked while outcome is unknown');
  await c.conflict.reapply();
  assert.equal(calls.length,2);
  assert.deepEqual(calls[1],calls[0]);
  assert.equal(c.unresolvedWrite,null);
});
test('ambiguous chat keeps input and exact request until explicit retry',async()=>{
  const calls=[];
  const c=harness({request:async(path,method,payload)=>{calls.push({path,method,payload:structuredClone(payload)});if(calls.length===1)throw new core.APIError(0,'network','unknown outcome');return {board:board('a',2),message:{role:'assistant',content:'done'}};}});
  c.settings={configured:true}; c.el('chat-input').value='split this';
  await c.sendChat();
  assert.equal(calls.length,1); assert.equal(c.el('chat-input').value,'split this'); assert.ok(c.unresolvedWrite);
  await c.sendChat();
  assert.equal(calls.length,1,'chat is not resubmitted with a new id');
  await c.conflict.reapply();
  assert.equal(calls.length,2); assert.deepEqual(calls[1],calls[0]);
  assert.equal(c.unresolvedWrite,null); assert.equal(c.el('chat-input').value,'');
});
test('late model deletion preserves a dirty editor as a recoverable draft',()=>{
  const c=harness(); c.selectedId='n'; c.editing=true;
  c.draft={boardId:'a',nodeId:'n',base:exported.editable(node()),values:{...exported.editable(node()),body:'unsaved human text'},baseRevision:1};
  const deleted={...board('a',2),nodes:[]};
  assert.equal(c.acceptBoard(deleted,c.capture(),{highlight:true}),true);
  assert.equal(c.selectedId,'n'); assert.equal(c.draft.values.body,'unsaved human text');
  assert.equal(c.draft.recovered,true); assert.equal(c.node().body,'unsaved human text');
});
test('model deletion proposal asks specifically about dirty content and preserves it',async()=>{
  const deleted={...board('a',2),nodes:[]};
  const c=harness({request:async()=>({board:deleted,change:{id:'change'}})}); c.selectedId='n'; c.editing=true;
  c.draft={boardId:'a',nodeId:'n',base:exported.editable(node()),values:{...exported.editable(node()),body:'unsaved human text'},baseRevision:1};
  c.syncDraft=()=>{}; c.loadMessages=async()=>{}; const prompts=[];c.confirm=async(title)=>{prompts.push(title);return true;};
  await c.applyProposal({id:'p',summary:'delete',base_revision:1,operations:[{op:'delete',id:'n'}]},{disabled:false,textContent:''});
  assert.deepEqual(prompts,['未保存的编辑','应用高风险变更']);
  assert.equal(c.draft.recovered,true); assert.equal(c.draft.values.body,'unsaved human text');
});
test('delayed stale view save is rejected and only explicit rebase retries',async()=>{
  let revision=0, release, delayedOnce=false; const calls=[];
  const save=async(id,view,expected)=>{calls.push({id,view:structuredClone(view),expected});if(view.zoom===1.1&&!delayedOnce){delayedOnce=true;await new Promise(r=>release=r);}if(expected!==revision)throw new core.APIError(409,'view_revision_conflict','stale view');revision++;return {view,view_revision:revision};};
  const stale=new core.ViewSaver(save,()=>{},10000), latest=new core.ViewSaver(save,()=>{},10000);
  stale.schedule('a',{zoom:1.1},0); const delayed=stale.flush('a').catch(error=>error);
  await new Promise(r=>setTimeout(r,0)); latest.schedule('a',{zoom:1.2},0); await latest.flush('a'); release();
  const error=await delayed; assert.equal(error.code,'view_revision_conflict'); assert.equal(stale.hasPending('a'),true);
  assert.equal(calls.length,2,'stale saver never retries automatically');
  stale.rebase('a',revision); await stale.flush('a');
  assert.equal(calls[2].expected,1); assert.equal(revision,2);
});
test('initial unauthenticated start shows login without a false expiry warning',async()=>{
  let c;
  const api={request:async()=>{c.expire();throw new core.APIError(401,'unauthenticated','login');}};
  c=harness(api); c.bind=()=>{}; await c.start();
  assert.equal(c.el('login-error').textContent,''); assert.equal(c.authenticated,false);
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
test('directional plus buttons generate child and sibling insert operations',()=>{
  assert.equal(typeof exported.nodeAddition, 'function');
  const nodes=[
    {...node('root'),title:'root',order:0},
    {...node('a'),parent_id:'root',order:0},
    {...node('b'),parent_id:'root',order:1},
  ];
  const child=exported.nodeAddition(nodes,'a','child','new-child');
  assert.equal(child.node.parent_id,'a'); assert.equal(child.node.order,0);
  assert.deepEqual(child.operations,[{op:'create',node:child.node}]);
  const before=exported.nodeAddition(nodes,'b','before','new-before');
  assert.equal(before.node.parent_id,'root'); assert.equal(before.node.order,1);
  assert.deepEqual(before.operations.map(op=>op.op),['update','create']);
  assert.deepEqual(before.operations[0],{op:'update',id:'b',fields:{order:2}});
  const after=exported.nodeAddition(nodes,'a','after','new-after');
  assert.deepEqual(after.operations.map(op=>op.op),['update','create']);
  assert.deepEqual(after.operations[0],{op:'update',id:'b',fields:{order:2}});
  assert.equal(after.node.order,1);
});

test('directional additions assign readable canvas coordinates and shift siblings',()=>{
  assert.equal(typeof exported.nodeAdditionPositions,'function');
  const nodes=[node('root'),{...node('a'),parent_id:'root',order:0},{...node('b'),parent_id:'root',order:1}];
  const view={positions:{root:{x:60,y:200},a:{x:370,y:200},b:{x:370,y:328}},pan:{x:0,y:0},zoom:1,collapsed:[]};
  const before=exported.nodeAdditionPositions(nodes,view,'b','before','new');
  assert.deepEqual(before.new,{x:370,y:328}); assert.equal(before.positions.b.y,456);
  const child=exported.nodeAdditionPositions(nodes,view,'a','child','new');
  assert.deepEqual(child.new,{x:680,y:200}); assert.equal(child.positions.a.y,200);
});

test('selecting card starts inline title edit while detail opens separately',async()=>{
  const c=harness(); c.protectDraft=async()=>true; c.renderAll=()=>{}; c.renderBoard=()=>{};
  await c.selectNode('n');
  assert.equal(c.selectedId,'n'); assert.equal(c.inlineTitle.id,'n'); assert.equal(c.detailOpen,false);
  await c.openDetail('n');
  assert.equal(c.selectedId,'n'); assert.equal(c.inlineTitle,null); assert.equal(c.detailOpen,true);
});

test('inline title commit patches only title and keeps the detail draft body',async()=>{
  const calls=[];
  const c=harness({request:async(path,method,payload)=>{calls.push(payload);return {board:{...board('a',2,'new'),nodes:[{...node('n','renamed'),body:'body'}]},change:{id:'ch'}};}});
  c.selectedId='n'; c.detailOpen=true; c.inlineTitle={id:'n',value:'original'}; c.draft={boardId:'a',nodeId:'n',base:exported.editable(node()),values:{...exported.editable(node()),body:'unsaved body'},baseRevision:1};
  c.renderAll=()=>{}; await c.commitTitleEdit('n','renamed');
  assert.deepEqual(calls[0].operations,[{op:'update',id:'n',fields:{title:'renamed'}}]);
  assert.equal(c.draft.values.body,'unsaved body');
});

test('real create callback selects the new blank node and queues its view',async()=>{
  let c; const writes=[];
  c=harness({request:async(path,method,payload)=>{
    writes.push(structuredClone(payload));
    const added=payload.operations.find(op=>op.op==='create').node;
    return {board:{...board('a',2),nodes:[node(),added]},change:{id:'created'}};
  }});
  c.protectDraft=async()=>true; c.renderAll=()=>{}; let saved=false;
  c.scheduleView=()=>{saved=true;};
  const result=await c.addNodeAt('n','child');
  assert.ok(result,'a committed write must not become a false callback failure');
  const added=result.board.nodes[1];
  assert.equal(writes.length,1); assert.equal(added.parent_id,'n'); assert.equal(added.body,'');
  assert.equal(c.selectedId,added.id); assert.equal(c.inlineTitle.id,added.id);
  assert.equal(c.detailOpen,false); assert.ok(c.view.positions[added.id]); assert.equal(saved,true);
});

test('canvas navigation discards neither unsaved inline title nor document without confirmation',async()=>{
  const c=harness(); c.selectedId='n'; c.inlineTitle={id:'n',value:'not saved',original:'original',baseRevision:1,boardId:'a'};
  let prompted=false;c.confirm=async()=>{prompted=true;return false;};
  assert.equal(await c.protectDraft('switch canvas'),false);assert.equal(prompted,true);
});

test('a clean document snapshot follows server state while unsaved text stays isolated',()=>{
  const c=harness();c.selectedId='n';c.detailOpen=false;c.makeDraft();
  c.acceptBoard({...board('a',2),nodes:[{...node(),body:'model body'}]},c.capture());
  assert.equal(c.draft.values.body,'model body');
});

test('only the last selected canvas is loaded after out-of-order reads',async()=>{
  let releaseB,releaseC;
  const c=harness({request:async(path)=>{
    if(path.endsWith('/messages'))return {messages:[]};
    if(path.endsWith('/b'))return await new Promise(resolve=>releaseB=resolve);
    if(path.endsWith('/c'))return await new Promise(resolve=>releaseC=resolve);
  }});
  c.protectDraft=async()=>true;c.renderAll=()=>{};
  const b=c.loadBoard('b');await new Promise(r=>setTimeout(r,0));
  const newer=c.loadBoard('c');await new Promise(r=>setTimeout(r,0));
  releaseC({board:board('c')});await newer;
  releaseB({board:board('b')});await b;
  assert.equal(c.board.id,'c');assert.equal(c.messages.length,0);
});

test('reading latest state keeps the original retry reachable after an unknown write',async()=>{
 let patches=0;
 const c=harness({request:async(path,method,payload)=>{
   if(method==='PATCH'){patches++;if(patches===1)throw new core.APIError(0,'network','unknown');return {board:board('a',2,'saved')};}
   return {board:board('a',1)};
 }});
 c.renderAll=()=>{};
 await c.mutate([{op:'update',id:'n',fields:{title:'saved'}}]);
 const id=c.unresolvedWrite.payload.request_id;
 await c.refreshBoard();assert.equal(c.unresolvedWrite.payload.request_id,id);assert.ok(c.conflict?.reapply);
 await c.rebaseConflict();assert.equal(patches,2);assert.equal(c.unresolvedWrite,null);
});

test('both refresh and late model deletion preserve an unsaved inline title',async()=>{
 for(const refresh of [false,true]){
  const c=harness({request:async()=>({board:{...board('a',2),nodes:[]}})});
  c.renderAll=()=>{};c.selectedId='n';c.makeDraft();
  c.inlineTitle={id:'n',value:'unsaved title',original:'original',boardId:'a',baseRevision:1};
  if(refresh)await c.refreshBoard();else c.acceptBoard({...board('a',2),nodes:[]},c.capture());
  assert.equal(c.draft.values.title,'unsaved title');assert.equal(c.draft.recovered,true);assert.equal(c.detailOpen,true);
 }
});

test('navigation rechecks edits made after the outgoing canvas passed its first guard',async()=>{
 let release;
 const c=harness({request:async path=>path.endsWith('/messages')?{messages:[]}:await new Promise(r=>release=r)});c.renderAll=()=>{};
 let prompts=0;c.confirm=async()=>{prompts++;return false;};
 const pending=c.loadBoard('b');await new Promise(r=>setTimeout(r,0));
 c.selectedId='n';c.makeDraft();c.inlineTitle={id:'n',value:'typed during load',original:'original',boardId:'a',baseRevision:1};
 release({board:board('b')});await pending;
 assert.equal(prompts,1);assert.equal(c.board.id,'a');assert.equal(c.inlineTitle.value,'typed during load');
});

test('source uses safe DOM sinks and implements lifecycle guards',()=>{
  assert.ok(exists); const source=fs.readFileSync(appPath,'utf8');
  assert.doesNotMatch(source,/\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write|localStorage|sessionStorage/);
  for(const token of ['beforeunload','visibilitychange','pointercancel','ViewSaver','confirm_destructive','proposal_id','base_revision','selected_node_id','view_revision','card-detail','inline-title-input','add-${direction}']) assert.ok(source.includes(token),token);
});
