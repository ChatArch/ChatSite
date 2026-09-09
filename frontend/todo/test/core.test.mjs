import test from 'node:test';
import assert from 'node:assert/strict';
import {API,APIError,ScopedDrafts,SingleFlight,cleanNodes,diffNodes,mergeCollapsed,mergeVisibleBranch,SemanticQueue,CasQueue,UndoRedo,NavigationGate,apiBase,isBoardScopeCurrent,isDraftDirty} from '../src/core.mjs';

const n=(id,parent_id=null,order=0,title=id)=>({id,parent_id,order,title,status:'pending',body:''});
const board=(revision=1,nodes=[n('root')])=>({id:'b',title:'Board',revision,nodes,view:{pan:{x:0,y:0},zoom:1,positions:{},collapsed:[]},view_revision:0});

test('node diff preserves create depth and sibling order moves',()=>{
  const before=[n('r'),n('a','r',0),n('b','r',1)];
  const after=[n('r'),n('b','r',0),n('a','r',1,'renamed'),n('c','a',0)];
  assert.deepEqual(diffNodes(before,after),[
    {op:'create',node:n('c','a',0)},
    {op:'move',id:'b',parent_id:'r',order:0},
    {op:'update',id:'a',fields:{title:'renamed'}},
    {op:'move',id:'a',parent_id:'r',order:1},
  ]);
});

test('multi-root branch merge never loses another root',()=>{
  const all=[n('r1'),n('a','r1'),n('r2'),n('keep','r2')];
  const edited=[n('r1',null,0,'one'),n('a','r1',0,'changed'),n('new','a')];
  assert.deepEqual(mergeVisibleBranch(all,'r1',edited),[edited[0],edited[1],edited[2],n('r2'),n('keep','r2')]);
  assert.throws(()=>mergeVisibleBranch(all,'r1',[n('r1'),n('foreign','r2')]),/(当前根|父级不存在)/);
});

test('editing a non-first root preserves its forest order',()=>{
  const all=[n('first',null,0),n('second',null,1)];
  const merged=mergeVisibleBranch(all,'second',[n('second',null,0,'edited')]);
  assert.equal(merged.find(node=>node.id==='second').order,1);
});

test('collapsed state from roots outside the visible branch is retained',()=>{
  const nodes=[n('r1'),n('a','r1'),n('r2',null,1),n('b','r2')];
  assert.deepEqual(mergeCollapsed(nodes,'r2',['a','b'],[]),['a']);
  assert.deepEqual(mergeCollapsed(nodes,'r2',['a'],['b']),['a','b']);
});

test('semantic queue serializes edits made while a save is pending',async()=>{
  const calls=[];let release;
  const q=new SemanticQueue(board(),async(_id,payload)=>{calls.push(payload);if(calls.length===1)await new Promise(r=>release=r);const created=calls.length===1?n('a','root'):n('b','root',1);return {board:board(payload.revision+1,[n('root'),n('a','root'),...(calls.length>1?[created]:[])])};});
  q.edit([n('root'),n('a','root')]);const pending=q.flush();await new Promise(r=>setTimeout(r,0));
  q.edit([n('root'),n('a','root'),n('b','root',1)]);release();await pending;
  assert.equal(calls.length,2);assert.equal(calls[1].revision,2);assert.equal(q.state,'saved');
});

test('unknown semantic write retains exact request and explicit retry after refresh',async()=>{
  let count=0,first;
  const q=new SemanticQueue(board(),async(_id,payload)=>{if(!first)first=structuredClone(payload);if(++count===1)throw Object.assign(new Error('unknown'),{status:0});return {board:board(2)};});
  q.edit([n('root',null,0,'edited')]);await assert.rejects(q.flush());
  q.observe(board(1));assert.deepEqual(q.unresolved.payload,first);await q.retry();assert.equal(count,2);assert.equal(q.unresolved,null);
});

test('unreadable successful write retains the exact request identity',async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async()=>({ok:true,status:200,json:async()=>{throw new SyntaxError('truncated');}});
  try{
    const api=new API(new URL('https://fixture.example/api/'));
    const q=new SemanticQueue(board(),(id,payload)=>api.request(`boards/${id}`,'PATCH',payload));
    q.edit([n('root',null,0,'edited')]);await assert.rejects(q.flush());
    const attempt=structuredClone(q.unresolved);assert.ok(attempt.payload.request_id);
    assert.deepEqual(q.unresolved.payload,attempt.payload);
  }finally{globalThis.fetch=original;}
});

test('retiring an outgoing queue cancels its timer and suppresses late publication',async()=>{
  let calls=0,release;const published=[];
  const q=new SemanticQueue(board(),async()=>{calls++;return new Promise(resolve=>release=resolve);},value=>published.push(value));
  q.edit([n('root',null,0,'pending')]);q.retire();await new Promise(resolve=>setTimeout(resolve,330));
  assert.equal(calls,0);
  const active=new SemanticQueue(board(),async()=>new Promise(resolve=>release=resolve),value=>published.push(value));
  active.edit([n('root',null,0,'running')]);const pending=active.flush();await new Promise(resolve=>setTimeout(resolve,0));active.retire();release({board:board(2,[n('root',null,0,'late')])});await pending;
  assert.notEqual(published.at(-1).nodes[0].title,'late');
});

