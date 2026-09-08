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
  const orderNodes = nodes => [...nodes].sort((a,b) => (a.order || 0) - (b.order || 0) || a.id.localeCompare(b.id));
  const nodeAddition = (nodes, targetId, direction, id) => {
    const target = nodes.find(node => node.id === targetId) || null;
    const task = {title:"新任务", status:"pending", body:""};
    if (direction === "child" || !target) {
      const parent_id = direction === "child" && target ? target.id : null;
      const siblings = orderNodes(nodes.filter(node => (node.parent_id || null) === parent_id));
      const node = {id, parent_id, ...task, order:siblings.length};
      return {node, operations:[{op:"create", node}]};
    }
    const parent_id = target.parent_id || null;
    const siblings = orderNodes(nodes.filter(node => (node.parent_id || null) === parent_id));
    const found = Math.max(0, siblings.findIndex(node => node.id === target.id));
    const insert = direction === "before" ? found : found + 1;
    const node = {id, parent_id, ...task, order:insert};
    const operations = siblings.map((sibling, index) => {
      const order = index >= insert ? index + 1 : index;
      return sibling.order === order ? null : {op:"update", id:sibling.id, fields:{order}};
    }).filter(Boolean);
    operations.push({op:"create", node});
    return {node, operations};
  };

  const nodeAdditionPositions = (nodes, view, targetId, direction, id) => {
    const positions=Object.fromEntries(Object.entries(view.positions||{}).map(([key,point])=>[key,{...point}]));
    const target=nodes.find(node=>node.id===targetId);const origin={...(positions[targetId]||{x:60,y:155})};
    const shiftColumn=(parent_id, afterOrder, amount)=>{
      for(const sibling of orderNodes(nodes.filter(node=>(node.parent_id||null)===(parent_id||null)))){
        if(sibling.order>=afterOrder&&positions[sibling.id])positions[sibling.id].y+=amount;
      }
    };
    if(direction==="child"||!target){
      const parent_id=direction==="child"&&target?target.id:null;
      const siblings=orderNodes(nodes.filter(node=>(node.parent_id||null)===parent_id));
      const last=siblings[siblings.length-1];
      const point=last&&positions[last.id]?{x:origin.x+310,y:positions[last.id].y+128}:{x:origin.x+310,y:origin.y};
      positions[id]=point;return {new:point,positions};
    }
    const siblings=orderNodes(nodes.filter(node=>(node.parent_id||null)===(target.parent_id||null)));
    const index=Math.max(0,siblings.findIndex(node=>node.id===target.id));
    const insert=direction==="before"?index:index+1;
    shiftColumn(target.parent_id,insert,128);
    const point={x:origin.x,y:origin.y+(direction==="after"?128:0)};
    positions[id]=point;return {new:point,positions};
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
      this.unresolvedWrite = null;
      this.detailOpen = false;
      this.inlineTitle = null;
      this.modalResolve = null;
      this.viewSaver = new this.core.ViewSaver(
        (id, view, view_revision) => this.api.request(`/api/boards/${encodeURIComponent(id)}/view`, "PATCH", {view,view_revision}),
        (id, state, result) => this.viewSaved(id, state, result)
      );
    }

    el(id) { return this.doc.getElementById(id); }
    capture() { return this.board ? {boardId:this.board.id, epoch:this.epoch} : null; }
    current(token) { return !!token && !!this.board && token.boardId === this.board.id && token.epoch === this.epoch; }
    node(id=this.selectedId) { return this.board?.nodes.find(item => item.id === id) || (this.draft?.recovered&&this.draft.nodeId===id?{id,...this.draft.values,parent_id:null,order:0}:null); }
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
      const wasAuthenticated=this.authenticated;
      this.showLogin();
      this.setError("login-error", wasAuthenticated?new Error("会话已过期。重新登录后可继续，未保存内容仍保留。"):null);
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
      if(this.unresolvedWrite&&this.unresolvedWrite.token?.boardId!==id){this.setError("global-error",new Error("请先核对并重试结果未知的写入，再切换任务树。"));this.renderBoardList();return;}
      if(!options.preserveDraft && !options.discardApproved && !await this.protectDraft("切换任务树会放弃未保存的节点内容，确定继续吗？")) {this.renderBoardList();return;}
      const prior=this.board?.id;
      try {
        if(prior) await this.viewSaver.flush(prior);
        const data=await this.api.request(`/api/boards/${encodeURIComponent(id)}`);
        this.epoch++; this.board=data.board; this.view=this.core.normalizeView(this.board);
        this.viewSaver.rebase(id,this.board.view_revision);
        this.selectedId=options.preserveDraft && this.draft?.boardId===id ? this.draft.nodeId : null;
        if(!options.preserveDraft || this.draft?.boardId!==id) {this.draft=null;this.editing=false;}
        this.conflict=null;this.changed.clear();this.renderAll(); await this.loadMessages();
      } catch(error) { this.setError("global-error",error); }
    }
    async refreshBoard() {
      if(!this.board)return; const id=this.board.id, token=this.capture();
      try {const data=await this.api.request(`/api/boards/${encodeURIComponent(id)}`);if(this.current(token)){if(this.selectedId&&!data.board.nodes.some(node=>node.id===this.selectedId)){if(this.draft?.nodeId===this.selectedId&&isDirty(this.draft)){this.draft={...this.draft,recovered:true};this.editing=true;this.detailOpen=true;this.inlineTitle=null;this.setError("global-error",new Error("当前节点已被删除；未保存内容已保留为只读草稿，请复制后再关闭。"));}else{this.selectedId=null;this.draft=null;this.editing=false;this.detailOpen=false;this.inlineTitle=null;}}this.board=data.board;this.view=this.core.normalizeView(this.board);this.viewSaver.rebase(id,this.board.view_revision);this.conflict=null;this.renderAll();}}
      catch(error){this.setError("global-error",error);}
    }
    acceptBoard(next, token, options={}) {
      if(!this.current(token) || !next || next.id!==this.board.id || next.revision<=this.board.revision) return false;
      const prior=this.board, oldView=this.view;
      this.board=next;
      this.board.view_revision=Math.max(next.view_revision??0,prior.view_revision??0);
      this.viewSaver.rebase(next.id,this.board.view_revision);
      const normalized=this.core.normalizeView(next);
      if(oldView) normalized.pan=oldView.pan, normalized.zoom=oldView.zoom, normalized.positions={...normalized.positions,...oldView.positions}, normalized.collapsed=[...oldView.collapsed];
      this.view=normalized;
      if(options.highlight) {this.changed=new Set(this.core.changedIds(prior.nodes,next.nodes));setTimeout(()=>{this.changed.clear();this.renderBoard();},1800);}
      if(this.selectedId && !next.nodes.some(node=>node.id===this.selectedId)) {
        if(this.draft?.nodeId===this.selectedId&&isDirty(this.draft)) {
          this.draft={...this.draft,recovered:true};this.editing=true;this.detailOpen=true;this.inlineTitle=null;
          this.setError("global-error",new Error("当前节点已被删除；未保存内容已保留为只读草稿，请复制后再关闭。"));
        } else {this.selectedId=null;this.draft=null;this.editing=false;this.detailOpen=false;this.inlineTitle=null;}
      }
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
      if(this.board?.id===id&&state==="error"&&result?.status===409){const pending=this.viewSaver.pendingView(id);this.conflict={message:"画布视图已在其他标签页更新。请先读取最新版本，再明确重试当前视图。",base_revision:this.board.view_revision,reapply:async()=>{if(!this.board||this.board.id!==id)return;this.viewSaver.rebase(id,this.board.view_revision);if(pending)this.view=pending;this.viewSaver.schedule(id,this.view,this.board.view_revision);await this.viewSaver.flush(id);this.renderAll();}};this.renderConflict();}
      if(this.board?.id===id)this.status(state==="error"?(result?.status===409?"视图冲突，等待确认重试":"视图保存失败，可继续操作"):state==="saving"?"正在保存视图…":state==="pending"?"视图待保存":"视图已保存");
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
        if(node.id===this.selectedId)card.classList.add("selected");if(this.changed.has(node.id))card.classList.add("changed");if(this.inlineTitle?.id===node.id)card.classList.add("inline-editing");
        const strip=this.doc.createElement("span");strip.className="strip";
        const content=this.doc.createElement("div");content.className="card-content";
        if(this.inlineTitle?.id===node.id){
          const input=this.doc.createElement("input");input.className="inline-title-input";input.value=this.inlineTitle.value;input.setAttribute("aria-label","编辑节点标题");
          input.addEventListener("pointerdown",event=>event.stopPropagation());input.addEventListener("click",event=>event.stopPropagation());
          input.addEventListener("input",event=>{if(this.inlineTitle?.id===node.id)this.inlineTitle.value=event.target.value;});
          input.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();this.commitTitleEdit(node.id,event.currentTarget.value).catch(error=>this.setError("global-error",error));}else if(event.key==="Escape"){event.preventDefault();this.inlineTitle=null;this.renderBoard();}});
          input.addEventListener("blur",event=>this.commitTitleEdit(node.id,event.currentTarget.value).catch(error=>this.setError("global-error",error)));
          content.append(input);
        } else {
          const title=this.doc.createElement("div");title.className="node-title";title.textContent=node.title || "未命名任务";content.append(title);
        }
        const subtitle=this.doc.createElement("div");subtitle.className="node-subtitle";subtitle.textContent=(node.body||"").replace(/\s+/g," ").trim() || "暂无说明";
        const meta=this.doc.createElement("div");meta.className="node-meta";
        const status=this.doc.createElement("span");status.className="status";status.textContent=this.core.statuses[node.status]||node.status;
        const count=this.doc.createElement("span");count.textContent=`${children.get(node.id)||0} 个子任务`;
        meta.append(status,count);content.append(subtitle,meta);card.append(strip,content);
        const detail=this.doc.createElement("button");detail.type="button";detail.className="card-detail";detail.dataset.action="detail";detail.textContent="详情";detail.title="打开 Markdown / PRD 详情";card.append(detail);
        for(const [direction,label,mark] of [["before","上方添加同级任务","＋"],["child","右侧添加子任务","＋"],["after","下方添加同级任务","＋"]]){const button=this.doc.createElement("button");button.type="button";button.className=`node-add add-${direction}`;button.dataset.action=`add-${direction}`;button.textContent=mark;button.title=label;button.setAttribute("aria-label",label);card.append(button);}
        if(children.get(node.id)) {const fold=this.doc.createElement("button");fold.type="button";fold.className="fold";fold.dataset.action="fold";fold.textContent=this.view.collapsed.includes(node.id)?"＋":"−";fold.title="展开或折叠子任务";card.append(fold);}
        host.append(card);
        if(this.inlineTitle?.id===node.id)this.win.setTimeout?.(()=>{const escaped=ROOT.CSS?.escape?ROOT.CSS.escape(node.id):node.id.replace(/[^a-zA-Z0-9_-]/g,"\\\\$&");const input=host.querySelector?.(`.card[data-id="${escaped}"] .inline-title-input`);input?.focus();input?.select();},0);
      }
      const ns="http://www.w3.org/2000/svg";
      for(const node of visible){if(!node.parent_id||!ids.has(node.parent_id))continue;const a=this.view.positions[node.parent_id],b=this.view.positions[node.id];if(!a||!b)continue;
        const path=this.doc.createElementNS(ns,"path"), x1=a.x+230,y1=a.y+52,x2=b.x,y2=b.y+52,m=(x1+x2)/2;
        path.setAttribute("d",`M ${x1} ${y1} C ${m} ${y1}, ${m} ${y2}, ${x2} ${y2}`);if(node.id===this.selectedId||node.parent_id===this.selectedId)path.classList.add("selected");edges.append(path);
      }
    }

    async ensureSelected(id) {
      if(id!==this.selectedId) {
        if(!await this.protectDraft("打开其他节点会放弃未保存内容，确定继续吗？"))return false;
        this.selectedId=id;this.detailOpen=false;this.inlineTitle=null;this.makeDraft();
      } else if(!this.draft||this.draft.nodeId!==id) this.makeDraft();
      return true;
    }
    async selectNode(id) { return this.beginTitleEdit(id); }
    async beginTitleEdit(id) {
      const node=this.board?.nodes.find(item=>item.id===id);if(!node)return false;
      if(this.detailOpen&&this.draft?.nodeId===id&&isDirty(this.draft)){if(!await this.protectDraft("开始编辑标题会关闭详情窗口，确定放弃未保存内容吗？"))return false;this.draft=null;}
      if(!await this.ensureSelected(id))return false;
      this.inlineTitle={id,value:node.title||""};this.detailOpen=false;this.editing=false;this.renderAll();return true;
    }
    async openDetail(id=this.selectedId) {
      const node=this.board?.nodes.find(item=>item.id===id);if(!node)return false;
      if(!await this.ensureSelected(id))return false;
      this.inlineTitle=null;this.detailOpen=true;this.editing=false;this.renderAll();return true;
    }
    makeDraft() {const node=this.node();this.draft=node?{boardId:this.board.id,nodeId:node.id,base:editable(node),values:editable(node),baseRevision:this.board.revision}:null;}
    syncDraft() {if(!this.draft||!this.detailOpen)return;this.draft.values={title:this.el("node-title-input").value,status:this.el("node-status-input").value,body:this.el("node-body-input").value};}
    renderDetail() {
      const panel=this.el("detail"),node=this.node();if(!panel)return;
      const open=!!node&&this.detailOpen;panel.classList.toggle("open",open);if(!open)return;
      if(!this.draft||this.draft.nodeId!==node.id)this.makeDraft();
      this.el("detail-title").textContent=this.draft.values.title||"未命名任务";
      const badge=this.el("detail-status");badge.dataset.status=this.draft.values.status;badge.textContent=this.core.statuses[this.draft.values.status]||this.draft.values.status;
      this.el("node-title-input").value=this.draft.values.title;this.el("node-status-input").value=this.draft.values.status;this.el("node-body-input").value=this.draft.values.body;
      this.core.renderMarkdown(this.el("node-preview"),this.draft.values.body);
      this.showTab(this.editing?"edit":"preview",false);
    }
    showTab(tab, render=true) {this.editing=tab==="edit";this.el("preview-panel").hidden=this.editing;this.el("edit-panel").hidden=!this.editing;for(const name of ["preview","edit"]){const b=this.el(`tab-${name}`),on=name===tab;b.classList.toggle("active",on);b.setAttribute("aria-selected",String(on));}if(render)this.renderDetail();}
    async protectDraft(message) {this.syncDraft();return !isDirty(this.draft)||await this.confirm("未保存的编辑",message,"放弃编辑");}
    async closeDetail() {if(!await this.protectDraft("关闭窗口会放弃未保存内容，确定继续吗？"))return;this.detailOpen=false;this.draft=null;this.editing=false;this.renderAll();}
    async saveNode() {this.syncDraft();if(!this.draft||!isDirty(this.draft)){this.notice("没有需要保存的修改");return;}if(!this.draft.values.title.trim()){this.setError("global-error",new Error("标题不能为空"));return;}
      if(this.draft.recovered){this.setError("global-error",new Error("原节点已删除；请先复制保留的草稿内容。"));return;}
      const patch=draftPatch(this.draft), id=this.draft.nodeId;await this.mutate([{op:"update",id,fields:patch}],{revision:this.draft.baseRevision,onSuccess:()=>{const node=this.node(id);if(node){this.draft={boardId:this.board.id,nodeId:id,base:editable(node),values:editable(node),baseRevision:this.board.revision};}}});
    }
    async commitTitleEdit(id, value) {
      if(!this.board||this.inlineTitle?.id!==id)return null;
      const title=String(value||"").trim(), node=this.board.nodes.find(item=>item.id===id);if(!node)return null;
      if(!title){this.inlineTitle={id,value};this.setError("global-error",new Error("标题不能为空"));this.renderBoard();return null;}
      this.inlineTitle=null;if(title===node.title){this.renderBoard();return null;}
      const result=await this.mutate([{op:"update",id,fields:{title}}],{revision:this.board.revision,onSuccess:()=>{if(this.draft?.nodeId===id){this.draft.base.title=title;this.draft.values.title=title;this.draft.baseRevision=this.board.revision;}}});
      if(!result)this.inlineTitle={id,value:title};this.renderAll();return result;
    }
    async addNode(parentId=this.selectedId) {return this.addNodeAt(parentId,"child");}
    async addNodeAt(targetId=this.selectedId,direction="child") {if(!this.board)return null;if(!await this.protectDraft("新建节点会关闭当前编辑，确定放弃未保存内容吗？"))return null;const id=this.core.uuid(), addition=nodeAddition(this.board.nodes,targetId,direction,id);
      const layout=nodeAdditionPositions(this.board.nodes,this.view,targetId,direction,id);
      const result=await this.mutate(addition.operations,{onSuccess:response=>{const next=this.core.normalizeView(response.board);next.pan=this.view.pan;next.zoom=this.view.zoom;next.collapsed=[...this.view.collapsed];next.positions={...next.positions,...layout.positions};this.view=next;this.selectedId=addition.node.id;this.detailOpen=false;this.inlineTitle={id:addition.node.id,value:addition.node.title};this.makeDraft();this.renderAll();this.scheduleView();}});return result;
    }
    async moveNode() {const node=this.node();if(!node)return;const choices=parentChoices(this.core,this.board.nodes,node.id);const rows=[{value:"",label:"顶层"},...choices.map(n=>({value:n.id,label:n.title||"未命名任务"}))];const value=await this.choose("移动节点","选择新的父节点",rows,node.parent_id||"");if(value===null||value===(node.parent_id||""))return;const siblings=this.board.nodes.filter(n=>n.parent_id===(value||null)&&n.id!==node.id);await this.mutate([{op:"move",id:node.id,parent_id:value||null,order:siblings.length}]);}
    async deleteNode() {const node=this.node();if(!node)return;const count=this.core.descendants(this.board.nodes,node.id).size;if(!await this.confirm("删除节点",`将删除“${node.title}”及 ${count} 个后代。此操作需要明确确认。`,"确认删除"))return;await this.mutate([{op:"delete",id:node.id}],{confirm:true,onSuccess:()=>{this.selectedId=null;this.draft=null;this.detailOpen=false;this.inlineTitle=null;}});}

    async mutate(operations, options={}) {
      if(!this.board||this.mutating)return null;
      if(this.unresolvedWrite){this.setError("global-error",new Error("上一次写入结果尚未确认，请先读取最新状态并重试原请求。"));return null;}
      const revision=options.revision??this.board.revision;
      const attempt={kind:"mutation",token:this.capture(),path:`/api/boards/${encodeURIComponent(this.board.id)}`,method:"PATCH",
        payload:{revision,request_id:this.core.uuid(),operations:this.core.copy(operations),confirm_destructive:!!options.confirm}};
      return this.submitMutation(attempt,options);
    }
    async submitMutation(attempt, options={}) {
      if(this.mutating)return null;const {token,payload}=attempt,revision=payload.revision,operations=payload.operations;
      this.mutating=true;this.renderControls();this.renderSaveStatus();
      const retry=()=>this.mutate(operations,{...options,revision:this.board.revision});
      try {const result=await this.api.request(attempt.path,attempt.method,payload);
        if(this.unresolvedWrite===attempt)this.unresolvedWrite=null;
        if(this.current(token)){this.acceptBoard(result.board,token,{highlight:true});this.conflict=null;options.onSuccess?.(result);this.renderAll();}return result;
      } catch(error) {
        const ambiguous=error.status===0||error.code==="invalid_response"||error.code==="request_pending";
        if(ambiguous){this.unresolvedWrite=attempt;this.conflict={message:"写入结果尚未确认。请读取最新状态后重试原请求；系统会复用同一 request_id。",reapply:()=>this.submitMutation(attempt,options),base_revision:revision};}
        else {if(this.unresolvedWrite===attempt)this.unresolvedWrite=null;if(error.status===409&&this.current(token))this.conflict={message:error.message,reapply:retry,base_revision:revision};}
        if(this.current(token))this.renderConflict();this.setError("global-error",error);return null;
      }
      finally {this.mutating=false;this.renderControls();this.renderSaveStatus();}
    }
    renderConflict() {const panel=this.el("conflict-panel");if(!panel)return;panel.hidden=!this.conflict;this.el("conflict-message").textContent=this.conflict?.message||"";this.el("conflict-rebase").hidden=!this.conflict?.reapply;}
    async rebaseConflict() {if(!this.conflict?.reapply)return;const action=this.conflict.reapply;await this.refreshBoard();if(this.conflict===null)await action();}

    scheduleView() {if(this.board&&this.view)this.viewSaver.schedule(this.board.id,this.view,this.board.view_revision);this.renderBoard();}
    zoom(delta, point) {if(!this.view)return;const canvas=this.el("canvas"),r=canvas.getBoundingClientRect(),at=point||{x:r.width/2,y:r.height/2};this.view={...this.view,...this.core.zoomAt(this.view,this.view.zoom*delta,at)};this.scheduleView();}
    fit() {if(!this.board?.nodes.length||!this.view)return;const points=this.core.visibleNodes(this.board.nodes,this.view.collapsed).map(n=>this.view.positions[n.id]).filter(Boolean);const xs=points.map(p=>p.x),ys=points.map(p=>p.y),r=this.el("canvas").getBoundingClientRect(),width=Math.max(...xs)-Math.min(...xs)+310,height=Math.max(...ys)-Math.min(...ys)+180,zoom=this.core.clamp(Math.min((r.width-80)/width,(r.height-150)/height),.2,1.25);this.view.zoom=zoom;this.view.pan={x:(r.width-width*zoom)/2-Math.min(...xs)*zoom+30,y:(r.height-height*zoom)/2-Math.min(...ys)*zoom+40};this.scheduleView();}

    async loadMessages() {if(!this.board)return;const token=this.capture();try{const data=await this.api.request(`/api/boards/${encodeURIComponent(token.boardId)}/messages`);if(this.current(token)){this.messages=data.messages||[];this.renderMessages();}}catch(error){if(this.current(token))this.setError("chat-error",error);}}
    renderScope() {const node=this.node();const scope=this.el("scope-title");if(scope)scope.textContent=node?.title||"整棵任务树";const all=this.el("scope-all");if(all)all.hidden=!node;const info=this.el("model-info");if(info)info.textContent=this.settings?(this.settings.configured?`模型：${this.settings.model} · ${this.settings.protocol}`:"模型尚未配置"):"";}
    renderMessages() {const host=this.el("messages");if(!host)return;host.replaceChildren();const all=[...this.messages];if(this.pendingMessage?.boardId===this.board?.id)all.push({role:"user",content:this.pendingMessage.content,pending:true});for(const message of all){const box=this.doc.createElement("article");box.className=`msg ${message.role==="user"?"user":"assistant"}`;const role=this.doc.createElement("div");role.className="speaker";role.textContent=message.pending?"你 · 发送中":"";if(!message.pending)role.textContent=message.role==="user"?"你":"模型";box.append(role);if(message.role==="assistant"){const body=this.doc.createElement("div");body.className="md-body";this.core.renderMarkdown(body,message.content||"");box.append(body);}else{const body=this.doc.createElement("div");body.textContent=message.content||"";box.append(body);}if(message.change)box.append(this.changeCard(message.change));if(message.proposal)box.append(this.proposalCard(message.proposal));host.append(box);}host.scrollTop=host.scrollHeight;}
    changeCard(change) {const box=this.doc.createElement("div");box.className="change-card";const title=this.doc.createElement("strong");title.textContent="变更已应用";const text=this.doc.createElement("p"),c=change.counts||{};text.textContent=`${change.summary||"任务树已更新"}（新增 ${c.created||0}、更新 ${c.updated||0}、删除 ${c.deleted||0}）`;box.append(title,text);return box;}
    proposalCard(proposal) {const box=this.doc.createElement("div");box.className="proposal-card";const title=this.doc.createElement("strong");title.textContent="高风险变更待确认";const text=this.doc.createElement("p");text.textContent=proposal.summary||"请核对后再应用";const details=this.doc.createElement("p");details.textContent=`基于版本 ${proposal.base_revision}，共 ${proposal.operations?.length||0} 项操作。`;
      const button=this.doc.createElement("button");button.type="button";button.textContent="确认并应用";button.addEventListener("click",()=>this.applyProposal(proposal,button));box.append(title,text,details,button);return box;}
    async sendChat(event) {event?.preventDefault();if(!this.board||this.chatPending||!this.settings?.configured)return;if(this.unresolvedWrite){this.setError("chat-error",new Error("上一次请求结果尚未确认，请先重试原请求。"));return;}const input=this.el("chat-input"),message=input.value.trim();if(!message)return;const selected_node_id=this.selectedId,revision=this.board.revision;
      const attempt={kind:"chat",token:this.capture(),path:`/api/boards/${encodeURIComponent(this.board.id)}/chat`,method:"POST",payload:{message,selected_node_id,revision,request_id:this.core.uuid()}};
      return this.submitChat(attempt);
    }
    async submitChat(attempt) {if(this.chatPending)return;const {token,payload}=attempt,{message,revision}=payload,input=this.el("chat-input");this.chatPending=true;this.pendingMessage={boardId:token.boardId,content:message};this.el("chat-busy").hidden=false;this.setError("chat-error",null);this.renderMessages();this.renderControls();
      try{const data=await this.api.request(attempt.path,attempt.method,payload);if(this.unresolvedWrite===attempt)this.unresolvedWrite=null;if(!this.current(token))return;if(input.value.trim()===message)input.value="";if(data.board)this.acceptBoard(data.board,token,{highlight:true});this.pendingMessage=null;this.conflict=null;this.messages.push({role:"user",content:message},data.message);this.renderMessages();}
      catch(error){const ambiguous=error.status===0||error.code==="invalid_response"||error.code==="request_pending";if(ambiguous){this.unresolvedWrite=attempt;this.conflict={message:"模型请求结果尚未确认。请读取最新状态后重试原请求；系统会复用同一 request_id。",reapply:()=>this.submitChat(attempt),base_revision:revision};}else{if(this.unresolvedWrite===attempt)this.unresolvedWrite=null;if(error.status===409)this.conflict={message:error.message,reapply:()=>this.sendChat(),base_revision:revision};}if(this.current(token)){this.renderConflict();this.setError("chat-error",error);}}
      finally{this.chatPending=false;if(this.pendingMessage?.boardId===token.boardId)this.pendingMessage=null;if(this.el("chat-busy"))this.el("chat-busy").hidden=true;this.renderMessages();this.renderControls();}
    }
    async applyProposal(proposal,button) {if(!this.board||button.disabled)return;this.syncDraft();const deleted=new Set();for(const op of proposal.operations||[])if(op.op==="delete"){deleted.add(op.id);for(const id of this.core.descendants(this.board.nodes,op.id))deleted.add(id);}if(isDirty(this.draft)&&deleted.has(this.draft.nodeId)&&!await this.confirm("未保存的编辑","提案会删除当前节点。应用后未保存内容将保留为只读草稿供你复制，是否继续？","应用并保留草稿"))return;if(!await this.confirm("应用高风险变更",`${proposal.summary||"该提案"}\n确认后才会写入任务树。`,"确认应用"))return;const token=this.capture();button.disabled=true;button.textContent="正在应用…";
      try{const data=await this.api.request(`/api/boards/${encodeURIComponent(token.boardId)}/apply`,"POST",{proposal_id:proposal.id,revision:this.board.revision,request_id:this.core.uuid(),confirm_destructive:true});if(this.current(token)){this.acceptBoard(data.board,token,{highlight:true});await this.loadMessages();this.notice("提案已应用");}}
      catch(error){if(this.current(token)){button.disabled=false;button.textContent="重试应用";if(error.status===409){this.conflict={message:error.message,reapply:null,base_revision:proposal.base_revision};this.renderConflict();}this.setError("chat-error",error);}}
    }

    async createBoard() {const title=await this.prompt("新建任务树","任务树名称","我的任务树");if(title===null)return;if(!await this.protectDraft("创建后将切换到新任务树，确定放弃未保存内容吗？"))return;try{const data=await this.api.request("/api/boards","POST",{title:title.trim()||"我的任务树"});this.boards.push(data.board);await this.loadBoard(data.board.id,{discardApproved:true});}catch(error){this.setError("global-error",error);}}
    async deleteBoard() {if(!this.board)return;if(!await this.confirm("删除任务树",`确定永久删除“${this.board.title}”吗？此操作不可撤销。`,"永久删除"))return;const id=this.board.id;try{const result=await this.api.request(`/api/boards/${encodeURIComponent(id)}`,"DELETE",{revision:this.board.revision,confirm:true});this.viewSaver.forget(id);this.boards=this.boards.filter(b=>b.id!==id);this.board=null;this.view=null;this.draft=null;this.epoch++;this.renderAll();if(result.cleanup_pending)this.notice(result.message||"任务树已删除，关联状态清理待重试");if(this.boards.length)await this.loadBoard(this.boards[0].id);}catch(error){this.setError("global-error",error);}}
    async undo() {if(!this.board||this.mutating)return;const token=this.capture();try{const data=await this.api.request(`/api/boards/${encodeURIComponent(token.boardId)}/undo`,"POST",{revision:this.board.revision,request_id:this.core.uuid()});if(this.current(token))this.acceptBoard(data.board,token,{highlight:true});}catch(error){if(error.status===409){this.conflict={message:error.message,reapply:null,base_revision:this.board.revision};this.renderConflict();}else this.setError("global-error",error);}}
    async history() {if(!this.board)return;try{const data=await this.api.request(`/api/boards/${encodeURIComponent(this.board.id)}/history`),content=this.doc.createElement("div");for(const change of data.changes||[]){const row=this.doc.createElement("p"),c=change.counts||{};row.textContent=`版本 ${change.revision} · ${change.summary} · 新增 ${c.created||0} / 更新 ${c.updated||0} / 删除 ${c.deleted||0}`;content.append(row);}if(!content.childNodes.length)content.textContent="暂无变更记录。";await this.dialog("变更记录",content,"关闭",false);}catch(error){this.setError("global-error",error);}}
    async exportBoard() {if(!this.board)return;try{const data=await this.api.request(`/api/boards/${encodeURIComponent(this.board.id)}/export`),blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),a=this.doc.createElement("a");a.href=url;a.download=`${this.board.title||"chattodo"}.json`;a.click();URL.revokeObjectURL(url);}catch(error){this.setError("global-error",error);}}
    async importFile(event) {const file=event.target.files?.[0];event.target.value="";if(!file)return;try{const board=JSON.parse(await file.text());if(!await this.confirm("导入为新任务树",`将“${board.title||"未命名任务树"}”导入为新任务树，不会覆盖当前内容。`,"开始导入"))return;const data=await this.api.request("/api/import","POST",{board});this.boards.push(data.board);await this.loadBoard(data.board.id);}catch(error){this.setError("global-error",error instanceof SyntaxError?new Error("JSON 文件格式无效"):error);}}

    dialog(title,content,okText="确认",cancel=true) {const modal=this.el("modal");this.el("modal-title").textContent=title;const host=this.el("modal-content");host.replaceChildren(typeof content==="string"?this.doc.createTextNode(content):content);this.el("modal-ok").textContent=okText;this.el("modal-cancel").hidden=!cancel;modal.showModal();return new Promise(resolve=>{this.modalResolve=resolve;});}
    finishDialog(value) {const modal=this.el("modal");if(modal.open)modal.close();const resolve=this.modalResolve;this.modalResolve=null;resolve?.(value);}
    confirm(title,text,ok="确认") {return this.dialog(title,text,ok,true);}
    async prompt(title,label,value="") {const wrap=this.doc.createElement("label");wrap.textContent=label;const input=this.doc.createElement("input");input.value=value;wrap.append(input);const ok=await this.dialog(title,wrap,"确认",true);return ok?input.value:null;}
    async choose(title,label,options,current) {const wrap=this.doc.createElement("label");wrap.textContent=label;const select=this.doc.createElement("select");for(const item of options){const option=this.doc.createElement("option");option.value=item.value;option.textContent=item.label;option.selected=item.value===current;select.append(option);}wrap.append(select);const ok=await this.dialog(title,wrap,"移动",true);return ok?select.value:null;}

    async nodeAction(event) {
      const button=event.target.closest?.("[data-action]"), card=event.target.closest?.(".card");if(!button||!card)return;
      event.preventDefault();event.stopPropagation();const id=card.dataset.id, action=button.dataset.action;
      if(action==="fold"){const pos=this.view.collapsed.indexOf(id);if(pos>=0)this.view.collapsed.splice(pos,1);else this.view.collapsed.push(id);this.scheduleView();return;}
      if(action==="detail"){await this.openDetail(id);return;}
      if(action?.startsWith("add-")){await this.addNodeAt(id,action.slice(4));}
    }
    pointerDown(event) {if(!this.board||event.button!==0)return;const card=event.target.closest?.(".card");if(card){if(event.target.closest?.("button,input,textarea,select"))return;const p=this.view.positions[card.dataset.id];this.drag={kind:"node",id:card.dataset.id,pointer:event.pointerId,start:{x:event.clientX,y:event.clientY},origin:{...p},moved:false};card.setPointerCapture?.(event.pointerId);return;}if(event.target===this.el("canvas")||event.target===this.el("scene")||event.target===this.el("nodes")||event.target===this.el("edges")){this.drag={kind:"pan",pointer:event.pointerId,start:{x:event.clientX,y:event.clientY},origin:{...this.view.pan},moved:false};this.el("canvas").setPointerCapture?.(event.pointerId);}}
    pointerMove(event) {if(!this.drag||event.pointerId!==this.drag.pointer)return;const dx=event.clientX-this.drag.start.x,dy=event.clientY-this.drag.start.y;this.drag.moved=this.drag.moved||Math.hypot(dx,dy)>3;if(this.drag.kind==="pan")this.view.pan={x:this.drag.origin.x+dx,y:this.drag.origin.y+dy};else this.view.positions[this.drag.id]={x:this.drag.origin.x+dx/this.view.zoom,y:this.drag.origin.y+dy/this.view.zoom};this.renderBoard();}
    pointerUp(event) {if(!this.drag||event.pointerId!==this.drag.pointer)return;const drag=this.drag;this.drag=null;if(drag.moved)this.scheduleView();else if(drag.kind==="node")this.selectNode(drag.id).catch(error=>this.setError("global-error",error));}
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
      on("nodes","click",this.nodeAction);on("canvas","pointerdown",this.pointerDown);on("canvas","pointermove",this.pointerMove);on("canvas","pointerup",this.pointerUp);on("canvas","pointercancel",this.pointerCancel);
      on("detail-bar","pointerdown",this.detailPointerDown);on("detail-bar","pointermove",this.detailPointerMove);on("detail-bar","pointerup",this.detailPointerEnd);on("detail-bar","pointercancel",this.detailPointerEnd);
      const toggle=show=>{this.el("layout").classList.toggle("chat-hidden",!show);this.el("chat-toggle").setAttribute("aria-expanded",String(show));};on("chat-toggle","click",()=>toggle(this.el("layout").classList.contains("chat-hidden")));on("chat-hide","click",()=>toggle(false));on("detail-chat","click",()=>{toggle(true);this.el("chat-input").focus();});on("scope-all","click",async()=>{if(!await this.protectDraft("切换到全局会关闭当前编辑，确定放弃未保存内容吗？"))return;this.selectedId=null;this.draft=null;this.detailOpen=false;this.inlineTitle=null;this.renderAll();});on("chat-form","submit",this.sendChat);
      on("undo","click",this.undo);on("history","click",this.history);on("export-board","click",this.exportBoard);on("import-board","click",()=>this.el("import-file").click());on("import-file","change",this.importFile);
      on("conflict-refresh","click",this.refreshBoard);on("conflict-rebase","click",this.rebaseConflict);on("modal-ok","click",()=>this.finishDialog(true));on("modal-cancel","click",()=>this.finishDialog(false));on("modal","cancel",e=>{e.preventDefault();this.finishDialog(false);});
      this.win.addEventListener?.("beforeunload",event=>{this.syncDraft();if(isDirty(this.draft)||this.el("chat-input")?.value.trim()||this.viewSaver.hasPending()||this.unresolvedWrite){event.preventDefault();event.returnValue="";}});
      this.doc.addEventListener?.("visibilitychange",()=>{if(this.doc.visibilityState==="hidden")this.viewSaver.flush().catch(()=>{});});
    }
  }

  const exported={Controller,editable,draftPatch,isDirty,parentChoices,nodeAddition,nodeAdditionPositions};
  if(typeof module!=="undefined"&&module.exports)module.exports=exported;
  if(ROOT.document&&ROOT.TodoCore)new Controller({core:ROOT.TodoCore,doc:ROOT.document,win:ROOT}).start();
})();
