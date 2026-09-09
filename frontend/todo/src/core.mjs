export const clone=value=>structuredClone(value);
export const uuid=()=>crypto.randomUUID().replaceAll('-','');
const definiteFailures=new Set(['invalid_model_response','model_not_configured','invalid_model_config','model_auth_error','model_http_error','model_response_too_large','model_timeout','model_unavailable','model_stream_failed','import_storage_error']);
export const isAmbiguousWriteError=error=>error?.status===0||(!definiteFailures.has(error?.code)&&(error?.status>=500||(error?.status>=200&&error?.status<300)));
const statuses=new Set(['pending','in_progress','completed','cancelled']);

export function cleanNodes(value){
  if(!Array.isArray(value)||value.length>2000)throw new Error('画布节点数量无效');
  const ids=new Set();
  const nodes=value.map(raw=>{
    const id=String(raw?.id??'');if(!id||ids.has(id))throw new Error('节点标识为空或重复');ids.add(id);
    return {id,parent_id:raw.parent_id==null?null:String(raw.parent_id),title:String(raw.title??'').trim()||'新想法',status:statuses.has(raw.status)?raw.status:'pending',body:String(raw.body??''),order:Number.isInteger(raw.order)&&raw.order>=0?raw.order:0};
  });
  const map=new Map(nodes.map(node=>[node.id,node]));
  for(const node of nodes){
    let cursor=node,seen=new Set();
    while(cursor.parent_id!==null){
      if(seen.has(cursor.id))throw new Error('节点关系包含循环');seen.add(cursor.id);
      cursor=map.get(cursor.parent_id);if(!cursor)throw new Error('节点父级不存在');
    }
  }
  return nodes;
}

export const sameNodes=(a,b)=>{
  const ordered=nodes=>cleanNodes(nodes).sort((x,y)=>x.id.localeCompare(y.id));
  return JSON.stringify(ordered(a))===JSON.stringify(ordered(b));
};

export function rootsOf(nodes){return cleanNodes(nodes).filter(node=>node.parent_id===null).sort((a,b)=>a.order-b.order||a.id.localeCompare(b.id));}
export function branchOf(nodes,rootId){
  nodes=cleanNodes(nodes);const children=new Map();
  for(const node of nodes){const list=children.get(node.parent_id)||[];list.push(node);children.set(node.parent_id,list);}
  for(const list of children.values())list.sort((a,b)=>a.order-b.order||a.id.localeCompare(b.id));
  const result=[],seen=new Set(),walk=node=>{if(!node||seen.has(node.id))return;seen.add(node.id);result.push(node);(children.get(node.id)||[]).forEach(walk);};
  walk(nodes.find(node=>node.id===rootId&&node.parent_id===null));return result;
}

export function mergeVisibleBranch(all,rootId,visible){
  all=cleanNodes(all);visible=cleanNodes(visible);
  if(!visible.some(node=>node.id===rootId&&node.parent_id===null))throw new Error('编辑结果必须保留根节点');
  const oldBranch=new Set(branchOf(all,rootId).map(node=>node.id));
  const editedIds=new Set(visible.map(node=>node.id));
  for(const node of visible){if(node.id!==rootId&&node.parent_id!==null&&!editedIds.has(node.parent_id))throw new Error('节点不能移出当前根');if(!oldBranch.has(node.id)&&all.some(old=>old.id===node.id))throw new Error('不能覆盖其他根的节点');}
  const rootOrder=all.find(node=>node.id===rootId&&node.parent_id===null)?.order;
  const preserved=visible.map(node=>node.id===rootId&&rootOrder!==undefined?{...node,order:rootOrder}:node);
  return [...preserved,...all.filter(node=>!oldBranch.has(node.id))];
}

export function mergeCollapsed(nodes,rootId,previous,visible){
  const branchIds=new Set(branchOf(nodes,rootId).map(node=>node.id));
  return [...new Set([...(previous||[]).filter(id=>!branchIds.has(id)),...(visible||[]).filter(id=>branchIds.has(id))])];
}

export const isDraftDirty=draft=>Boolean(draft&&JSON.stringify(draft.values)!==JSON.stringify(draft.base));
export const isBoardScopeCurrent=(scope,current)=>Boolean(scope&&scope.id===current.id&&scope.epoch===current.epoch&&scope.queue===current.queue&&scope.views===current.views);

export class ScopedDrafts{
  constructor(){this.values=new Map();}
  get(id){return id?this.values.get(id)||'':'';}
  set(id,value){if(id)this.values.set(id,String(value??''));}
}

export class SingleFlight{
  constructor(){this.busy=false;}
  start(){if(this.busy)return false;this.busy=true;return true;}
  finish(){this.busy=false;}
}

