const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const base=path.resolve(__dirname,'../../src/chatsite/todo_static');
const env={window:{},structuredClone,crypto:require('node:crypto').webcrypto,setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync(path.join(base,'core.js'),'utf8'),env);
const core=env.window.TodoCore;
const {Controller}=require(path.join(base,'app.js'));

test('pinch keeps the world anchor beneath the translated two-finger center',()=>{
 assert.equal(typeof core.pinchView,'function');
 const start={pan:{x:10,y:20},zoom:1};
 const from=[{x:100,y:100},{x:200,y:100}],to=[{x:80,y:120},{x:220,y:120}];
 const next=core.pinchView(start,from,to);
 assert.ok(next.zoom>start.zoom);
 for(const axis of ['x','y']) {
  const initial=(from[0][axis]+from[1][axis])/2,current=(to[0][axis]+to[1][axis])/2;
  assert.ok(Math.abs((initial-start.pan[axis])/start.zoom-(current-next.pan[axis])/next.zoom)<1e-9);
 }
});
test('pinch clamps supported zoom and tolerates coincident touch points',()=>{
 assert.equal(typeof core.pinchView,'function');
 const view={pan:{x:0,y:0},zoom:1};
 const next=core.pinchView(view,[{x:1,y:1},{x:2,y:1}],[{x:1,y:1},{x:200,y:1}]);
 assert.equal(next.zoom,2.5);
 const zero=core.pinchView(view,[{x:1,y:1},{x:1,y:1}],[{x:1,y:1},{x:1,y:1}]);
 assert.ok(Number.isFinite(zero.zoom)&&Number.isFinite(zero.pan.x));
});
test('two fingers cancel an accidental node drag and never open its editor',()=>{
 const canvas={getBoundingClientRect:()=>({left:0,top:0,width:500,height:700}),setPointerCapture(){}};
 const card={dataset:{id:'n'},setPointerCapture(){}};
 const target={closest(selector){return selector==='.card'?card:null;}};
 const c=new Controller({core,doc:{getElementById:()=>canvas},win:{},api:{}});
 c.board={id:'a',revision:0,nodes:[{id:'n',title:'idea',parent_id:null,body:'',order:0,status:'pending'}]};
 c.view={pan:{x:0,y:0},zoom:1,positions:{n:{x:10,y:10}},collapsed:[]};
 c.renderBoard=()=>{};let saves=0,edits=0;c.scheduleView=()=>saves++;c.selectNode=async()=>edits++;
 const event=(id,x,y)=>({pointerId:id,pointerType:'touch',button:0,clientX:x,clientY:y,target,preventDefault(){}});
 c.pointerDown(event(1,100,100));c.pointerMove(event(1,105,100));
 c.pointerDown(event(2,200,100));c.pointerMove(event(2,260,130));
 assert.ok(c.view.zoom>1);assert.equal(c.view.positions.n.x,10);
 c.pointerUp(event(2,260,130));c.pointerUp(event(1,105,100));
 assert.equal(edits,0);assert.ok(saves>=1);assert.equal(c.pinch,null);assert.equal(c.touches.size,0);
});
