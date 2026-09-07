import type {User,Organization,Target,Run,RunPage,RunStatus} from './faithbook-types';
export class ApiError extends Error { status:number; constructor(status:number,message:string){super(message);this.status=status;} }
type Options={organizationId?:number;signal?:AbortSignal;method?:string;body?:unknown;blob?:boolean};
export async function request<T>(path:string,options:Options={}):Promise<T>{
 const controller=new AbortController();
 const abort=()=>controller.abort();
 if(options.signal?.aborted)controller.abort();
 options.signal?.addEventListener('abort',abort,{once:true});
 const timer=setTimeout(()=>controller.abort(),25000);
 try{
  const headers:Record<string,string>={Accept:options.blob?'image/*,application/pdf':'application/json'};
  if(options.organizationId!==undefined){if(!Number.isSafeInteger(options.organizationId)||options.organizationId<=0)throw new Error('Espace invalide.');headers['X-Organization-ID']=String(options.organizationId);}
  if(options.body!==undefined)headers['Content-Type']='application/json';
  const response=await fetch('/api'+path,{method:options.method??'GET',credentials:'same-origin',cache:'no-store',headers,signal:controller.signal,...(options.body!==undefined?{body:JSON.stringify(options.body)}:{})});
  if(!response.ok){let detail=`Le service a répondu avec une erreur (${response.status}).`;try{const data=await response.json() as {detail?:unknown};if(typeof data.detail==='string')detail=data.detail;}catch{}throw new ApiError(response.status,detail);}
  if(response.status===204)return undefined as T;
  const type=response.headers.get('content-type')??'';
  if(options.blob){if(!/^(image\/|application\/pdf)/i.test(type))throw new ApiError(502,'Le fichier demandé est indisponible.');return await response.blob() as T;}
  if(!type.includes('application/json'))throw new ApiError(502,'L’API FaithBook est indisponible à cette adresse.');
  return await response.json() as T;
 }catch(error){if(controller.signal.aborted&&!options.signal?.aborted)throw new ApiError(408,'Le serveur met trop de temps à répondre. Réessayez.');throw error;}
 finally{clearTimeout(timer);options.signal?.removeEventListener('abort',abort);}
}
export type RunQuery={capture_date?:string;status?:RunStatus;target_id?:number;limit?:number;offset?:number};
export function runsPath(query:RunQuery={}){const params=new URLSearchParams();for(const [key,value] of Object.entries(query))if(value!==undefined&&value!=='')params.set(key,String(value));return '/runs?'+params.toString();}
export const api={
 me:(signal?:AbortSignal)=>request<User>('/auth/me',{signal}),
 login:(email:string,password:string)=>request<User>('/auth/login',{method:'POST',body:{email,password}}),
 logout:()=>request<void>('/auth/logout',{method:'POST'}),
 organizations:(signal?:AbortSignal)=>request<Organization[]>('/organizations',{signal}),
 config:(signal?:AbortSignal)=>request<{timezone:string}>('/config',{signal}),
 targets:(organizationId:number,signal?:AbortSignal)=>request<Target[]>('/targets',{organizationId,signal}),
 runs:(organizationId:number,query:RunQuery,signal?:AbortSignal)=>request<RunPage>(runsPath(query),{organizationId,signal}),
 run:(organizationId:number,id:number,signal?:AbortSignal)=>request<Run>(`/runs/${id}`,{organizationId,signal}),
 image:(organizationId:number,id:number,full=false,signal?:AbortSignal)=>request<Blob>(`/runs/${id}/${full?'screenshot':'thumbnail'}`,{organizationId,signal,blob:true}),
 pdf:(organizationId:number,date:string)=>request<Blob>(`/runs/planche/${encodeURIComponent(date)}.pdf`,{organizationId,blob:true}),
};