export function diffNodes(before,after){
  before=cleanNodes(before);after=cleanNodes(after);const old=new Map(before.map(n=>[n.id,n])),next=new Map(after.map(n=>[n.id,n]));
  const depth=node=>{let d=0,cursor=node,seen=new Set();while(cursor.parent_id!==null){if(seen.has(cursor.id))throw new Error('节点关系包含循环');seen.add(cursor.id);cursor=next.get(cursor.parent_id);if(!cursor)throw new Error('节点父级不存在');d++;}return d;};
  const creates=after.filter(n=>!old.has(n.id)).sort((a,b)=>depth(a)-depth(b)).map(node=>({op:'create',node}));
  const changes=[];
  for(const node of after){const prior=old.get(node.id);if(!prior)continue;const fields={};for(const key of ['title','status','body'])if(node[key]!==prior[key])fields[key]=node[key];if(Object.keys(fields).length)changes.push({op:'update',id:node.id,fields});if(node.parent_id!==prior.parent_id||node.order!==prior.order)changes.push({op:'move',id:node.id,parent_id:node.parent_id,order:node.order});}
  const removed=new Set(before.filter(n=>!next.has(n.id)).map(n=>n.id));
  const deletes=before.filter(n=>removed.has(n.id)&&!removed.has(n.parent_id)).map(n=>({op:'delete',id:n.id}));
  return [...creates,...changes,...deletes];
}

