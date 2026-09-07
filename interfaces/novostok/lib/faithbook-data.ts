export const organizationKey='faithbook_organization_id';
export function safeUrl(value:string):string|null{try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;}}
export function sourceChannel(value:string){try{const host=new URL(value).hostname.toLowerCase();return host==='facebook.com'||host.endsWith('.facebook.com')?'Facebook':'Site web';}catch{return 'Site web';}}
export function dayInZone(now:Date,timezone:string){const p=new Intl.DateTimeFormat('en-US',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);const get=(type:string)=>p.find(x=>x.type===type)!.value;return `${get('year')}-${get('month')}-${get('day')}`;}
export function pastWeek(day:string){const end=new Date(day+'T12:00:00Z');return Array.from({length:7},(_,i)=>{const d=new Date(end);d.setUTCDate(end.getUTCDate()-6+i);return d.toISOString().slice(0,10);});}
export function successRate(success:number,failed:number){return success+failed?100*success/(success+failed):null;}
export function readableStatus(status:string){return ({success:'Réussie',failed:'Échec',pending:'En attente',running:'En cours',skipped:'Ignorée'} as Record<string,string>)[status]??'Aucune collecte';}
export function readableTime(value:string|null,timezone:string){if(!value)return '—';const d=new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value)?value:value+'Z');return Number.isNaN(d.getTime())?'—':new Intl.DateTimeFormat('fr-FR',{timeZone:timezone,day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}).format(d);}
