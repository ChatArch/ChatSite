import React,{useEffect,useRef,useState} from 'react';
import MindMap from 'simple-mind-map/index.js';
import Drag from 'simple-mind-map/src/plugins/Drag.js';
import Select from 'simple-mind-map/src/plugins/Select.js';
import TouchEvent from 'simple-mind-map/src/plugins/TouchEvent.js';
import KeyboardNavigation from 'simple-mind-map/src/plugins/KeyboardNavigation.js';
import {branchOf,cleanNodes,mergeCollapsed,mergeVisibleBranch,sameNodes} from './core.mjs';

MindMap.usePlugin(Drag).usePlugin(Select).usePlugin(TouchEvent).usePlugin(KeyboardNavigation);
export const layouts=[
  ['logicalStructure','逻辑结构图'],['mindMap','左右思维导图'],['organizationStructure','组织结构图'],
  ['catalogOrganization','目录结构图'],['timeline','时间轴'],['fishbone','鱼骨图'],
];

function treeFor(nodes,collapsed,previous){
  nodes=cleanNodes(nodes);const roots=nodes.filter(n=>n.parent_id===null);if(roots.length!==1)throw new Error('当前分支必须有且只有一个根节点');
  const old=new Map();const scan=node=>{if(!node)return;old.set(node.data?.uid,node);(node.children||[]).forEach(scan);};scan(previous?.root||previous);
  const children=new Map();for(const node of nodes){const list=children.get(node.parent_id)||[];list.push(node);children.set(node.parent_id,list);}for(const list of children.values())list.sort((a,b)=>a.order-b.order||a.id.localeCompare(b.id));
  const fold=new Set(collapsed||[]),seen=new Set();const build=node=>{if(seen.has(node.id))throw new Error('节点关系包含循环');seen.add(node.id);const saved=old.get(node.id)||{};return {...saved,data:{...saved.data,uid:node.id,text:node.title,body:node.body,status:node.status,richText:false,expand:!fold.has(node.id)},children:(children.get(node.id)||[]).map(build)};};
  return build(roots[0]);
}

function flatten(data){
  const result=[];const walk=(node,parent_id=null,order=0)=>{const d=node.data||{};result.push({id:String(d.uid||''),parent_id,title:String(d.text||''),status:d.status||'pending',body:String(d.body||''),order});(node.children||[]).forEach((child,index)=>walk(child,String(d.uid||''),index));};
  if(data?.root)walk(data.root);else if(data)walk(data);return cleanNodes(result);
}

