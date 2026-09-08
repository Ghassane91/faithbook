import test from 'node:test';
import assert from 'node:assert/strict';
import {collectRuns,previousCapture} from '../lib/capture-navigation.ts';
const row=(id,day,target_id=1,status='success')=>({id,target_id,status,started_at:`2026-09-${day}T12:00:00Z`});
test('previous capture belongs to same target and is successful, even across days',()=>{
 const current=row(9,'08');
 assert.equal(previousCapture([row(10,'09'),row(8,'07',2),row(7,'07',1,'failed'),row(6,'06'),current],current).id,6);
 assert.equal(previousCapture([current,row(10,'09')],current),null);
});
test('same timestamp uses earlier id deterministically',()=>{assert.equal(previousCapture([row(7,'08'),row(8,'08'),row(10,'08')],row(9,'08')).id,8)});
test('navigation loads beyond first page and deduplicates overlapping pages',async()=>{
 const offsets=[];const result=await collectRuns(async offset=>{offsets.push(offset);return offset===0?{total:4,items:[row(1,'08'),row(2,'08')]}:{total:4,items:[row(2,'08'),row(3,'08')]}},new AbortController().signal);
 assert.deepEqual(offsets,[0,2]);assert.deepEqual(result.map(r=>r.id),[1,2,3]);
});
test('aborted navigation never fetches another page',async()=>{const c=new AbortController();let calls=0;await assert.rejects(collectRuns(async()=>{calls++;c.abort();return {total:200,items:[row(1,'08')]}},c.signal),{name:'AbortError'});assert.equal(calls,1)});
