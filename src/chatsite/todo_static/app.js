/* ChatTodo browser controller. Business data is always read from the same-origin API. */
(() => {
  "use strict";

  const ROOT = typeof window !== "undefined" ? window : globalThis;
  const editable = node => ({title:String(node?.title || ""), status:node?.status || "pending", body:String(node?.body || "")});
  const draftPatch = draft => {
    const fields = {};
    for (const key of ["title", "status", "body"]) if (draft?.values?.[key] !== draft?.base?.[key]) fields[key] = draft.values[key];
    return fields;
  };
  const isDirty = draft => Object.keys(draftPatch(draft)).length > 0;
  const parentChoices = (core, nodes, id) => {
    const forbidden = core.descendants(nodes, id); forbidden.add(id);
    return nodes.filter(node => !forbidden.has(node.id));
  };

  class Controller {
    constructor({core, doc, win, api} = {}) {
      this.core = core || ROOT.TodoCore;
      this.doc = doc || ROOT.document;
      this.win = win || ROOT;
      this.csrf = "";
      this.api = api || new this.core.API(() => this.csrf, () => this.expire());
      this.boards = [];
      this.board = null;
      this.view = null;
      this.messages = [];
      this.settings = null;
      this.selectedId = null;
      this.draft = null;
      this.editing = false;
      this.epoch = 0;
      this.mutating = false;
      this.chatPending = false;
      this.pendingMessage = null;
      this.conflict = null;
      this.changed = new Set();
      this.drag = null;
      this.detailDrag = null;
      this.authenticated = false;
      this.modalResolve = null;
      this.viewSaver = new this.core.ViewSaver(
        (id, view) => this.api.request(`/api/boards/${encodeURIComponent(id)}/view`, "PATCH", {view}),
        (id, state, result) => this.viewSaved(id, state, result)
      );
    }

    el(id) { return this.doc.getElementById(id); }
    capture() { return this.board ? {boardId:this.board.id, epoch:this.epoch} : null; }
    current(token) { return !!token && !!this.board && token.boardId === this.board.id && token.epoch === this.epoch; }
    node(id=this.selectedId) { return this.board?.nodes.find(item => item.id === id) || null; }
    notice(message) {
      const host = this.el("toast"); if (!host) return;
      host.textContent = message; host.classList.add("show");
      clearTimeout(this.toastTimer); this.toastTimer = setTimeout(() => host.classList.remove("show"), 2600);
    }
    setError(id, error) {
      const host=this.el(id); if (!host) return;
      host.textContent = error ? (error.message || String(error)) : ""; host.hidden = !error;
    }
    status(text) { const host=this.el("save-status"); if (host) host.textContent=text; }

    async start() {
      this.bind();
      try {
        const session=await this.api.request("/api/session");
        await this.enter(session);
      } catch (error) {
        if (error.status !== 401) this.setError("login-error", error);
        this.showLogin();
      }
    }
    showLogin() {
      this.authenticated=false;
      const login=this.el("login-screen"), app=this.el("app");
      if(login) login.hidden=false; if(app) app.hidden=true;
    }
    async enter(session) {
      this.authenticated=true; this.csrf=session.csrf_token || "";
      this.el("login-screen").hidden=true; this.el("app").hidden=false;
      this.el("user-email").textContent=session.email || "";
      this.setError("login-error", null);
      const [listed, settings]=await Promise.all([this.api.request("/api/boards"),this.api.request("/api/settings")]);
      this.boards=listed.boards || []; this.settings=settings; this.renderBoardList(); this.renderScope();
      if(this.board && this.boards.some(b=>b.id===this.board.id)) {
        await this.loadBoard(this.board.id, {preserveDraft:true});
      } else if(this.boards.length) await this.loadBoard(this.boards[0].id);
      else { this.board=null;this.view=null;this.renderAll();this.status("暂无任务树"); }
    }
    expire() {
      this.showLogin();
      this.setError("login-error", new Error("会话已过期。重新登录后可继续，未保存内容仍保留。"));
    }
    async login(event) {
      event?.preventDefault(); const password=this.el("login-password");
      try {
        const session=await this.api.request("/api/login","POST",{email:this.el("login-email").value,password:password.value});
        password.value=""; await this.enter(session);
      } catch(error) { password.value=""; this.setError("login-error",error); }
    }
    async logout() {
      if (!await this.protectDraft("退出前有未保存的节点内容，确定放弃吗？")) return;
      try { await this.viewSaver.flush(); await this.api.request("/api/logout","POST"); }
      catch(error) { if(error.status!==401){this.setError("global-error",error);return;} }
      this.board=null;this.view=null;this.messages=[];this.csrf="";this.showLogin();
    }

    async loadBoard(id, options={}) {
      if(this.board?.id===id && !options.force) return;
      if(!options.preserveDraft && !options.discardApproved && !await this.protectDraft("切换任务树会放弃未保存的节点内容，确定继续吗？")) {this.renderBoardList();return;}
      const prior=this.board?.id;
      try {
        if(prior) await this.viewSaver.flush(prior);
        const data=await this.api.request(`/api/boards/${encodeURIComponent(id)}`);
        this.epoch++; this.board=data.board; this.view=this.core.normalizeView(this.board);
        this.selectedId=options.preserveDraft && this.draft?.boardId===id ? this.draft.nodeId : null;
        if(!options.preserveDraft || this.draft?.boardId!==id) {this.draft=null;this.editing=false;}
        this.conflict=null;this.changed.clear();this.renderAll(); await this.loadMessages();
      } catch(error) { this.setError("global-error",error); }
    }
    async refreshBoard() {
      if(!this.board)return; const id=this.board.id, token=this.capture();
      try {const data=await this.api.request(`/api/boards/${encodeURIComponent(id)}`);if(this.current(token)){this.board=data.board;this.view=this.core.normalizeView(this.board);this.conflict=null;this.renderAll();}}
      catch(error){this.setError("global-error",error);}
    }
    acceptBoard(next, token, options={}) {
      if(!this.current(token) || !next || next.id!==this.board.id || next.revision<=this.board.revision) return false;
      const prior=this.board, oldView=this.view;
      this.board=next;
      const normalized=this.core.normalizeView(next);
      if(oldView) normalized.pan=oldView.pan, normalized.zoom=oldView.zoom, normalized.positions={...normalized.positions,...oldView.positions}, normalized.collapsed=[...oldView.collapsed];
      this.view=normalized;
      if(options.highlight) {this.changed=new Set(this.core.changedIds(prior.nodes,next.nodes));setTimeout(()=>{this.changed.clear();this.renderBoard();},1800);}
      if(this.selectedId && !this.node()) {this.selectedId=null;this.draft=null;this.editing=false;}
      this.renderAll(); return true;
    }

    renderAll() { this.renderBoardList();this.renderBoard();this.renderDetail();this.renderControls();this.renderScope();this.renderConflict();this.renderSaveStatus(); }
    renderBoardList() {
      const select=this.el("board-select");if(!select)return;select.replaceChildren();
      for(const board of this.boards){const option=this.doc.createElement("option");option.value=board.id;option.textContent=board.title;option.selected=board.id===this.board?.id;select.append(option);}
      select.disabled=!this.boards.length;
    }
    renderControls() {
      for(const id of ["add-button","undo","history","export-board","delete-board"]){const button=this.el(id);if(button)button.disabled=!this.board||this.mutating;}
      const send=this.el("send-chat");if(send)send.disabled=!this.board||this.chatPending||!this.settings?.configured;
    }
    renderSaveStatus() {
      if(!this.board)return;
      this.status(this.viewSaver.hasPending(this.board.id)?"视图待保存":this.mutating?"正在保存…":`已同步 · 版本 ${this.board.revision}`);
    }
    viewSaved(id,state,result) {
      if(this.board?.id===id && result?.view_revision!=null)this.board.view_revision=result.view_revision;
      if(this.board?.id===id)this.status(state==="error"?"视图保存失败，可继续操作":state==="saving"?"正在保存视图…":state==="pending"?"视图待保存":"视图已保存");
    }
    renderBoard() {
      const host=this.el("nodes"), edges=this.el("edges"), scene=this.el("scene");if(!host||!edges||!scene)return;
      host.replaceChildren();edges.replaceChildren();
      this.el("canvas-title").textContent=this.board?.title || "任务树";
      this.el("canvas-empty").hidden=!!this.board?.nodes.length;
      if(!this.board||!this.view){scene.style.transform="";return;}
      scene.style.transformOrigin="0 0";scene.style.transform=`translate(${this.view.pan.x}px, ${this.view.pan.y}px) scale(${this.view.zoom})`;
      this.el("zoom-label").textContent=`${Math.round(this.view.zoom*100)}%`;
      const visible=this.core.visibleNodes(this.board.nodes,this.view.collapsed), ids=new Set(visible.map(n=>n.id));
      const children=new Map();for(const n of this.board.nodes)children.set(n.parent_id,(children.get(n.parent_id)||0)+1);
      for(const node of visible){
        const p=this.view.positions[node.id]; if(!p)continue;
        const card=this.doc.createElement("article");card.className="card";card.dataset.id=node.id;card.dataset.status=node.status;card.tabIndex=0;
        card.style.left=`${p.x}px`;card.style.top=`${p.y}px`;
        if(node.id===this.selectedId)card.classList.add("selected");if(this.changed.has(node.id))card.classList.add("changed");
        const strip=this.doc.createElement("span");strip.className="strip";
        const content=this.doc.createElement("div");content.className="card-content";
        const title=this.doc.createElement("div");title.className="node-title";title.textContent=node.title || "未命名任务";
        const subtitle=this.doc.createElement("div");subtitle.className="node-subtitle";subtitle.textContent=(node.body||"").replace(/\s+/g," ").trim() || "暂无说明";
        const meta=this.doc.createElement("div");meta.className="node-meta";
        const status=this.doc.createElement("span");status.className="status";status.textContent=this.core.statuses[node.status]||node.status;
        const count=this.doc.createElement("span");count.textContent=`${children.get(node.id)||0} 个子任务`;
        meta.append(status,count);content.append(title,subtitle,meta);card.append(strip,content);
        if(children.get(node.id)) {const fold=this.doc.createElement("button");fold.type="button";fold.className="fold";fold.dataset.action="fold";fold.textContent=this.view.collapsed.includes(node.id)?"＋":"−";fold.title="展开或折叠子任务";card.append(fold);}
        host.append(card);
      }
      const ns="http://www.w3.org/2000/svg";
      for(const node of visible){if(!node.parent_id||!ids.has(node.parent_id))continue;const a=this.view.positions[node.parent_id],b=this.view.positions[node.id];if(!a||!b)continue;
        const path=this.doc.createElementNS(ns,"path"), x1=a.x+230,y1=a.y+52,x2=b.x,y2=b.y+52,m=(x1+x2)/2;
        path.setAttribute("d",`M ${x1} ${y1} C ${m} ${y1}, ${m} ${y2}, ${x2} ${y2}`);if(node.id===this.selectedId||node.parent_id===this.selectedId)path.classList.add("selected");edges.append(path);
      }
    }

    selectNode(id) {
      if(id===this.selectedId)return;
      this.protectDraft("打开其他节点会放弃未保存内容，确定继续吗？").then(ok=>{if(!ok)return;this.selectedId=id;this.editing=false;this.makeDraft();this.renderAll();});
    }
    makeDraft() {const node=this.node();this.draft=node?{boardId:this.board.id,nodeId:node.id,base:editable(node),values:editable(node),baseRevision:this.board.revision}:null;}
    syncDraft() {if(!this.draft)return;this.draft.values={title:this.el("node-title-input").value,status:this.el("node-status-input").value,body:this.el("node-body-input").value};}
    renderDetail() {
      const panel=this.el("detail"),node=this.node();if(!panel)return;
      panel.classList.toggle("open",!!node);if(!node)return;
      if(!this.draft||this.draft.nodeId!==node.id)this.makeDraft();
      this.el("detail-title").textContent=this.draft.values.title||"未命名任务";
      const badge=this.el("detail-status");badge.dataset.status=this.draft.values.status;badge.textContent=this.core.statuses[this.draft.values.status]||this.draft.values.status;
      this.el("node-title-input").value=this.draft.values.title;this.el("node-status-input").value=this.draft.values.status;this.el("node-body-input").value=this.draft.values.body;
      this.core.renderMarkdown(this.el("node-preview"),this.draft.values.body);
      this.showTab(this.editing?"edit":"preview",false);
    }
    showTab(tab, render=true) {this.editing=tab==="edit";this.el("preview-panel").hidden=this.editing;this.el("edit-panel").hidden=!this.editing;for(const name of ["preview","edit"]){const b=this.el(`tab-${name}`),on=name===tab;b.classList.toggle("active",on);b.setAttribute("aria-selected",String(on));}if(render)this.renderDetail();}
    async protectDraft(message) {this.syncDraft();return !isDirty(this.draft)||await this.confirm("未保存的编辑",message,"放弃编辑");}
    async closeDetail() {if(!await this.protectDraft("关闭窗口会放弃未保存内容，确定继续吗？"))return;this.selectedId=null;this.draft=null;this.editing=false;this.renderAll();}
    async saveNode() {this.syncDraft();if(!this.draft||!isDirty(this.draft)){this.notice("没有需要保存的修改");return;}if(!this.draft.values.title.trim()){this.setError("global-error",new Error("标题不能为空"));return;}
      const patch=draftPatch(this.draft), id=this.draft.nodeId;await this.mutate([{op:"update",id,fields:patch}],{revision:this.draft.baseRevision,onSuccess:()=>{const node=this.node(id);if(node){this.draft={boardId:this.board.id,nodeId:id,base:editable(node),values:editable(node),baseRevision:this.board.revision};}}});
    }
    async addNode(parentId=this.selectedId) {if(!this.board)return;if(!await this.protectDraft("新建节点会关闭当前编辑，确定放弃未保存内容吗？"))return;const id=this.core.uuid(),siblings=this.board.nodes.filter(n=>n.parent_id===(parentId||null));const node={id,parent_id:parentId||null,title:"新任务",status:"pending",body:"",order:siblings.length};
      const result=await this.mutate([{op:"create",node}],{onSuccess:()=>{this.selectedId=id;this.makeDraft();this.editing=true;this.renderAll();}});return result;
    }
    async moveNode() {const node=this.node();if(!node)return;const choices=parentChoices(this.core,this.board.nodes,node.id);const rows=[{value:"",label:"顶层"},...choices.map(n=>({value:n.id,label:n.title||"未命名任务"}))];const value=await this.choose("移动节点","选择新的父节点",rows,node.parent_id||"");if(value===null||value===(node.parent_id||""))return;const siblings=this.board.nodes.filter(n=>n.parent_id===(value||null)&&n.id!==node.id);await this.mutate([{op:"move",id:node.id,parent_id:value||null,order:siblings.length}]);}
    async deleteNode() {const node=this.node();if(!node)return;const count=this.core.descendants(this.board.nodes,node.id).size;if(!await this.confirm("删除节点",`将删除“${node.title}”及 ${count} 个后代。此操作需要明确确认。`,"确认删除"))return;await this.mutate([{op:"delete",id:node.id}],{confirm:true,onSuccess:()=>{this.selectedId=null;this.draft=null;}});}

    async mutate(operations, options={}) {
      if(!this.board||this.mutating)return null;const token=this.capture(), revision=options.revision??this.board.revision;
      this.mutating=true;this.renderControls();this.renderSaveStatus();
      const retry=()=>this.mutate(operations,{...options,revision:this.board.revision});
      try {const result=await this.api.request(`/api/boards/${encodeURIComponent(token.boardId)}`,"PATCH",{revision,request_id:this.core.uuid(),operations,confirm_destructive:!!options.confirm});
        if(this.current(token)){this.acceptBoard(result.board,token,{highlight:true});this.conflict=null;options.onSuccess?.(result);this.renderAll();}return result;
      } catch(error) {if(error.status===409&&this.current(token)){this.conflict={message:error.message,reapply:retry,base_revision:revision};this.renderConflict();}else this.setError("global-error",error);return null;}
      finally {this.mutating=false;this.renderControls();this.renderSaveStatus();}
    }
    renderConflict() {const panel=this.el("conflict-panel");if(!panel)return;panel.hidden=!this.conflict;this.el("conflict-message").textContent=this.conflict?.message||"";this.el("conflict-rebase").hidden=!this.conflict?.reapply;}
    async rebaseConflict() {if(!this.conflict?.reapply)return;const action=this.conflict.reapply;await this.refreshBoard();if(this.conflict===null)await action();}

    scheduleView() {if(this.board&&this.view)this.viewSaver.schedule(this.board.id,this.view);this.renderBoard();}
    zoom(delta, point) {if(!this.view)return;const canvas=this.el("canvas"),r=canvas.getBoundingClientRect(),at=point||{x:r.width/2,y:r.height/2};this.view={...this.view,...this.core.zoomAt(this.view,this.view.zoom*delta,at)};this.scheduleView();}
    fit() {if(!this.board?.nodes.length||!this.view)return;const points=this.core.visibleNodes(this.board.nodes,this.view.collapsed).map(n=>this.view.positions[n.id]).filter(Boolean);const xs=points.map(p=>p.x),ys=points.map(p=>p.y),r=this.el("canvas").getBoundingClientRect(),width=Math.max(...xs)-Math.min(...xs)+310,height=Math.max(...ys)-Math.min(...ys)+180,zoom=this.core.clamp(Math.min((r.width-80)/width,(r.height-150)/height),.2,1.25);this.view.zoom=zoom;this.view.pan={x:(r.width-width*zoom)/2-Math.min(...xs)*zoom+30,y:(r.height-height*zoom)/2-Math.min(...ys)*zoom+40};this.scheduleView();}

    async loadMessages() {if(!this.board)return;const token=this.capture();try{const data=await this.api.request(`/api/boards/${encodeURIComponent(token.boardId)}/messages`);if(this.current(token)){this.messages=data.messages||[];this.renderMessages();}}catch(error){if(this.current(token))this.setError("chat-error",error);}}
    renderScope() {const node=this.node();const scope=this.el("scope-title");if(scope)scope.textContent=node?.title||"整棵任务树";const all=this.el("scope-all");if(all)all.hidden=!node;const info=this.el("model-info");if(info)info.textContent=this.settings?(this.settings.configured?`模型：${this.settings.model} · ${this.settings.protocol}`:"模型尚未配置"):"";}
    renderMessages() {const host=this.el("messages");if(!host)return;host.replaceChildren();const all=[...this.messages];if(this.pendingMessage?.boardId===this.board?.id)all.push({role:"user",content:this.pendingMessage.content,pending:true});for(const message of all){const box=this.doc.createElement("article");box.className=`msg ${message.role==="user"?"user":"assistant"}`;const role=this.doc.createElement("div");role.className="speaker";role.textContent=message.pending?"你 · 发送中":"";if(!message.pending)role.textContent=message.role==="user"?"你":"模型";box.append(role);if(message.role==="assistant"){const body=this.doc.createElement("div");body.className="md-body";this.core.renderMarkdown(body,message.content||"");box.append(body);}else{const body=this.doc.createElement("div");body.textContent=message.content||"";box.append(body);}if(message.change)box.append(this.changeCard(message.change));if(message.proposal)box.append(this.proposalCard(message.proposal));host.append(box);}host.scrollTop=host.scrollHeight;}
    changeCard(change) {const box=this.doc.createElement("div");box.className="change-card";const title=this.doc.createElement("strong");title.textContent="变更已应用";const text=this.doc.createElement("p"),c=change.counts||{};text.textContent=`${change.summary||"任务树已更新"}（新增 ${c.created||0}、更新 ${c.updated||0}、删除 ${c.deleted||0}）`;box.append(title,text);return box;}
    proposalCard(proposal) {const box=this.doc.createElement("div");box.className="proposal-card";const title=this.doc.createElement("strong");title.textContent="高风险变更待确认";const text=this.doc.createElement("p");text.textContent=proposal.summary||"请核对后再应用";const details=this.doc.createElement("p");details.textContent=`基于版本 ${proposal.base_revision}，共 ${proposal.operations?.length||0} 项操作。`;
      const button=this.doc.createElement("button");button.type="button";button.textContent="确认并应用";button.addEventListener("click",()=>this.applyProposal(proposal,button));box.append(title,text,details,button);return box;}
    async sendChat(event) {event?.preventDefault();if(!this.board||this.chatPending||!this.settings?.configured)return;const input=this.el("chat-input"),message=input.value.trim();if(!message)return;const token=this.capture(),selected_node_id=this.selectedId,revision=this.board.revision;this.chatPending=true;this.pendingMessage={boardId:token.boardId,content:message};this.el("chat-busy").hidden=false;this.setError("chat-error",null);this.renderMessages();this.renderControls();
      try{const data=await this.api.request(`/api/boards/${encodeURIComponent(token.boardId)}/chat`,"POST",{message,selected_node_id,revision,request_id:this.core.uuid()});if(!this.current(token))return;if(input.value.trim()===message)input.value="";if(data.board)this.acceptBoard(data.board,token,{highlight:true});this.pendingMessage=null;this.messages.push({role:"user",content:message},data.message);this.renderMessages();}
      catch(error){if(this.current(token)){if(error.status===409){this.conflict={message:error.message,reapply:null,base_revision:revision};this.renderConflict();}this.setError("chat-error",error);}}
      finally{this.chatPending=false;if(this.pendingMessage?.boardId===token.boardId)this.pendingMessage=null;if(this.el("chat-busy"))this.el("chat-busy").hidden=true;this.renderMessages();this.renderControls();}
    }
    async applyProposal(proposal,button) {if(!this.board||button.disabled)return;if(!await this.confirm("应用高风险变更",`${proposal.summary||"该提案"}\n确认后才会写入任务树。`,"确认应用"))return;const token=this.capture();button.disabled=true;button.textContent="正在应用…";
      try{const data=await this.api.request(`/api/boards/${encodeURIComponent(token.boardId)}/apply`,"POST",{proposal_id:proposal.id,revision:this.board.revision,request_id:this.core.uuid(),confirm_destructive:true});if(this.current(token)){this.acceptBoard(data.board,token,{highlight:true});await this.loadMessages();this.notice("提案已应用");}}
      catch(error){if(this.current(token)){button.disabled=false;button.textContent="重试应用";if(error.status===409){this.conflict={message:error.message,reapply:null,base_revision:proposal.base_revision};this.renderConflict();}this.setError("chat-error",error);}}
    }

    async createBoard() {const title=await this.prompt("新建任务树","任务树名称","我的任务树");if(title===null)return;if(!await this.protectDraft("创建后将切换到新任务树，确定放弃未保存内容吗？"))return;try{const data=await this.api.request("/api/boards","POST",{title:title.trim()||"我的任务树"});this.boards.push(data.board);await this.loadBoard(data.board.id,{discardApproved:true});}catch(error){this.setError("global-error",error);}}
    async deleteBoard() {if(!this.board)return;if(!await this.confirm("删除任务树",`确定永久删除“${this.board.title}”吗？此操作不可撤销。`,"永久删除"))return;const id=this.board.id;try{await this.api.request(`/api/boards/${encodeURIComponent(id)}`,"DELETE",{revision:this.board.revision,confirm:true});this.viewSaver.forget(id);this.boards=this.boards.filter(b=>b.id!==id);this.board=null;this.view=null;this.draft=null;this.epoch++;this.renderAll();if(this.boards.length)await this.loadBoard(this.boards[0].id);}catch(error){this.setError("global-error",error);}}
    async undo() {if(!this.board||this.mutating)return;const token=this.capture();try{const data=await this.api.request(`/api/boards/${encodeURIComponent(token.boardId)}/undo`,"POST",{revision:this.board.revision,request_id:this.core.uuid()});if(this.current(token))this.acceptBoard(data.board,token,{highlight:true});}catch(error){if(error.status===409){this.conflict={message:error.message,reapply:null,base_revision:this.board.revision};this.renderConflict();}else this.setError("global-error",error);}}
    async history() {if(!this.board)return;try{const data=await this.api.request(`/api/boards/${encodeURIComponent(this.board.id)}/history`),content=this.doc.createElement("div");for(const change of data.changes||[]){const row=this.doc.createElement("p"),c=change.counts||{};row.textContent=`版本 ${change.revision} · ${change.summary} · 新增 ${c.created||0} / 更新 ${c.updated||0} / 删除 ${c.deleted||0}`;content.append(row);}if(!content.childNodes.length)content.textContent="暂无变更记录。";await this.dialog("变更记录",content,"关闭",false);}catch(error){this.setError("global-error",error);}}
    async exportBoard() {if(!this.board)return;try{const data=await this.api.request(`/api/boards/${encodeURIComponent(this.board.id)}/export`),blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),a=this.doc.createElement("a");a.href=url;a.download=`${this.board.title||"chattodo"}.json`;a.click();URL.revokeObjectURL(url);}catch(error){this.setError("global-error",error);}}
    async importFile(event) {const file=event.target.files?.[0];event.target.value="";if(!file)return;try{const board=JSON.parse(await file.text());if(!await this.confirm("导入为新任务树",`将“${board.title||"未命名任务树"}”导入为新任务树，不会覆盖当前内容。`,"开始导入"))return;const data=await this.api.request("/api/import","POST",{board});this.boards.push(data.board);await this.loadBoard(data.board.id);}catch(error){this.setError("global-error",error instanceof SyntaxError?new Error("JSON 文件格式无效"):error);}}

    dialog(title,content,okText="确认",cancel=true) {const modal=this.el("modal");this.el("modal-title").textContent=title;const host=this.el("modal-content");host.replaceChildren(typeof content==="string"?this.doc.createTextNode(content):content);this.el("modal-ok").textContent=okText;this.el("modal-cancel").hidden=!cancel;modal.showModal();return new Promise(resolve=>{this.modalResolve=resolve;});}
    finishDialog(value) {const modal=this.el("modal");if(modal.open)modal.close();const resolve=this.modalResolve;this.modalResolve=null;resolve?.(value);}
    confirm(title,text,ok="确认") {return this.dialog(title,text,ok,true);}
    async prompt(title,label,value="") {const wrap=this.doc.createElement("label");wrap.textContent=label;const input=this.doc.createElement("input");input.value=value;wrap.append(input);const ok=await this.dialog(title,wrap,"确认",true);return ok?input.value:null;}
    async choose(title,label,options,current) {const wrap=this.doc.createElement("label");wrap.textContent=label;const select=this.doc.createElement("select");for(const item of options){const option=this.doc.createElement("option");option.value=item.value;option.textContent=item.label;option.selected=item.value===current;select.append(option);}wrap.append(select);const ok=await this.dialog(title,wrap,"移动",true);return ok?select.value:null;}

    pointerDown(event) {if(!this.board||event.button!==0)return;const card=event.target.closest?.(".card");if(card){if(event.target.dataset.action==="fold"){event.stopPropagation();const id=card.dataset.id,pos=this.view.collapsed.indexOf(id);if(pos>=0)this.view.collapsed.splice(pos,1);else this.view.collapsed.push(id);this.scheduleView();return;}const p=this.view.positions[card.dataset.id];this.drag={kind:"node",id:card.dataset.id,pointer:event.pointerId,start:{x:event.clientX,y:event.clientY},origin:{...p},moved:false};card.setPointerCapture?.(event.pointerId);return;}if(event.target===this.el("canvas")||event.target===this.el("scene")||event.target===this.el("nodes")||event.target===this.el("edges")){this.drag={kind:"pan",pointer:event.pointerId,start:{x:event.clientX,y:event.clientY},origin:{...this.view.pan},moved:false};this.el("canvas").setPointerCapture?.(event.pointerId);}}
    pointerMove(event) {if(!this.drag||event.pointerId!==this.drag.pointer)return;const dx=event.clientX-this.drag.start.x,dy=event.clientY-this.drag.start.y;this.drag.moved=this.drag.moved||Math.hypot(dx,dy)>3;if(this.drag.kind==="pan")this.view.pan={x:this.drag.origin.x+dx,y:this.drag.origin.y+dy};else this.view.positions[this.drag.id]={x:this.drag.origin.x+dx/this.view.zoom,y:this.drag.origin.y+dy/this.view.zoom};this.renderBoard();}
    pointerUp(event) {if(!this.drag||event.pointerId!==this.drag.pointer)return;const drag=this.drag;this.drag=null;if(drag.moved)this.scheduleView();else if(drag.kind==="node")this.selectNode(drag.id);}
    pointerCancel(event) {if(!this.drag||event.pointerId!==this.drag.pointer)return;const drag=this.drag;this.drag=null;if(drag.kind==="pan")this.view.pan=drag.origin;else this.view.positions[drag.id]=drag.origin;this.renderBoard();}
    detailPointerDown(event) {if(event.target.closest?.("button"))return;const box=this.el("detail").getBoundingClientRect();this.detailDrag={pointer:event.pointerId,start:{x:event.clientX,y:event.clientY},origin:{x:box.left,y:box.top}};event.currentTarget.setPointerCapture?.(event.pointerId);}
    detailPointerMove(event) {if(!this.detailDrag||event.pointerId!==this.detailDrag.pointer)return;const p=this.detailDrag,box=this.el("detail"),canvas=this.el("canvas").getBoundingClientRect();box.style.left=`${this.core.clamp(p.origin.x+event.clientX-p.start.x-canvas.left,0,Math.max(0,canvas.width-box.offsetWidth))}px`;box.style.top=`${this.core.clamp(p.origin.y+event.clientY-p.start.y-canvas.top,0,Math.max(0,canvas.height-box.offsetHeight))}px`;}
    detailPointerEnd(event) {if(this.detailDrag?.pointer===event.pointerId)this.detailDrag=null;}

    bind() {
      const on=(id,type,fn,opts)=>this.el(id)?.addEventListener(type,fn.bind(this),opts);
      on("login-form","submit",this.login);on("logout","click",this.logout);on("board-select","change",e=>this.loadBoard(e.target.value));on("new-board","click",this.createBoard);on("delete-board","click",this.deleteBoard);on("add-button","click",()=>this.addNode());
      on("detail-close","click",this.closeDetail);on("tab-preview","click",()=>{this.syncDraft();this.showTab("preview")});on("tab-edit","click",()=>this.showTab("edit"));on("save-node","click",this.saveNode);on("move-node","click",this.moveNode);on("delete-node","click",this.deleteNode);
      for(const id of ["node-title-input","node-status-input","node-body-input"])on(id,"input",()=>{this.syncDraft();this.el("detail-title").textContent=this.draft.values.title||"未命名任务";});
      on("zoom-in","click",()=>this.zoom(1.2));on("zoom-out","click",()=>this.zoom(1/1.2));on("fit","click",this.fit);on("canvas","wheel",e=>{e.preventDefault();const r=e.currentTarget.getBoundingClientRect();this.zoom(e.deltaY<0?1.12:1/1.12,{x:e.clientX-r.left,y:e.clientY-r.top});},{passive:false});
      on("canvas","pointerdown",this.pointerDown);on("canvas","pointermove",this.pointerMove);on("canvas","pointerup",this.pointerUp);on("canvas","pointercancel",this.pointerCancel);
      on("detail-bar","pointerdown",this.detailPointerDown);on("detail-bar","pointermove",this.detailPointerMove);on("detail-bar","pointerup",this.detailPointerEnd);on("detail-bar","pointercancel",this.detailPointerEnd);
      const toggle=show=>{this.el("layout").classList.toggle("chat-hidden",!show);this.el("chat-toggle").setAttribute("aria-expanded",String(show));};on("chat-toggle","click",()=>toggle(this.el("layout").classList.contains("chat-hidden")));on("chat-hide","click",()=>toggle(false));on("detail-chat","click",()=>{toggle(true);this.el("chat-input").focus();});on("scope-all","click",async()=>{if(!await this.protectDraft("切换到全局会关闭当前编辑，确定放弃未保存内容吗？"))return;this.selectedId=null;this.draft=null;this.renderAll();});on("chat-form","submit",this.sendChat);
      on("undo","click",this.undo);on("history","click",this.history);on("export-board","click",this.exportBoard);on("import-board","click",()=>this.el("import-file").click());on("import-file","change",this.importFile);
      on("conflict-refresh","click",this.refreshBoard);on("conflict-rebase","click",this.rebaseConflict);on("modal-ok","click",()=>this.finishDialog(true));on("modal-cancel","click",()=>this.finishDialog(false));on("modal","cancel",e=>{e.preventDefault();this.finishDialog(false);});
      this.win.addEventListener?.("beforeunload",event=>{this.syncDraft();if(isDirty(this.draft)||this.el("chat-input")?.value.trim()||this.viewSaver.hasPending()){event.preventDefault();event.returnValue="";}});
      this.doc.addEventListener?.("visibilitychange",()=>{if(this.doc.visibilityState==="hidden")this.viewSaver.flush().catch(()=>{});});
    }
  }

  const exported={Controller,editable,draftPatch,isDirty,parentChoices};
  if(typeof module!=="undefined"&&module.exports)module.exports=exported;
  if(ROOT.document&&ROOT.TodoCore)new Controller({core:ROOT.TodoCore,doc:ROOT.document,win:ROOT}).start();
})();
