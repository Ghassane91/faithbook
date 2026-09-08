import type {RunSummary,RunPage} from './faithbook-types';

export async function collectRuns(load:(offset:number)=>Promise<RunPage>,signal:AbortSignal){
 const rows=new Map<number,RunSummary>();
 for(let offset=0;;){
  signal.throwIfAborted();
  const page=await load(offset);
  signal.throwIfAborted();
  for(const run of page.items)rows.set(run.id,run);
  offset+=page.items.length;
  if(!page.items.length||offset>=page.total)break;
 }
 return [...rows.values()];
}
export function previousCapture(runs:RunSummary[],current:RunSummary){
 const time=Date.parse(current.started_at);
 return runs.filter(r=>r.target_id===current.target_id&&r.status==='success'&&(Date.parse(r.started_at)<time||(Date.parse(r.started_at)===time&&r.id<current.id)))
  .sort((a,b)=>Date.parse(b.started_at)-Date.parse(a.started_at)||b.id-a.id)[0]??null;
}
