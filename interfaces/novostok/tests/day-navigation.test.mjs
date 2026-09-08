import test from 'node:test';
import assert from 'node:assert/strict';
import {shiftDay,dayInZone} from '../lib/faithbook-data.ts';
test('calendar navigation crosses month and year boundaries',()=>{
 assert.equal(shiftDay('2026-01-01',-1),'2025-12-31');
 assert.equal(shiftDay('2026-12-31',1),'2027-01-01');
 assert.equal(shiftDay('2024-03-01',-1),'2024-02-29');
 assert.equal(shiftDay('2026-03-01',-1),'2026-02-28');
});
test('calendar rejects normalized invalid dates',()=>{for(const value of ['2026-02-30','invalid','2026-13-01'])assert.throws(()=>shiftDay(value,1))});
test('today uses workspace timezone instead of browser or UTC day',()=>{assert.equal(dayInZone(new Date('2026-09-08T23:30:00Z'),'Africa/Casablanca'),'2026-09-09')});
