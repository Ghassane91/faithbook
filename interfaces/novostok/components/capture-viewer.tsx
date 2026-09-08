'use client';
import {useEffect,useState,useRef,type KeyboardEvent,type UIEvent} from 'react';
import {Dialog,DialogContent,DialogTitle,DialogDescription,DialogClose} from '@/components/ui/dialog';
import {api,ApiError} from '@/lib/faithbook-api';
import {collectRuns,previousCapture} from '@/lib/capture-navigation';
import {readableTime} from '@/lib/faithbook-data';
import type {RunSummary,Target} from '@/lib/faithbook-types';

function FullImage({org,run,zoom,expire}:{org:number;run:RunSummary;zoom:number;expire:()=>void}){
 const [url,setUrl]=useState(''),[error,setError]=useState(''),[revision,setRevision]=useState(0),[extension,setExtension]=useState('png');
 useEffect(()=>{const c=new AbortController();let blobUrl='';setUrl('');setError('');
  api.image(org,run.id,true,c.signal).then(blob=>{if(c.signal.aborted)return;blobUrl=URL.createObjectURL(blob);setExtension(blob.type.includes('jpeg')?'jpg':blob.type.includes('webp')?'webp':'png');setUrl(blobUrl)}).catch(e=>{if(c.signal.aborted)return;if(e instanceof ApiError&&e.status===401)expire();else setError('Image indisponible. Vous pouvez réessayer sans fermer la visionneuse.')});
  return()=>{c.abort();if(blobUrl)URL.revokeObjectURL(blobUrl)};
 },[org,run.id,expire,revision]);
 return <><div className="viewer-image-actions">{url&&<a className="outline-action" href={url} download={'faithbook-'+run.capture_date+'-'+run.id+'.'+extension}>Télécharger cette image</a>}</div><div className="viewer-scroll" tabIndex={0} aria-label="Image défilable">{url?<img src={url} alt={'Capture #'+run.id} style={{width:zoom+'%',maxWidth:'none'}} onError={()=>{setUrl('');setError('Cette image ne peut pas être affichée.')}}/>:<div className="viewer-image-state"><p role={error?'alert':'status'}>{error||'Chargement de l’image originale…'}</p>{error&&<button className="outline-action" onClick={()=>setRevision(v=>v+1)}>Réessayer</button>}</div>}</div></>;

}
export function CaptureViewer({org,initial,date,targetId,targets,timezone,expire,onClose,onDetails}:{org:number;initial:RunSummary;date:string;targetId?:number;targets:Target[];timezone:string;expire:()=>void;onClose:()=>void;onDetails:(run:RunSummary)=>void}){
 const [current,setCurrent]=useState(initial),[runs,setRuns]=useState<RunSummary[]>([initial]),[loading,setLoading]=useState(true),[error,setError]=useState(''),[zoom,setZoom]=useState(100),[compare,setCompare]=useState(false),[previous,setPrevious]=useState<RunSummary|null>(null),[comparing,setComparing]=useState(false),[compareError,setCompareError]=useState('');
 useEffect(()=>{const c=new AbortController();collectRuns(offset=>api.runs(org,{capture_date:date,status:'success',target_id:targetId,limit:100,offset},c.signal),c.signal).then(rows=>{if(!rows.some(r=>r.id===initial.id))rows.unshift(initial);setRuns(rows)}).catch(e=>{if(c.signal.aborted)return;if(e instanceof ApiError&&e.status===401)expire();else setError('Navigation indisponible. Fermez puis rouvrez la capture pour réessayer.')}).finally(()=>{if(!c.signal.aborted)setLoading(false)});return()=>c.abort()},[org,date,targetId,initial,expire]);
 useEffect(()=>{setPrevious(null);setCompareError('');if(!compare)return;const c=new AbortController();setComparing(true);
  collectRuns(offset=>api.runs(org,{target_id:current.target_id,status:'success',limit:100,offset},c.signal),c.signal).then(rows=>setPrevious(previousCapture(rows,current))).catch(e=>{if(c.signal.aborted)return;if(e instanceof ApiError&&e.status===401)expire();else setCompareError('Comparaison indisponible. Désactivez puis réactivez la comparaison pour réessayer.')}).finally(()=>{if(!c.signal.aborted)setComparing(false)});return()=>c.abort();
 },[org,current,compare,expire]);
 const [sync,setSync]=useState(true);
 const synchronized=useRef(new WeakMap<HTMLElement,{top:number;left:number}>());
 function synchronize(event:UIEvent<HTMLDivElement>){
  if(!sync||!compare)return;
  const source=event.target as HTMLElement;
  if(!source.classList.contains('viewer-scroll'))return;
  const expected=synchronized.current.get(source);
  if(expected&&Math.abs(source.scrollTop-expected.top)<2&&Math.abs(source.scrollLeft-expected.left)<2){synchronized.current.delete(source);return}
  for(const other of event.currentTarget.querySelectorAll<HTMLElement>('.viewer-scroll')){
   if(other===source)continue;
   const top=source.scrollTop/Math.max(1,source.scrollHeight-source.clientHeight)*Math.max(0,other.scrollHeight-other.clientHeight);
   const left=source.scrollLeft/Math.max(1,source.scrollWidth-source.clientWidth)*Math.max(0,other.scrollWidth-other.clientWidth);
   if(Math.abs(other.scrollTop-top)<1&&Math.abs(other.scrollLeft-left)<1)continue;
   synchronized.current.set(other,{top,left});other.scrollTop=top;other.scrollLeft=left;
  }
 }
 function shortcut(event:KeyboardEvent){
  if(event.ctrlKey||event.metaKey||event.altKey||(event.target as HTMLElement).closest('input,textarea,select,[contenteditable=true]'))return;
  if(event.key==='ArrowLeft'||event.key==='ArrowRight'){if(loading)return;event.preventDefault();move(event.key==='ArrowLeft'?-1:1)}
  else if(event.key==='+'||event.key==='='){event.preventDefault();setZoom(z=>Math.min(300,z+25))}
  else if(event.key==='-'){event.preventDefault();setZoom(z=>Math.max(50,z-25))}
  else if(event.key==='0'){event.preventDefault();setZoom(100)}
 }
 const index=runs.findIndex(r=>r.id===current.id);
 function move(delta:number){const next=runs[index+delta];if(next){setCurrent(next);setZoom(100);setCompare(false)}}
 const name=targets.find(t=>t.id===current.target_id)?.name??'Cible #'+current.target_id;
 return <Dialog open onOpenChange={open=>{if(!open)onClose()}}><DialogContent className="capture-viewer" onKeyDown={shortcut} showCloseButton={false}><header className="viewer-header"><div><DialogTitle>{name}</DialogTitle><DialogDescription>{readableTime(current.started_at,timezone)} · Capture #{current.id}</DialogDescription></div><button className="outline-action" onClick={()=>onDetails(current)}>Fiche de collecte</button><DialogClose className="outline-action">Fermer</DialogClose></header><nav className="viewer-controls" aria-label="Outils de lecture"><button disabled={loading||index<=0} onClick={()=>move(-1)}>← Précédente</button><span>{loading?'Chargement…':`${index+1} / ${runs.length}`}</span><button disabled={loading||index>=runs.length-1} onClick={()=>move(1)}>Suivante →</button><button disabled={zoom<=50} onClick={()=>setZoom(z=>Math.max(50,z-25))} aria-label="Réduire le zoom">−</button><span>{zoom} %</span><button disabled={zoom>=300} onClick={()=>setZoom(z=>Math.min(300,z+25))} aria-label="Augmenter le zoom">+</button><button onClick={()=>setZoom(100)}>Ajuster à la largeur</button><button aria-pressed={compare} onClick={()=>setCompare(v=>!v)}>Comparer avec la capture précédente</button>{compare&&<button aria-pressed={sync} onClick={()=>setSync(v=>!v)}>Défilement synchronisé {sync?'activé':'désactivé'}</button>}</nav><p className="viewer-help">← → : changer de capture · + / − : zoom · 0 : ajuster · Échap : fermer</p>{error&&<p role="alert">{error}</p>}<div onScrollCapture={synchronize} className={'viewer-images'+(compare?' is-comparing':'')}>{compare&&<section><h3>Capture précédente {previous&&' · '+readableTime(previous.started_at,timezone)}</h3>{comparing?<p role="status">Recherche de la capture précédente…</p>:compareError?<p role="alert">{compareError}</p>:previous?<FullImage key={previous.id} org={org} run={previous} zoom={zoom} expire={expire}/>:<p>Aucune capture réussie antérieure pour cette cible.</p>}</section>}<section><h3>Capture sélectionnée · {readableTime(current.started_at,timezone)}</h3><FullImage key={current.id} org={org} run={current} zoom={zoom} expire={expire}/></section></div></DialogContent></Dialog>;
}
