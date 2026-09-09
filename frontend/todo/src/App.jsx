import React,{useCallback,useEffect,useRef,useState} from 'react';
import {ConfigProvider,Input,Modal,Select} from 'antd';
import zhCN from 'antd/locale/zh_CN';
import MapEditor,{layouts} from './Map.jsx';
import Chat from './Chat.jsx';
import {API,CasQueue,NavigationGate,ScopedDrafts,SemanticQueue,SingleFlight,UndoRedo,clone,isAmbiguousWriteError,isBoardScopeCurrent,isDraftDirty,rootsOf,uuid} from './core.mjs';
import './style.css';

const statusText={saved:'已保存',dirty:'待保存',saving:'保存中…',error:'结果尚未确认'};
const statusOptions=[{value:'pending',label:'待开始'},{value:'in_progress',label:'进行中'},{value:'completed',label:'已完成'},{value:'cancelled',label:'已取消'}];
const ask=options=>new Promise(resolve=>Modal.confirm({...options,onOk:()=>resolve(true),onCancel:()=>resolve(false)}));

function Login({api,onReady}){const [email,setEmail]=useState(''),[password,setPassword]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);async function submit(event){event.preventDefault();setBusy(true);setError('');try{await api.request('login','POST',{email,password});setPassword('');await onReady();}catch(reason){setError(reason.message);}finally{setBusy(false);}}return <main className="login-shell"><form className="login-box" onSubmit={submit}><span className="eyebrow">ChatTodo</span><h1>打开你的画布</h1><p>使用 ChatSite 账号登录。</p><label>邮箱<input type="email" autoComplete="username" required value={email} onChange={e=>setEmail(e.target.value)}/></label><label>密码<input type="password" autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/></label>{error&&<p className="form-error" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy?'正在登录…':'登录'}</button></form></main>;}

