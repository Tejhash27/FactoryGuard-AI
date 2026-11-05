import {initial,advance,snapshot,mutate,assistant,csv,key} from './demo.mjs';
let demo,lastTick=Date.now();
function load(){if(!demo){try{demo=JSON.parse(localStorage.getItem(key));}catch{}if(!demo?.machines||!demo?.history)demo=initial();}return demo;}
function persist(){try{localStorage.setItem(key,JSON.stringify(demo));}catch{throw Error('Browser storage is unavailable or full. Export reports and free storage.');}}
export function endpoint(){return localStorage.getItem('fg-api')??import.meta.env.VITE_API_URL??'';}
export function mode(){return endpoint()?'api':'browser';}
async function fetchApi(path,options={}){const base=endpoint()==='auto'?'':endpoint().replace(/\/$/,'');const r=await fetch(base+'/api'+path,{...options,headers:{'Content-Type':'application/json','X-API-Key':sessionStorage.getItem('fg-key')||'',...options.headers},signal:AbortSignal.timeout(10000)});if(!r.ok){let e;try{e=await r.json();}catch{}throw Error(typeof e?.detail==='string'?e.detail:`API request failed (${r.status}). Check connection settings.`);}return r;}
export async function getState(){if(mode()==='api')return (await fetchApi('/state')).json();load();if(Date.now()-lastTick>=4900){advance(demo);lastTick=Date.now();persist();}return snapshot(structuredClone(demo));}
export async function getHistory(id){if(mode()==='api')return (await fetchApi(`/machines/${id}/readings`)).json();return structuredClone(load().history[id]||[]);}
export async function command(path,method='POST',body={}){if(mode()==='api')return (await fetchApi(path,{method,body:method==='DELETE'?undefined:JSON.stringify(body)})).json();load();mutate(demo,path,method,body);persist();return true;}
export async function ask(question){if(mode()==='api')return (await(await fetchApi('/assistant',{method:'POST',body:JSON.stringify({question})})).json()).answer;return assistant(load(),question);}
export async function report(kind){if(mode()==='api')return (await fetchApi('/reports/'+kind)).blob();const s=load();const rows=kind==='machines'?s.machines.map(m=>({id:m.id,name:m.name,zone:m.zone,...m.reading,risk:m.analysis.risk,explanation:m.analysis.reasons.join(' '),simulated:true})):kind==='maintenance'?s.tasks:kind==='loss'?[s.loss]:s.alerts;return new Blob([csv(rows)],{type:'text/csv;charset=utf-8'});}
export async function download(kind){const blob=await report(kind);const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`factoryguard-${kind}.csv`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