test('confirmed validation/conflict failures remain correctable without losing drafts',async()=>{
  let count=0;
  const q=new SemanticQueue(board(),async()=>{if(++count===1)throw new APIError(409,'conflict','stale');return {board:board(3,[n('root',null,0,'fixed')])};});
  q.edit([n('root',null,0,'too long')]);await assert.rejects(q.flush());
  assert.equal(q.unresolved,null);q.edit([n('root',null,0,'fixed')]);q.observe(board(2));await q.flush();
  assert.equal(q.ack.nodes[0].title,'fixed');
  assert.equal(isDraftDirty({base:{body:'old'},values:{body:'new'}}),true);
});

test('an overlong-title 400 can be corrected and saved with a new attempt',async()=>{
  const requests=[];
  const q=new SemanticQueue(board(),async(_id,payload)=>{
    requests.push(structuredClone(payload));
    if(requests.length===1)throw new APIError(400,'validation_error','title too long');
    return {board:board(2,[n('root',null,0,'short')])};
  });
  q.edit([n('root',null,0,'x'.repeat(500))]);await assert.rejects(q.flush());
  assert.equal(q.unresolved,null);q.edit([n('root',null,0,'short')]);await q.flush();
  assert.equal(q.ack.nodes[0].title,'short');assert.notEqual(requests[0].request_id,requests[1].request_id);
});

test('stale result from an old board cannot publish into the active board',async()=>{
  let release;const seen=[];
  const q=new SemanticQueue(board(),async()=>await new Promise(r=>release=r),b=>seen.push(b.id));
  q.edit([n('root',null,0,'edit')]);const pending=q.flush();await new Promise(r=>setTimeout(r,0));
  q.start({...board(),id:'other'},true);release({board:board(2)});await pending;
  assert.equal(q.board.id,'other');assert.equal(seen.at(-1),'other');
});

test('undo redo is revision-gated and semantic changes clear redo',async()=>{
  const calls=[];const history=new UndoRedo(async(path,payload)=>{calls.push({path,payload});return path.endsWith('/undo')?{board:board(3,[n('root',null,0,'old')]),change:{id:'u'}}:{board:board(4,[n('root',null,0,'new')])};});
  const current=board(2,[n('root',null,0,'new')]);const undone=await history.undo(current);assert.equal(history.canRedo(undone.board),true);
  await history.redo(undone.board);assert.equal(calls[1].payload.revision,3);
  await history.undo(current);history.semanticChanged();assert.equal(history.canRedo(board(3)),false);
});

test('unknown redo preserves its original method, request id, and payload',async()=>{
  const seen=[];let count=0;
  const history=new UndoRedo(async(path,payload,method)=>{seen.push({path,payload:structuredClone(payload),method});if(path.endsWith('/undo'))return {board:board(3,[n('root',null,0,'old')]),change:{id:'u'}};if(++count===1)throw Object.assign(new Error('unknown'),{status:0});return {board:board(4)};});
  const undone=await history.undo(board(2,[n('root',null,0,'new')]));await assert.rejects(history.redo(undone.board));const original=seen.at(-1);await history.retry();
  assert.deepEqual(seen.at(-1),original);assert.equal(seen.at(-1).method,'PATCH');
});

test('successful CAS receipts are not passed as errors',async()=>{
  const errors=[];
  const q=new CasQueue(async(value,revision)=>({value,revision:revision+1}),0,(_state,error)=>{if(error)errors.push(error);});
  q.schedule({zoom:1.2});await q.flush();
  assert.deepEqual(errors,[]);
});

test('independent CAS queue does not consume newer view or layout',async()=>{
  const sent=[];let release;
  const q=new CasQueue(async(value,revision)=>{sent.push({value,revision});if(sent.length===1)await new Promise(r=>release=r);return {value,revision:revision+1};},0);
  q.schedule({zoom:1});const pending=q.flush();await new Promise(r=>setTimeout(r,0));q.schedule({zoom:2});release();await pending;
  assert.deepEqual(sent.map(x=>x.value.zoom),[1,2]);assert.equal(q.pending,false);assert.equal(q.revision,2);
});

test('navigation gate detects edits begun during a delayed GET',()=>{
  const gate=new NavigationGate();const token=gate.begin();gate.changed();assert.equal(gate.isClean(token),false);
});

test('delayed refresh scope and chat drafts stay owned by their original board',()=>{
  const queueA={},viewA={},scope={id:'a',epoch:1,queue:queueA,views:viewA};
  assert.equal(isBoardScopeCurrent(scope,{id:'b',epoch:2,queue:{},views:{}}),false);
  assert.equal(isBoardScopeCurrent(scope,{id:'a',epoch:1,queue:queueA,views:viewA}),true);
  const drafts=new ScopedDrafts();drafts.set('a','draft a');drafts.set('b','draft b');
  const delayedFailure=value=>drafts.set('a',value);delayedFailure('restored a');
  assert.equal(drafts.get('a'),'restored a');assert.equal(drafts.get('b'),'draft b');
});

test('non-idempotent board operations are synchronously single-flight',()=>{
  const flight=new SingleFlight();assert.equal(flight.start(),true);assert.equal(flight.start(),false);flight.finish();assert.equal(flight.start(),true);
});

test('API base follows the current page directory',()=>{
  assert.equal(apiBase('https://example.test/').pathname,'/api/');
  assert.equal(apiBase('https://example.test/labs/todo/integrated/').pathname,'/labs/todo/integrated/api/');
});

test('invalid nodes, cycles, and dropped active roots are rejected',()=>{
  assert.throws(()=>cleanNodes([n('x'),n('x')]),/重复/);
  assert.throws(()=>diffNodes([n('x')],[n('x','x')]),/循环/);
  assert.throws(()=>mergeVisibleBranch([n('r1'),n('r2')],'r1',[]),/保留根节点/);
});
