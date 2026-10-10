import {useState} from 'react';
import {QuestionBuilder} from './QuestionBuilder';
import {QuestionReadingPage,AddQuestionToDataset} from './QuestionReadingPage';
import {DatasetLibrary} from './DatasetLibrary';
import {DatasetBrowser} from './DatasetBrowser';
import {GlobalQuestionBank} from './GlobalQuestionBank';
import type {Action} from './Questions';
import type {Bootstrap} from './types';
import type {DataLocation} from './dataTypes';
import './data-workspace.css';
export function DataWorkspace({version,onRag,bootstrap,act,onRun}: {version:number;act:Action;bootstrap:Bootstrap;onRag:(key:string)=>void;onRun:(id:string)=>void}){
 const [addKey,setAddKey]=useState<string>();
 const [location,setLocation]=useState<DataLocation>({view:'datasets'});
 return <div className="data-workspace"><nav className="data-subnav" aria-label="Data 工作空间"><button aria-current={location.view==='datasets'?'page':undefined} onClick={()=>setLocation({view:'datasets'})}>Datasets</button><button aria-current={location.view==='bank'?'page':undefined} onClick={()=>setLocation({view:'bank',filters:{},offset:0})}>总题库</button><span>DATA → HARNESS → KB → TASK</span></nav>
 {location.view==='datasets'&&<DatasetLibrary version={version} onOpen={ref=>setLocation({view:'dataset',ref,filters:{},offset:0})}/>}
 {location.view==='bank'&&<><div className="data-heading"><div><p className="data-eyebrow">DATA / QUESTION BANK</p><h1>总题库</h1><p>统一浏览所有题目，保留版本、来源与 Dataset 归属。</p></div></div><GlobalQuestionBank version={version} onRead={key=>setLocation({view:"question",key,returnTo:location})} filters={location.filters} offset={location.offset} onLocation={(filters,offset)=>setLocation({...location,filters,offset})}/></>}
 {location.view==='dataset'&&<DatasetBrowser onBuild={()=>setLocation({view:"builder",target:location.ref,returnTo:location})} onRead={key=>setLocation({view:"question",key,returnTo:location})} key={location.ref.collection_id} refValue={location.ref} version={version} filters={location.filters} offset={location.offset} onLocation={(filters,offset)=>setLocation({...location,filters,offset})} onBack={()=>setLocation({view:'datasets'})} onChanged={ref=>setLocation({...location,ref})}/>}
 {location.view==='question'&&<QuestionReadingPage questionKey={location.key} context={location.returnTo} onBack={()=>setLocation(location.returnTo)} onQuestion={key=>setLocation({...location,key})} onAddToDataset={setAddKey} onRag={onRag}/>}
 {location.view==='builder'&&<><button className="data-back" onClick={()=>setLocation(location.returnTo)}>返回 Dataset</button><QuestionBuilder capabilities={bootstrap.capabilities} target={location.target} version={version} act={act} executionEnabled={bootstrap.service.execution_enabled} onRun={onRun} onAttached={ref=>setLocation({...location,target:ref,returnTo:location.returnTo.view==='dataset'?{...location.returnTo,ref}:location.returnTo})}/></>}
 {addKey&&<AddQuestionToDataset questionKey={addKey} onClose={()=>setAddKey(undefined)}/>}
 </div>;
}