export default function App(){
  const api=useRef(new API()).current,mapApi=useRef(null),semantic=useRef(null),viewQueue=useRef(null),presentationQueue=useRef(null),boardRef=useRef(null),detailRef=useRef(null),epoch=useRef(0),loadSeq=useRef(0),gate=useRef(new NavigationGate()),unknownChat=useRef(null),unknownOperation=useRef(null),busyRef=useRef(false),operationFlight=useRef(new SingleFlight()).current,chatDrafts=useRef(new ScopedDrafts());
  const historyController=useRef(new UndoRedo((path,payload,method='POST')=>api.request(path,method,payload))).current;
  const [session,setSession]=useState('checking'),[email,setEmail]=useState(''),[boards,setBoards]=useState([]),[board,setBoard]=useState(null),[messages,setMessages]=useState([]),[settings,setSettings]=useState(null);
  const [selected,setSelected]=useState(null),[rootId,setRootId]=useState(null),[layout,setLayout]=useState('logicalStructure'),[saveState,setSaveState]=useState('saved'),[error,setError]=useState(''),[busy,setBusyState]=useState(false),[sidebar,setSidebar]=useState(false),[chatOpen,setChatOpen]=useState(()=>innerWidth>800),[dialog,setDialog]=useState(null),[detail,setDetail]=useState(null),[chatWidth,setChatWidth]=useState(370);
  const setBusy=value=>{busyRef.current=value;setBusyState(value);};
  boardRef.current=board;detailRef.current=detail;api.expired=()=>setSession('no');
  const roots=board?rootsOf(board.nodes):[],selectedNode=board?.nodes.find(node=>node.id===selected),hasUnknown=Boolean(unknownChat.current||unknownOperation.current||semantic.current?.unresolved||historyController.unresolved),locked=busy||hasUnknown;
  const fail=useCallback(reason=>setError(reason?.message||String(reason)),[]);
  const publish=useCallback(next=>{boardRef.current=next;setBoard(next);},[]);
  function makeSemantic(next){
    const queue=new SemanticQueue(next,(id,payload)=>api.request(`boards/${encodeURIComponent(id)}`,'PATCH',payload));
    queue.publish=value=>{if(semantic.current===queue&&boardRef.current?.id===value.id)publish(value);};
    queue.notify=(state,reason)=>{if(semantic.current!==queue)return;setSaveState(state);if(reason)setError(reason.message);};
    return queue;
  }
  function reconcileDetail(next){const draft=detailRef.current;if(!draft||draft.boardId!==next.id||next.nodes.some(n=>n.id===draft.nodeId))return;if(JSON.stringify(draft.values)!==JSON.stringify(draft.base)){const recovered={...draft,recovered:true};detailRef.current=recovered;setDetail(recovered);setError('目标节点已不存在，未保存的正文已保留，请复制后关闭。');}else{detailRef.current=null;setDetail(null);setSelected(null);}}
  function accept(next,{discard=false,semanticChange=false}={}){reconcileDetail(next);if(!semantic.current||semantic.current.board.id!==next.id){semantic.current=makeSemantic(next);setSaveState('saved');}else semantic.current.start(next,discard);if(semanticChange)historyController.semanticChanged();boardRef.current=next;setBoard(next);const roots=rootsOf(next.nodes);setRootId(current=>roots.some(r=>r.id===current)?current:roots[0]?.id||null);}
  async function listBoards(){const data=await api.request('boards');setBoards(data.boards||[]);return data.boards||[];}
  async function loadMessages(id,token){const data=await api.request(`boards/${encodeURIComponent(id)}/messages`);if(token===epoch.current&&boardRef.current?.id===id)setMessages(data.messages||[]);}
  async function setupAux(id,next){
    viewQueue.current=new CasQueue(async(value,revision)=>{const saved=await api.request(`boards/${encodeURIComponent(id)}/view`,'PATCH',{view:value,view_revision:revision});return {value:saved.view,revision:saved.view_revision};},next.view_revision,(_state,reason)=>reason&&fail(reason));
    presentationQueue.current=null;const result=await api.request(`boards/${encodeURIComponent(id)}/presentation`);if(boardRef.current?.id!==id)return;setLayout(result.layout);presentationQueue.current=new CasQueue(async(value,revision)=>{const saved=await api.request(`boards/${encodeURIComponent(id)}/presentation`,'PATCH',{layout:value,revision});return {value:saved.layout,revision:saved.revision};},result.revision,(_state,reason)=>reason&&fail(reason));
  }
  async function settle({body=true}={}){
    if(unknownChat.current||unknownOperation.current||semantic.current?.unresolved||historyController.unresolved)throw new Error('请先核对结果未知的请求');
    await mapApi.current?.finishEdit?.();
    const draft=detailRef.current,current=semantic.current?.board;
    let pendingDraft=null;
    if(body&&draft&&current?.id===draft.boardId&&!draft.recovered&&isDraftDirty(draft)){
      if(!current.nodes.some(n=>n.id===draft.nodeId))throw new Error('正文目标节点已不存在，草稿仍保留');
      historyController.semanticChanged();
      semantic.current.edit(current.nodes.map(n=>n.id===draft.nodeId?{...n,...draft.values}:n));
      pendingDraft={boardId:draft.boardId,nodeId:draft.nodeId,values:clone(draft.values)};
    }
    const saved=await semantic.current?.flush();
    if(pendingDraft){
      const latest=detailRef.current;
      if(latest?.boardId===pendingDraft.boardId&&latest.nodeId===pendingDraft.nodeId&&JSON.stringify(latest.values)===JSON.stringify(pendingDraft.values)){
        const clean={...latest,base:clone(pendingDraft.values)};detailRef.current=clean;setDetail(clean);
      }
    }
    await viewQueue.current?.flush();await presentationQueue.current?.flush();return saved||semantic.current?.ack;
  }
  async function protectRecovered(){if(!detailRef.current?.recovered)return true;return ask({title:'未保存正文仍在编辑器中',content:'目标节点已不存在。继续会关闭这份恢复草稿，请先复制需要保留的内容。',okText:'放弃并继续',cancelText:'返回复制'});}
  async function loadBoard(id,{force=false,internal=false}={}){
    if(!id||(busy&&!internal)||(!force&&boardRef.current?.id===id))return;if(hasUnknown&&!internal){fail(new Error('请先核对并重试结果未知的请求'));return;}if(!await protectRecovered())return;
    const outgoing=semantic.current;
    try{if(boardRef.current)await settle();const sequence=++loadSeq.current,guard=gate.current.begin(),prior=boardRef.current?.id;const data=await api.request(`boards/${encodeURIComponent(id)}`);if(sequence!==loadSeq.current)return;
      if(!gate.current.isClean(guard)){
        const proceed=await ask({title:'加载期间出现了新编辑',content:'先保存刚产生的编辑，再切换画布？',okText:'保存并切换',cancelText:'留在当前画布'});
        if(!proceed)return;
        await settle();
      }
      if(!internal&&busyRef.current){fail(new Error('加载期间开始了其他操作，已留在当前画布。'));return;}
      if(sequence!==loadSeq.current)return;
      outgoing?.retire();if(semantic.current===outgoing)semantic.current=null;
      if(prior!==id)epoch.current++;viewQueue.current=null;presentationQueue.current=null;accept(data.board,{discard:true});setSelected(null);setMessages([]);setDetail(null);setSidebar(false);setError('');historyController.semanticChanged();await setupAux(id,data.board);await loadMessages(id,epoch.current);
    }catch(reason){fail(reason);}
  }
  async function initialize(){try{const info=await api.request('session');setEmail(info.email||'');setSession('yes');const [all,config]=await Promise.all([listBoards(),api.request('settings')]);setSettings(config);if(all.length)await loadBoard(all[0].id);else{setBoard(null);setSession('yes');}}catch(reason){if(reason.status===401)setSession('no');else{fail(reason);setSession('no');}}}
  useEffect(()=>{initialize();},[]);
  useEffect(()=>{const warn=event=>{if(semantic.current?.hasPending()||isDraftDirty(detailRef.current)||detailRef.current?.recovered||busy||unknownChat.current||unknownOperation.current||historyController.unresolved){event.preventDefault();event.returnValue='';}};addEventListener('beforeunload',warn);return()=>removeEventListener('beforeunload',warn);},[busy,historyController]);
  const onNodes=useCallback(nodes=>{try{gate.current.changed();historyController.semanticChanged();semantic.current.edit(nodes);}catch(reason){fail(reason);}},[fail,historyController]);
  const onView=useCallback(view=>{if(!boardRef.current||!viewQueue.current)return;setBoard(current=>{const next=current?{...current,view}:current;boardRef.current=next;return next;});viewQueue.current.schedule(view);},[]);
  async function saveDetail(){try{await settle();setDetail(null);}catch(reason){fail(reason);}}
  async function openDetail(){try{await settle({body:false});const node=boardRef.current?.nodes.find(n=>n.id===selected);if(!node)return;const next={boardId:boardRef.current.id,nodeId:node.id,base:{body:node.body,status:node.status},values:{body:node.body,status:node.status},recovered:false};detailRef.current=next;setDetail(next);}catch(reason){fail(reason);}}
  async function openNew(){if(locked)return;try{if(boardRef.current)await settle();setDialog({kind:'new',value:'新的想法'});}catch(reason){fail(reason);}}
  async function chooseImport(){if(locked)return;try{if(boardRef.current)await settle();document.getElementById('import-file').click();}catch(reason){fail(reason);}}
  async function switchRoot(value){try{await settle();setSelected(null);setRootId(value);}catch(reason){fail(reason);}}
  async function changeLayout(value){try{await mapApi.current?.finishEdit?.();await semantic.current?.flush();setLayout(value);presentationQueue.current?.schedule(value);}catch(reason){fail(reason);}}
  async function undo(){if(locked||!boardRef.current)return;setBusy(true);try{const current=await settle(),result=await historyController.undo(current);if(result.change)accept(result.board,{discard:true});else setError('没有可撤销的变更');await listBoards();}catch(reason){fail(reason);}finally{setBusy(false);}}
  async function redo(){if(locked||!boardRef.current)return;setBusy(true);try{await settle();const result=await historyController.redo(semantic.current.ack);accept(result.board,{discard:true});await listBoards();}catch(reason){fail(reason);}finally{setBusy(false);}}
  async function retryUnknown(){try{setBusy(true);let result;if(semantic.current?.unresolved)result=await semantic.current.retry();else if(historyController.unresolved)result=await historyController.retry();else if(unknownChat.current){const item=unknownChat.current;result=await api.request(item.path,'POST',item.payload);if(item.boardId!==boardRef.current?.id||item.epoch!==epoch.current)return;unknownChat.current=null;accept(result.board,{discard:true});await loadMessages(item.boardId,item.epoch);}if(result?.board&&result.board.id===boardRef.current?.id)accept(result.board,{discard:true});setError('');}catch(reason){fail(reason);}finally{setBusy(false);}}
  async function refresh(){if(!boardRef.current)return;const scope={id:boardRef.current.id,epoch:epoch.current,queue:semantic.current,views:viewQueue.current};try{const data=await api.request(`boards/${encodeURIComponent(scope.id)}`);if(!isBoardScopeCurrent(scope,{id:boardRef.current?.id,epoch:epoch.current,queue:semantic.current,views:viewQueue.current}))return;reconcileDetail(data.board);scope.queue.observe(data.board);setBoard(scope.queue.board);scope.views?.rebase(data.board.view_revision);setError('已读取服务器当前状态；原请求仍可重试。');}catch(reason){fail(reason);}}
  async function retryConfirmed(){try{await settle();setError('');}catch(reason){fail(reason);}}
  async function discardLocal(){if(!boardRef.current)return;const ok=await ask({title:'放弃本地未保存修改？',content:'将重新读取服务器版本。正文草稿也会关闭，请先复制需要保留的内容。',okText:'放弃并读取',okType:'danger',cancelText:'取消'});if(!ok)return;const id=boardRef.current.id,token=epoch.current;try{const data=await api.request(`boards/${encodeURIComponent(id)}`);if(boardRef.current?.id!==id||epoch.current!==token)return;detailRef.current=null;setDetail(null);semantic.current.start(data.board,true);setError('');}catch(reason){fail(reason);}}
  async function retryAux(){if(!boardRef.current)return;setBusy(true);try{const id=boardRef.current.id;if(viewQueue.current?.error){const pending=clone(viewQueue.current.value),data=await api.request(`boards/${encodeURIComponent(id)}`);if(boardRef.current?.id!==id)return;semantic.current.observe(data.board);viewQueue.current.rebase(data.board.view_revision);viewQueue.current.schedule(pending);await viewQueue.current.flush();}if(presentationQueue.current?.error){const pending=clone(presentationQueue.current.value),data=await api.request(`boards/${encodeURIComponent(id)}/presentation`);if(boardRef.current?.id!==id)return;presentationQueue.current.rebase(data.revision);presentationQueue.current.schedule(pending);await presentationQueue.current.flush();}setError('');}catch(reason){fail(reason);}finally{setBusy(false);}}
  async function send(message){if(locked||!boardRef.current)throw new Error('请先完成当前保存或未知请求');const current=await settle(),token=epoch.current,id=current.id,payload={message,selected_node_id:current.nodes.some(n=>n.id===selected)?selected:null,revision:current.revision,request_id:uuid()};setMessages(old=>[...old,{id:`pending-${payload.request_id}`,role:'user',content:message}]);setBusy(true);try{const result=await api.request(`boards/${encodeURIComponent(id)}/chat`,'POST',payload);if(token!==epoch.current||boardRef.current?.id!==id)return;historyController.semanticChanged();accept(result.board,{discard:true});await Promise.all([loadMessages(id,token),listBoards()]);}catch(reason){const currentBoard=token===epoch.current&&boardRef.current?.id===id;if(currentBoard&&isAmbiguousWriteError(reason)){unknownChat.current={path:`boards/${encodeURIComponent(id)}/chat`,payload,boardId:id,epoch:token};setMessages(old=>[...old,{id:`error-${payload.request_id}`,role:'assistant',content:reason.message,isError:true}]);}if(currentBoard)fail(reason);throw reason;}finally{setBusy(false);}}
  async function applyProposal(proposal){if(locked)return false;let current;try{current=await settle();}catch(reason){fail(reason);throw reason;}const confirmed=await ask({title:'应用这组节点变更？',content:proposal.summary||'其中可能包含移动或删除操作。',okText:'确认应用',cancelText:'取消'});if(!confirmed)return false;setBusy(true);let path,payload,token;try{token=epoch.current;path=`boards/${encodeURIComponent(current.id)}/apply`;payload={proposal_id:proposal.id,revision:current.revision,request_id:uuid(),confirm_destructive:true};const result=await api.request(path,'POST',payload);if(token!==epoch.current||boardRef.current?.id!==current.id)return false;historyController.semanticChanged();accept(result.board,{discard:true});await loadMessages(current.id,token);return true;}catch(reason){const currentBoard=token===epoch.current&&boardRef.current?.id===current.id;if(currentBoard&&path&&isAmbiguousWriteError(reason))unknownChat.current={path,payload,boardId:current.id,epoch:token};if(currentBoard)fail(reason);throw reason;}finally{setBusy(false);}}
  async function createBoard(){const value=dialog?.value?.trim();if(!value||busy||unknownOperation.current||!operationFlight.start())return;const known=new Set(boards.map(item=>item.id));let submitted=false;setBusy(true);try{await settle();submitted=true;const data=await api.request('boards','POST',{title:value});setDialog(null);await listBoards();await loadBoard(data.board.id,{internal:true});}catch(reason){if(submitted&&isAmbiguousWriteError(reason))unknownOperation.current={kind:'create',title:value,known};fail(reason);}finally{operationFlight.finish();setBusy(false);}}
  async function deleteBoard(){if(!boardRef.current||busy||!operationFlight.start())return;let submitted=false;setBusy(true);try{const current=await settle();const ok=await ask({title:'删除这个画布？',content:'此操作不可直接恢复。',okText:'确认删除',okType:'danger',cancelText:'取消'});if(!ok)return;submitted=true;await api.request(`boards/${encodeURIComponent(current.id)}`,'DELETE',{revision:current.revision,confirm:true});epoch.current++;semantic.current?.retire();semantic.current=null;boardRef.current=null;setBoard(null);setMessages([]);setDetail(null);const all=await listBoards();if(all.length)await loadBoard(all[0].id,{internal:true});}catch(reason){if(submitted&&isAmbiguousWriteError(reason)&&boardRef.current)unknownOperation.current={kind:'delete',boardId:boardRef.current.id,known:new Set(boards.map(item=>item.id))};fail(reason);}finally{operationFlight.finish();setBusy(false);}}
  async function exportBoard(){if(!boardRef.current)return;try{await settle();const data=await api.request(`boards/${encodeURIComponent(boardRef.current.id)}/export`);const href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=href;a.download=`${boardRef.current.title||'chattodo'}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(href),1000);}catch(reason){fail(reason);}}
  async function importBoard(file){if(!file||busy||unknownOperation.current||!operationFlight.start())return;let parsed,submitted=false;const known=new Set(boards.map(item=>item.id));setBusy(true);try{await settle();parsed=JSON.parse(await file.text());submitted=true;const data=await api.request('import','POST',{board:parsed});await listBoards();await loadBoard(data.board.id,{internal:true});}catch(reason){if(submitted&&parsed&&isAmbiguousWriteError(reason))unknownOperation.current={kind:'import',title:parsed.title||parsed.board?.title||'',known};fail(reason);}finally{operationFlight.finish();setBusy(false);}}
  async function reconcileOperation(){const item=unknownOperation.current;if(!item||!operationFlight.start())return;setBusy(true);try{const all=await listBoards();let matches=[];if(item.kind==='delete'){if(!all.some(board=>board.id===item.boardId)){unknownOperation.current=null;if(boardRef.current?.id===item.boardId){semantic.current?.retire();semantic.current=null;boardRef.current=null;setBoard(null);setMessages([]);if(all.length)await loadBoard(all[0].id,{internal:true});}setError('删除结果已核对。');return;}}else matches=all.filter(board=>!item.known.has(board.id)&&(!item.title||board.title===item.title));if(matches.length===1){unknownOperation.current=null;setDialog(null);await loadBoard(matches[0].id,{internal:true});setError('操作结果已核对。');return;}const unlock=await ask({title:'未找到唯一结果',content:'画布列表已刷新。解除锁定前请人工核对，避免重复创建或导入。',okText:'已核对，解除锁定',cancelText:'保持锁定'});if(unlock){unknownOperation.current=null;setError('');}}catch(reason){fail(reason);}finally{operationFlight.finish();setBusy(false);}}
  async function showHistory(){if(!boardRef.current)return;try{await settle();const data=await api.request(`boards/${encodeURIComponent(boardRef.current.id)}/history`);setDialog({kind:'history',changes:data.changes||[]});}catch(reason){fail(reason);}}
  async function logout(){if(!await protectRecovered())return;try{await settle();await api.request('logout','POST',{});epoch.current++;setBoard(null);setMessages([]);setSession('no');}catch(reason){fail(reason);}}
  async function addCenter(){if(!semantic.current||boardRef.current.nodes.length)return;try{historyController.semanticChanged();semantic.current.edit([{id:uuid(),parent_id:null,title:'新想法',status:'pending',body:'',order:0}]);await semantic.current.flush();}catch(reason){fail(reason);}}
  function resize(event){if(event.button!==0)return;event.preventDefault();const x=event.clientX,width=chatWidth,move=e=>setChatWidth(Math.max(310,Math.min(560,width+x-e.clientX))),up=()=>{removeEventListener('pointermove',move);removeEventListener('pointerup',up);};addEventListener('pointermove',move);addEventListener('pointerup',up,{once:true});}
  if(session==='checking')return <main className="loading-shell">正在打开 ChatTodo…</main>;
  if(session==='no')return <Login api={api} onReady={initialize}/>;

  const updateDetail=values=>{
    gate.current.changed();
    const next={...detail,values:{...detail.values,...values}};
    detailRef.current=next;
    setDetail(next);
  };
  const closeDetail=()=>{
    if(detail?.recovered||isDraftDirty(detail)){
      ask({title:'放弃未保存的正文？',okText:'放弃',okType:'danger',cancelText:'继续编辑'}).then(ok=>{
        if(ok){detailRef.current=null;setDetail(null);}
      });
    }else setDetail(null);
  };

  return (
    <ConfigProvider locale={zhCN} theme={{token:{colorPrimary:'#3868df',borderRadius:9,fontFamily:'ChatTodoCJK, system-ui, sans-serif'}}}>
      <div className={`app ${sidebar?'sidebar-open':''} ${chatOpen?'chat-open':''}`} style={{'--chat-width':`${chatWidth}px`}}>
        <header className="header">
          <button className="icon menu" onClick={()=>setSidebar(!sidebar)} aria-label="画布列表">☰</button>
          <div className="brand"><span>✳</span><strong>ChatTodo</strong></div>
          <div className="header-spacer"/>
          <span className="user-email">{email}</span>
          <button className="quiet" disabled={locked} onClick={logout}>退出</button>
          <button className="quiet" onClick={()=>setChatOpen(!chatOpen)}>{chatOpen?'收起对话':'打开对话'}</button>
        </header>
        <div className="workspace">
          <aside className="sidebar">
            <div className="sidebar-head"><span>画布</span><button disabled={locked} onClick={openNew} aria-label="新建画布">＋</button></div>
            <div className="board-list">
              {boards.map(item=><button key={item.id} disabled={locked} className={item.id===board?.id?'active':''} onClick={()=>loadBoard(item.id)}><span>◇</span><strong>{item.title}</strong></button>)}
            </div>
            <div className="sidebar-foot">
              <button disabled={locked} onClick={chooseImport}>导入 JSON</button>
              <input id="import-file" type="file" accept="application/json,.json" hidden onChange={event=>{importBoard(event.target.files?.[0]);event.target.value='';}}/>
              <a href="./assets/THIRD_PARTY_NOTICES.txt" target="_blank">开源许可</a>
            </div>
          </aside>
          {sidebar&&<button className="scrim" aria-label="关闭画布列表" onClick={()=>setSidebar(false)}/>}
          <main className="canvas">
            <div className="canvas-head">
              <div><span className="eyebrow">SimpleMindMap · 工作画布</span><h1>{board?.title||'画布'}</h1></div>
              <span className={`save ${saveState}`}>{statusText[saveState]}</span>
            </div>
            <div className="toolbar">
              <button disabled={locked||!board||!rootId} onClick={()=>mapApi.current?.addChild()}>＋ 子节点 <kbd>Tab</kbd></button>
              <button disabled={locked||!board||!rootId} onClick={()=>mapApi.current?.addSibling()}>同级 <kbd>Enter</kbd></button>
              <span/>
              <button disabled={locked||!board} onClick={undo}>↶ 撤销</button>
              <button disabled={locked||!historyController.canRedo(board)} onClick={redo}>↷ 重做</button>
              <span/>
              <button disabled={!selectedNode||locked} onClick={openDetail}>正文 / 状态</button>
              {roots.length>1&&<Select aria-label="根节点" value={rootId} onChange={switchRoot} options={roots.map(root=>({value:root.id,label:root.title}))}/>} 
              <Select aria-label="布局" disabled={locked||!presentationQueue.current} value={layout} onChange={changeLayout} options={layouts.map(([value,label])=>({value,label}))}/>
              <i/>
              <button onClick={()=>mapApi.current?.fit()}>适应</button>
              <button onClick={showHistory} disabled={locked||!board}>历史</button>
              <button onClick={exportBoard} disabled={locked||!board}>导出</button>
              <button className="danger" onClick={deleteBoard} disabled={locked||!board}>删除</button>
            </div>
            {error&&<div className="error-banner" role="alert">
              <span>{error}</span>
              <div>
                {(semantic.current?.unresolved||historyController.unresolved||unknownChat.current)&&<button onClick={retryUnknown}>重试原请求</button>}
                {unknownOperation.current&&<button onClick={reconcileOperation}>核对画布列表</button>}
                {saveState==='error'&&!semantic.current?.unresolved&&<button onClick={retryConfirmed}>修正后重试</button>}
                {saveState==='error'&&!semantic.current?.unresolved&&<button onClick={discardLocal}>放弃本地修改</button>}
                {(viewQueue.current?.error||presentationQueue.current?.error)&&<button onClick={retryAux}>重试视图 / 布局</button>}
                <button onClick={refresh} disabled={!board}>读取当前状态</button>
                <button onClick={()=>setError('')} aria-label="关闭">×</button>
              </div>
            </div>}
            <div className="map-surface">
              {board&&rootId?<MapEditor board={board} rootId={rootId} layout={layout} disabled={locked} onNodes={onNodes} onSelect={setSelected} onView={onView} onUndo={undo} onRedo={redo} apiRef={mapApi}/>:board?<div className="empty"><h2>空画布</h2><p>当前没有持久化节点。</p><button className="primary" onClick={addCenter}>添加中心节点</button><button onClick={undo}>撤销</button></div>:<div className="empty"><h2>从一个想法开始</h2><button className="primary" onClick={openNew}>新建画布</button></div>}
            </div>
            <div className="canvas-foot">
              <span>{board?.nodes.length||0} 个节点{roots.length>1?` · ${roots.length} 个根，正在编辑所选分支`:''}</span>
              <span>点击选择 · 双击或 F2 编辑 · 拖动调整层级</span>
              <div><button onClick={()=>mapApi.current?.zoomOut()}>−</button><button onClick={()=>mapApi.current?.zoomIn()}>＋</button></div>
            </div>
          </main>
          <div className="resizer" onPointerDown={resize}/>
          <aside className="chat-pane">
            <div className="chat-head"><div><span className="eyebrow">Ant Design X</span><h2>对话</h2></div><button className="icon mobile-close" onClick={()=>setChatOpen(false)}>×</button></div>
            <Chat key={board?.id||'none'} boardKey={board?.id||'none'} messages={messages} busy={busy} ready={Boolean(board)} onSend={send} onApply={applyProposal} context={selectedNode?.title||'整个画布'} onClear={selected?()=>setSelected(null):null} initialDraft={chatDrafts.current.get(board?.id)} onDraftChange={value=>chatDrafts.current.set(board?.id,value)}/>
            <div className="chat-foot">{settings?.configured?'模型已配置':'模型未配置'} · 完整响应</div>
          </aside>
        </div>
        <Modal open={dialog?.kind==='new'} title="新建画布" onCancel={()=>{if(!busy)setDialog(null);}} onOk={createBoard} confirmLoading={busy} okButtonProps={{disabled:Boolean(unknownOperation.current)}} okText="创建" cancelText="取消">
          <Input autoFocus maxLength={200} disabled={busy||Boolean(unknownOperation.current)} value={dialog?.value||''} onChange={event=>setDialog({...dialog,value:event.target.value})} onPressEnter={createBoard}/>
          {unknownOperation.current&&<p className="form-error" role="alert">创建结果尚未确认。请关闭窗口后使用“核对画布列表”，不要重复提交。</p>}
        </Modal>
        <Modal open={dialog?.kind==='history'} title="变更历史" footer={null} onCancel={()=>setDialog(null)}>
          <div className="history-list">{dialog?.changes?.length?dialog.changes.map((change,index)=><article key={change.id||index}><strong>{change.summary||change.kind||'画布变更'}</strong><small>{change.created_at||''}</small></article>):<p>暂无历史记录</p>}</div>
        </Modal>
        <Modal open={Boolean(detail)} title={detail?.recovered?'恢复的正文草稿':selectedNode?.title||'节点正文'} onCancel={closeDetail} onOk={detail?.recovered?undefined:saveDetail} okButtonProps={{style:detail?.recovered?{display:'none'}:{}}} okText="保存" cancelText={detail?.recovered?'关闭':'取消'}>
          <div className="detail-editor">
            {detail?.recovered&&<p className="draft-warning">原节点已不存在。请复制需要保留的内容。</p>}
            <label>状态<Select disabled={detail?.recovered} value={detail?.values.status} onChange={status=>updateDetail({status})} options={statusOptions}/></label>
            <label>Markdown 正文<Input.TextArea value={detail?.values.body} autoSize={{minRows:9,maxRows:16}} onChange={event=>updateDetail({body:event.target.value})}/></label>
          </div>
        </Modal>
      </div>
    </ConfigProvider>
  );
}
