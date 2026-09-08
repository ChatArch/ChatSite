/* 任务树纯逻辑、同源 API 与串行视图保存。 */
(() => {
  "use strict";
  const copy = value => structuredClone(value);
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const uuid = () => crypto.randomUUID();
  const statuses = {pending: "待开始", in_progress: "进行中", completed: "已完成", cancelled: "已取消"};
  function descendants(nodes, id) {
    const children = new Map();
    nodes.forEach(n => { if (!children.has(n.parent_id)) children.set(n.parent_id, []); children.get(n.parent_id).push(n.id); });
    const found = new Set(), queue = [...(children.get(id) || [])];
    while (queue.length) {
      const next = queue.pop();
      if (next === id || found.has(next)) continue;
      found.add(next); queue.push(...(children.get(next) || []));
    }
    return found;
  }
  function visibleNodes(nodes, collapsed) {
    const map = new Map(nodes.map(n => [n.id, n])), folds = new Set(collapsed);
    return nodes.filter(node => {
      let parent = node.parent_id; const seen = new Set([node.id]);
      while (parent && !seen.has(parent)) {
        if (folds.has(parent)) return false;
        seen.add(parent); parent = map.get(parent)?.parent_id;
      }
      return true;
    });
  }
  function normalizeView(board) {
    const raw = board.view || {}, positions = Object.create(null), ids = new Set(board.nodes.map(n => n.id));
    const finite = (v, fallback) => Number.isFinite(v) ? v : fallback;
    for (const [id, p] of Object.entries(raw.positions || {})) {
      if (ids.has(id) && Number.isFinite(p?.x) && Number.isFinite(p?.y)) positions[id] = {x:p.x, y:p.y};
    }
    const map = new Map(board.nodes.map(n => [n.id, n]));
    const children = new Map();
    for (const node of board.nodes) {
      const parent = map.has(node.parent_id) ? node.parent_id : null;
      if (!children.has(parent)) children.set(parent, []);
      children.get(parent).push(node);
    }
    for (const list of children.values()) list.sort((a,b) => (a.order || 0) - (b.order || 0) || a.id.localeCompare(b.id));
    let row = 0; const seen = new Set();
    function layout(node, depth) {
      if (seen.has(node.id)) return row * 128;
      seen.add(node.id);
      const ys = (children.get(node.id) || []).map(n => layout(n, depth+1));
      const y = ys.length ? (ys[0]+ys[ys.length-1])/2 : row++ * 128;
      positions[node.id] ||= {x:60+depth*310, y:155+y};
      return y;
    }
    (children.get(null) || []).forEach(n => layout(n, 0));
    board.nodes.forEach(n => {if (!seen.has(n.id)) layout(n, 0);});
    return {pan:{x:finite(raw.pan?.x, 0),y:finite(raw.pan?.y, 0)},zoom:clamp(finite(raw.zoom,1),.2,2.5),positions,collapsed:[...new Set(raw.collapsed || [])].filter(id => ids.has(id))};
  }
  function zoomAt(view, next, point) {
    const zoom = clamp(next,.2,2.5), ratio = zoom / view.zoom;
    return {pan:{x:point.x-(point.x-view.pan.x)*ratio,y:point.y-(point.y-view.pan.y)*ratio},zoom};
  }
  function changedIds(before, after) {
    const old = new Map(before.map(n => [n.id, JSON.stringify(n)]));
    return after.filter(n => old.get(n.id) !== JSON.stringify(n)).map(n => n.id);
  }
  function renderMarkdown(host, source) {
    // 禁止原始 HTML；Markdown 语义来自本地固定版本 parser。
    // 再以严格白名单 sanitizer 返回 DOM，任何业务文本不经 innerHTML。
    const renderer = new marked.Renderer();
    renderer.html = () => "";
    const html = marked.parse(String(source || ""), {gfm:true, breaks:false, renderer});
    const fragment = DOMPurify.sanitize(html, {
      RETURN_DOM_FRAGMENT:true,
      ALLOWED_TAGS:["p","br","h1","h2","h3","h4","h5","h6","strong","em","del","blockquote","ul","ol","li","pre","code","hr","a","table","thead","tbody","tr","th","td","input"],
      ALLOWED_ATTR:["href","title","start","type","checked","disabled","align"],
      ALLOW_DATA_ATTR:false, ALLOW_ARIA_ATTR:false,
    });
    for (const a of fragment.querySelectorAll("a")) {
      const href = a.getAttribute("href") || "";
      if (!/^(https?:\/\/|mailto:|\/(?!\/)|#)/i.test(href) || /[\u0000-\u0020\\]/.test(href)) a.removeAttribute("href");
      else {a.rel = "noopener noreferrer"; a.target = "_blank";}
    }
    for (const input of fragment.querySelectorAll("input")) {input.type="checkbox";input.disabled=true;}
    host.replaceChildren(fragment);
  }
  class APIError extends Error {
    constructor(status, code, message) {super(message);this.status=status;this.code=code;}
  }
  class API {
    constructor(token, expired, transport = (...args) => fetch(...args)) {this.token=token;this.expired=expired;this.transport=transport;}
    async request(path, method="GET", body, options={}) {
      const headers = {Accept:"application/json"};
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (method !== "GET" && path !== "/api/login") headers["X-CSRF-Token"] = this.token();
      let response;
      try {response = await this.transport(path, {method,headers,credentials: "same-origin",cache:"no-store",...(body!==undefined?{body:JSON.stringify(body)}:{}),...options});}
      catch (error) {if (error.name==="AbortError") throw error;throw new APIError(0,"network","网络连接失败。内容仍保留，请检查连接后重试。");}
      let data;
      try {data = await response.json();} catch {throw new APIError(response.status,"invalid_response","服务器返回了无法读取的响应，请稍后重试。");}
      if (!response.ok) {
        if (response.status===401) this.expired();
        throw new APIError(response.status,data.error?.code || "request_failed",data.error?.message || "请求未完成，请稍后重试。");
      }
      return data;
    }
  }
  class ViewSaver {
    constructor(save, notify, delay=550) {this.save=save;this.notify=notify;this.delay=delay;this.entries=new Map();}
    schedule(id, view, revision) {
      let entry=this.entries.get(id);
      if (!entry) {entry={seq:0,done:0,view:null,revision,timer:null,running:null,error:null};this.entries.set(id,entry);}
      else if(entry.revision==null&&revision!=null)entry.revision=revision;
      entry.view=copy(view);entry.seq++;entry.error=null;clearTimeout(entry.timer);
      entry.timer=setTimeout(()=>this.flush(id).catch(()=>{}),this.delay);this.notify(id,"pending");
    }
    hasPending(id) {return id ? this.entries.has(id) && this.entries.get(id).seq>this.entries.get(id).done : [...this.entries.values()].some(e=>e.seq>e.done);}
    async flush(id) {
      if (!id) {await Promise.all([...this.entries.keys()].map(key=>this.flush(key)));return;}
      const entry=this.entries.get(id);if(!entry)return;clearTimeout(entry.timer);
      if (entry.running) return entry.running;
      entry.running=(async()=>{
        while(entry.seq>entry.done) {
          const seq=entry.seq, view=copy(entry.view);this.notify(id,"saving");
          try {const result=await this.save(id,view,entry.revision);entry.done=seq;entry.error=null;if(result?.view_revision!=null)entry.revision=result.view_revision;this.notify(id,entry.seq===seq?"saved":"pending",result);}
          catch(error) {entry.error=error;this.notify(id,"error",error);throw error;}
        }
      })();
      try {await entry.running;} finally {entry.running=null;}
    }
    rebase(id, revision) {const entry=this.entries.get(id);if(entry)entry.revision=revision;}
    pendingView(id) {const entry=this.entries.get(id);return entry?.view?copy(entry.view):null;}
    forget(id) {const e=this.entries.get(id);if(e)clearTimeout(e.timer);this.entries.delete(id);}
  }
  window.TodoCore = {copy,clamp,uuid,statuses,descendants,visibleNodes,normalizeView,zoomAt,changedIds,renderMarkdown,API,APIError,ViewSaver};
})();