export function apiBase(page=globalThis.location?.href||'http://localhost/'){
  const url=new URL(page);url.hash='';url.search='';if(!url.pathname.endsWith('/'))url.pathname=url.pathname.slice(0,url.pathname.lastIndexOf('/')+1);return new URL('./api/',url);
}
export class APIError extends Error{constructor(status,code,message){super(message);this.status=status;this.code=code;}}
export class API{
  constructor(base=apiBase()){this.base=base;this.csrf='';this.expired=()=>{};}
  async request(path,method='GET',body){
    const url=new URL(String(path).replace(/^\//,''),this.base);let response;
    try{response=await fetch(url,{method,credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json',...(body===undefined?{}:{'Content-Type':'application/json'}),...(method==='GET'||path==='login'?{}:{'X-CSRF-Token':this.csrf})},...(body===undefined?{}:{body:JSON.stringify(body)})});}
    catch(error){if(error.name==='AbortError')throw error;throw new APIError(0,'network','网络连接中断，写入结果尚未确认。');}
    let data;try{data=await response.json();}catch{throw new APIError(response.status,'invalid_response','服务器响应无法读取，结果尚未确认。');}
    if(!response.ok){if(response.status===401)this.expired();throw new APIError(response.status,data.error?.code||'request_failed',data.error?.message||'请求未完成');}
    if(data.csrf_token)this.csrf=data.csrf_token;return data;
  }
}

export class SemanticQueue{
  constructor(board,perform,publish=()=>{},notify=()=>{}){this.perform=perform;this.publish=publish;this.notify=notify;this.generation=0;this.running=null;this.timer=null;this.unresolved=null;this.retired=false;this.start(board,true);}
  start(board,discard=false){if(this.unresolved&&!discard)throw new Error('请先处理结果未知的保存');clearTimeout(this.timer);this.generation++;this.ack=clone(board);this.board=clone(board);this.latest=null;this.pendingBase=null;if(discard)this.unresolved=null;this.state='saved';this.publish(clone(this.board));this.notify(this.state);}
  observe(board){if(board?.id===this.board?.id&&board.revision>=this.ack.revision){this.ack=clone(board);if(!this.latest)this.board=clone(board);this.publish(clone(this.board));}}
  edit(nodes){if(this.retired)throw new Error('此画布保存队列已关闭');if(this.unresolved)throw new Error('请先重试或核对结果未知的保存');nodes=cleanNodes(nodes);if(sameNodes(nodes,this.board.nodes))return;if(!this.pendingBase)this.pendingBase=clone(this.board.nodes);this.latest=clone(nodes);this.board={...this.board,nodes:clone(nodes)};this.state=this.running?'saving':'dirty';this.publish(clone(this.board));this.notify(this.state);clearTimeout(this.timer);this.timer=setTimeout(()=>this.flush().catch(()=>{}),300);}
  async flush(){clearTimeout(this.timer);if(this.retired)return this.ack;if(this.unresolved)throw this.unresolved.error;if(this.running)return this.running;const generation=this.generation;
    // Retain the displayed editing base: a newer GET must not turn unrelated
    // remote nodes/fields into implicit deletions when the user retries a delta.
    this.running=(async()=>{while(this.latest&&generation===this.generation){const nodes=this.latest,baseNodes=clone(this.pendingBase||this.ack.nodes);this.latest=null;this.pendingBase=null;const operations=diffNodes(baseNodes,nodes);if(!operations.length){this.board=clone(this.ack);this.publish(clone(this.board));continue;}const attempt={id:this.ack.id,payload:{revision:this.ack.revision,request_id:uuid(),operations,confirm_destructive:true},nodes,baseNodes,error:null};this.state='saving';this.notify(this.state);
      try{const result=await this.perform(attempt.id,attempt.payload);if(generation!==this.generation)return this.ack;if(result.board.revision>=this.ack.revision)this.ack=clone(result.board);this.pendingBase=this.latest?clone(nodes):null;this.board={...clone(this.ack),nodes:clone(this.latest||this.ack.nodes)};this.publish(clone(this.board));}
      catch(error){if(generation!==this.generation)return this.ack;attempt.error=error;this.latest=this.latest||nodes;this.pendingBase=baseNodes;if(isAmbiguousWriteError(error))this.unresolved=attempt;this.state='error';this.notify(this.state,error);throw error;}}
      if(generation===this.generation){this.state='saved';this.notify(this.state);}return this.ack;})();
    try{return await this.running;}finally{this.running=null;}
  }
  async retry(){if(!this.unresolved)return this.flush();const attempt=this.unresolved;this.state='saving';this.notify(this.state);try{const result=await this.perform(attempt.id,attempt.payload);if(result.board.revision>=this.ack.revision)this.ack=clone(result.board);this.unresolved=null;if(this.latest&&sameNodes(this.latest,attempt.nodes))this.latest=null;this.pendingBase=this.latest?clone(attempt.nodes):null;this.board={...clone(this.ack),nodes:clone(this.latest||this.ack.nodes)};this.publish(clone(this.board));return this.flush();}catch(error){attempt.error=error;this.state='error';this.notify(this.state,error);throw error;}}
  hasPending(){return Boolean(this.latest||this.running||this.unresolved);}
  retire(){clearTimeout(this.timer);this.retired=true;this.generation++;this.latest=null;this.pendingBase=null;}
}

export class CasQueue{
  constructor(save,revision=0,notify=()=>{},delay=350){this.save=save;this.revision=revision;this.notify=notify;this.delay=delay;this.seq=0;this.done=0;this.value=null;this.running=null;this.timer=null;this.error=null;}
  get pending(){return this.seq>this.done;}
  schedule(value){this.value=clone(value);this.seq++;this.error=null;clearTimeout(this.timer);this.timer=setTimeout(()=>this.flush().catch(()=>{}),this.delay);this.notify('pending');}
  async flush(){clearTimeout(this.timer);if(this.running)return this.running;this.running=(async()=>{while(this.seq>this.done){const seq=this.seq,value=clone(this.value);this.notify('saving');try{const result=await this.save(value,this.revision);this.revision=result.revision;this.done=seq;this.error=null;this.notify(this.seq===seq?'saved':'pending',null,result);}catch(error){this.error=error;this.notify('error',error);throw error;}}})();try{return await this.running;}finally{this.running=null;}}
  rebase(revision){this.revision=revision;}
}

export class UndoRedo{
  constructor(request){this.request=request;this.redoState=null;this.unresolved=null;}
  canRedo(board){return Boolean(this.redoState&&board?.id===this.redoState.id&&board.revision===this.redoState.expectedRevision);}
  semanticChanged(){this.redoState=null;}
  async undo(board){const snapshot=clone(board),payload={revision:board.revision,request_id:uuid()};try{const result=await this.request(`boards/${encodeURIComponent(board.id)}/undo`,payload);this.redoState=result.change?{id:board.id,expectedRevision:result.board.revision,snapshot}:null;return result;}catch(error){if(isAmbiguousWriteError(error))this.unresolved={kind:'undo',path:`boards/${encodeURIComponent(board.id)}/undo`,payload,snapshot,error};throw error;}}
  async redo(board){if(!this.canRedo(board))throw new Error('当前版本已变化，不能重做');const state=this.redoState,path=`boards/${encodeURIComponent(board.id)}`,payload={revision:board.revision,request_id:uuid(),operations:diffNodes(board.nodes,state.snapshot.nodes),confirm_destructive:true};try{const result=await this.request(path,payload,'PATCH');this.redoState=null;return result;}catch(error){if(isAmbiguousWriteError(error))this.unresolved={kind:'redo',path,payload,method:'PATCH',snapshot:state.snapshot,error};throw error;}}
  async retry(){if(!this.unresolved)throw new Error('没有待重试请求');const item=this.unresolved;const result=await this.request(item.path,item.payload,item.method||'POST');this.unresolved=null;if(item.kind==='undo'&&result.change)this.redoState={id:item.snapshot.id,expectedRevision:result.board.revision,snapshot:item.snapshot};if(item.kind==='redo')this.redoState=null;return result;}
}

export class NavigationGate{constructor(){this.version=0;}begin(){return this.version;}changed(){this.version++;}isClean(token){return token===this.version;}}
