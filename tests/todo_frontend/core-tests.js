/* 在真实浏览器 DOM 中运行；不连接模型或生产服务。 */
window.runCoreTests = async function () {
  const results = [];
  function test(name, fn) { results.push(Promise.resolve().then(fn).then(() => ({name, ok:true}), e => ({name, ok:false, error:e.message}))); }
  function equal(a,b) { if (JSON.stringify(a)!==JSON.stringify(b)) throw new Error(JSON.stringify({actual:a,expected:b})); }
  const C = window.TodoCore;
  test('核心接口存在', () => { if (!C) throw new Error('尚未实现 TodoCore'); });
  test('折叠后代而非折叠节点本身', () => {
    const nodes=[{id:'a',parent_id:null},{id:'b',parent_id:'a'},{id:'c',parent_id:'b'},{id:'d',parent_id:null}];
    equal(C.visibleNodes(nodes,['a']).map(n=>n.id),['a','d']);
    equal([...C.descendants(nodes,'a')].sort(),['b','c']);
  });
  test('非法环也不能让可见性计算死循环', () => {
    equal(C.visibleNodes([{id:'a',parent_id:'b'},{id:'b',parent_id:'a'}],[]).length,2);
  });
  test('缩放锚点保持不动', () => {
    const v=C.zoomAt({pan:{x:20,y:30},zoom:1},2,{x:120,y:130});
    equal(v,{pan:{x:-80,y:-70},zoom:2});
  });
  test('自动布局确定且不修改已有位置', () => {
    const b={nodes:[{id:'a',parent_id:null,order:0},{id:'b',parent_id:'a',order:0}],view:{pan:{x:0,y:0},zoom:1,positions:{a:{x:9,y:20}},collapsed:[]}};
    const v=C.normalizeView(b); equal(v.positions.a,{x:9,y:20});
    if (!Number.isFinite(v.positions.b.x)) throw new Error('缺少新增节点位置');
    equal(b.view.positions.b,undefined);
  });
  test('Markdown 保留表格列表代码，去掉脚本和危险链接', () => {
    const host=document.createElement('div');
    C.renderMarkdown(host,'# 标题\n\n- [x] 完成\n\n**粗体** [安全](https://example.org) [危险](javascript:alert(1))\n\n|甲|乙|\n|-|-|\n|1|2|\n\n```js\n<a>\n```\n\n<img src=x onerror=alert(1)><script>alert(1)</script><svg onload=alert(1)>');
    if(!host.querySelector('h1')||!host.querySelector('table')||!host.querySelector('pre code')||!host.querySelector('strong')) throw new Error('不是完整 Markdown');
    if(host.querySelector('script,svg,img,[onerror],[onload],a[href^="javascript:"]')) throw new Error('不安全 Markdown');
    equal(host.querySelector('a[href^="https:"]').rel,'noopener noreferrer');
  });
  test('同源写操作 CSRF 与请求体固定', async () => {
    let seen; const api=new C.API(()=> 'csrf-test',()=>{},async(url,init)=>{seen={url,init};return new Response('{"ok":true}',{status:200});});
    await api.request('/api/boards','POST',{title:'中文'});
    equal(seen.init.credentials,'same-origin'); equal(seen.init.headers['X-CSRF-Token'],'csrf-test'); equal(JSON.parse(seen.init.body),{title:'中文'});
    await api.request('/api/login','POST',{email:'test@example.invalid',password:'test-only'});
    equal(seen.init.headers['X-CSRF-Token'],undefined);
  });
  test('409 与 401 保留结构化错误', async () => {
    let expired=0;
    for (const status of [409,401]) {
      const api=new C.API(()=>'',()=>expired++,async()=>new Response(JSON.stringify({error:{code:'conflict',message:'版本不一致'}}),{status}));
      try { await api.request('/api/boards/x'); throw new Error('未拒绝错误'); } catch(e) { equal(e.status,status); equal(e.message,'版本不一致'); }
    } equal(expired,1);
  });
  test('视图串行持久化，拖动期间响应不能吃掉新位置', async () => {
    const calls=[]; let release;
    const saver=new C.ViewSaver(async(id,view)=> {calls.push({id,view});if(calls.length===1)await new Promise(r=>release=r);return {view,view_revision:calls.length};},()=>{},10000);
    saver.schedule('a',{zoom:1}); const first=saver.flush('a');
    await new Promise(r=>setTimeout(r,0)); saver.schedule('a',{zoom:2}); release(); await first;
    equal(calls,[{id:'a',view:{zoom:1}},{id:'a',view:{zoom:2}}]); equal(saver.hasPending(),false);
  });
  test('视图失败保留队列，显式重试才继续', async () => {
    let count=0;
    const saver=new C.ViewSaver(async()=>{if(++count===1)throw new Error('离线');return {view_revision:1};},()=>{},10000);
    saver.schedule('a',{zoom:1}); await saver.flush('a').catch(()=>{}); equal(saver.hasPending(),true);
    await saver.flush('a'); equal(saver.hasPending(),false);
  });
  test('变更只标记真实新增或修改的节点',()=>{
    equal(C.changedIds([{id:'a',title:'前'},{id:'b',title:'相同'}],[{id:'a',title:'后'},{id:'b',title:'相同'},{id:'c'}]),['a','c']);
  });
  return Promise.all(results);
};
