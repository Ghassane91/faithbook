export type RunStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped';
export interface User { id:number; email:string; must_change_password:boolean }
export interface Organization { id:number; name:string; role:'owner'|'admin'|'member'|'viewer' }
export interface RunSummary { id:number; target_id:number; status:RunStatus; capture_date:string; started_at:string; finished_at:string|null; error_message:string|null; skipped_reason:string|null; changed:boolean|null; duration_ms:number|null }
export interface Target { id:number; name:string; url:string; enabled:boolean; tags:string|null; account_id:number|null; next_run_at:string|null; last_run:RunSummary|null }
export interface Run extends RunSummary { screenshot_path:string|null; screenshot_bytes:number|null; page_title:string|null; ai_summary:string|null; drive_status:'local'|'pending'|'uploaded'|'failed'; logs:Array<{id:number;ts:string;level:string;step:string;message:string}> }
export interface RunPage { total:number; items:RunSummary[] }