export default function MapEditor({board,rootId,layout,disabled,onNodes,onSelect,onView,onUndo,onRedo,apiRef}){
  const host=useRef(null),instance=useRef(null),latest=useRef(null),suppress=useRef(false),positions=useRef(board.view?.positions||{}),layoutTimer=useRef(null);const [error,setError]=useState('');
  latest.current={board,rootId,layout,disabled,onNodes,onSelect,onView,onUndo,onRedo};positions.current=board.view?.positions||positions.current;
  useEffect(()=>{
    if(!rootId)return;let mindMap,observer,alive=true;
    const emitNodes=()=>{if(!alive||suppress.current)return;try{const visible=flatten(mindMap.getData(true));const merged=mergeVisibleBranch(latest.current.board.nodes,latest.current.rootId,visible);if(!sameNodes(merged,latest.current.board.nodes))latest.current.onNodes(merged);}catch(reason){setError(reason.message);}};
    const emitView=()=>{if(!alive||suppress.current)return;try{const data=mindMap.getData(true),state=mindMap.view.getTransformData().state;const visibleCollapsed=flattenWithExpand(data).filter(x=>!x.expand).map(x=>x.id);const collapsed=mergeCollapsed(latest.current.board.nodes,latest.current.rootId,latest.current.board.view?.collapsed,visibleCollapsed);latest.current.onView({...latest.current.board.view,pan:{x:state.x,y:state.y},zoom:state.scale,positions:positions.current,collapsed});}catch(reason){setError(reason.message);}};
    try{
      const visible=branchOf(board.nodes,rootId);mindMap=new MindMap({el:host.current,data:treeFor(visible,board.view?.collapsed),layout,theme:'classic',readonly:disabled,fit:false,enableFreeDrag:false,isShowExpandNum:true,addHistoryTime:60,richText:false,minZoomRatio:20,maxZoomRatio:250,enableAutoEnterTextEditWhenKeydown:true,defaultInsertSecondLevelNodeText:'新想法',defaultInsertBelowSecondLevelNodeText:'新想法',themeConfig:{backgroundColor:'transparent',fontFamily:'ChatTodoCJK, system-ui, sans-serif'}});instance.current=mindMap;
      suppress.current=true;mindMap.view.scale=board.view?.zoom||1;mindMap.view.x=board.view?.pan?.x||0;mindMap.view.y=board.view?.pan?.y||0;mindMap.view.transform();queueMicrotask(()=>suppress.current=false);
      mindMap.on('data_change',emitNodes);mindMap.on('node_active',(_node,list)=>latest.current.onSelect(list?.[0]?.getData('uid')||null));mindMap.on('view_data_change',emitView);
      const original=mindMap.execCommand.bind(mindMap);mindMap.execCommand=(name,...args)=>{if(name==='BACK'){latest.current.onUndo();return;}if(name==='FORWARD'){latest.current.onRedo();return;}const result=original(name,...args);if(name==='SET_NODE_EXPAND')emitView();return result;};
      const active=()=>{if(!mindMap.renderer.activeNodeList.length)mindMap.renderer.root?.active();return mindMap.renderer.activeNodeList[0];};
      const finishEdit=async()=>{if(mindMap.renderer.textEdit.isShowTextEdit())mindMap.renderer.textEdit.hideEditTextBox();mindMap.command.originAddHistory();emitNodes();await Promise.resolve();};
      apiRef.current={finishEdit,addChild:()=>{active();mindMap.execCommand('INSERT_CHILD_NODE');},addSibling:()=>{const node=active();mindMap.execCommand(node?.isRoot?'INSERT_CHILD_NODE':'INSERT_NODE');},edit:()=>{const node=active();if(node)mindMap.renderer.textEdit.show({node});},fit:()=>mindMap.view.fit(),zoomIn:()=>mindMap.view.enlarge(),zoomOut:()=>mindMap.view.narrow()};
      observer=new ResizeObserver(()=>mindMap.resize());observer.observe(host.current);
    }catch(reason){setError(reason.message);}
    return()=>{alive=false;clearTimeout(layoutTimer.current);observer?.disconnect();mindMap?.destroy();instance.current=null;if(apiRef.current)apiRef.current=null;};
  },[board.id,rootId]);
  useEffect(()=>{const m=instance.current;if(m)m.setMode(disabled?'readonly':'edit');},[disabled]);
  useEffect(()=>{const m=instance.current;if(!m)return;try{const visible=branchOf(board.nodes,rootId),current=flatten(m.getData(true));if(sameNodes(current,visible))return;suppress.current=true;m.updateData(treeFor(visible,board.view?.collapsed,m.getData(true)));queueMicrotask(()=>suppress.current=false);}catch(reason){suppress.current=false;setError(reason.message);}},[board.nodes,board.revision,rootId]);
  useEffect(()=>{const m=instance.current;if(!m||m.opt.layout===layout)return;clearTimeout(layoutTimer.current);suppress.current=true;m.setLayout(layout);layoutTimer.current=setTimeout(()=>{if(instance.current!==m)return;suppress.current=false;m.view.fit();},80);return()=>clearTimeout(layoutTimer.current);},[layout]);
  return <div className="map-wrap"><div ref={host} className="smm-native" aria-label="思维导图编辑器"/>{error&&<div className="map-error" role="alert">{error}</div>}</div>;
}

function flattenWithExpand(data){const out=[];const walk=node=>{out.push({id:String(node.data?.uid||''),expand:node.data?.expand!==false});(node.children||[]).forEach(walk);};if(data?.root)walk(data.root);return out;}
