import base64
import io
from datetime import datetime, timezone, timedelta

import pytest
from PIL import Image
from sqlalchemy import select

from app.database import session_scope
from app.models import BrowserDevice, BrowserTarget, Run, Target
from app.services.browser_schedule import ZONE, due_slot, next_slot


def test_huntx_queue_all_merchants_isolated_and_idempotent(enrolled, monkeypatch):
    from app.services.browser_links import enqueue_links
    from app.models import BrowserLinkJob, RunStatus, TriggerType
    from app.services.quotas import _target_count
    monkeypatch.setattr('app.services.browser_links.socket.getaddrinfo', lambda *a: [(2, 1, 6, '', ('93.184.216.34', 443))])
    client, headers, device, bearer = enrolled
    org_id = int(headers['X-Organization-ID'])
    with session_scope() as s:
        source = Target(organization_id=org_id, name='HuntX cameras', url='https://huntx.example.com/app/cameras', enabled=True, capture_row_links=True)
        s.add(source); s.flush()
        source_id = source.id
        run = Run(target_id=source.id, status=RunStatus.success, trigger=TriggerType.manual, capture_date='2026-10-07')
        s.add(run); s.flush()
        run_id = run.id
        links = [{'url':u, 'marque':'Same brand', 'modele':'Same name', 'colonne':'BRAND'} for u in
                 ['https://www.amazon.com/dp/first','https://www.reconyx.com/product/second','https://www.amazon.com/dp/first','http://127.0.0.1/private']]
        assert enqueue_links(s, run.id, links) == {'queued':2,'rejected':1}
        assert enqueue_links(s, run.id, links) == {'queued':2,'rejected':1}
        assert len(list(s.scalars(select(BrowserLinkJob).where(BrowserLinkJob.source_run_id==run.id)))) == 2
        assert _target_count(s,org_id) == 4  # three control pages + HuntX, no quota per derived link
    assert client.post('/api/browser-capture/claim',headers=bearer).json()['job'] is None
    v2 = bearer | {'X-FaithBook-Capture-Version':'2'}
    job = client.post('/api/browser-capture/claim',headers=v2).json()['job']
    assert job['kind']=='product' and job['url']=='https://www.amazon.com/dp/first'
    assert client.post('/api/browser-capture/result',headers=v2,json=payload(job)|{'final_url':'https://evil.com/'}).status_code==422
    result = client.post('/api/browser-capture/result',headers=v2,json=payload(job))
    assert result.status_code==200,result.text
    assert client.post('/api/browser-capture/result',headers=v2,json=payload(job)).json()['duplicate']
    with session_scope() as s:
        done = s.scalar(select(BrowserLinkJob).where(BrowserLinkJob.target_id==job['target_id']))
        assert done.finished_at and done.result_run_id==result.json()['run_id']
        s.get(Target,source_id).enabled=False
    assert client.post('/api/browser-capture/claim',headers=v2).json()['job'] is None


def test_huntx_no_cross_organization_device(enrolled):
    from app.services.browser_links import enqueue_links
    from app.models import Organization, RunStatus, TriggerType
    with session_scope() as s:
        other = Organization(name='Other tenant', slug='other-huntx-tenant');s.add(other);s.flush()
        target=Target(organization_id=other.id,name='HuntX',url='https://huntx.example.com/',enabled=True,capture_row_links=True)
        s.add(target);s.flush()
        run=Run(target_id=target.id,status=RunStatus.success,trigger=TriggerType.manual,capture_date='2026-10-07')
        s.add(run);s.flush()
        assert enqueue_links(s,run.id,[{'url':'https://www.amazon.com/item'}]) is None


@pytest.mark.parametrize('when,expected', [
    ('2026-10-01T08:59:00', None),
    ('2026-10-01T09:00:00', '2026-10-01'),
    ('2026-10-03T09:01:00', None),
    ('2026-10-15T09:00:00', '2026-10-15'),
    ('2026-10-31T09:00:00', None),
    ('2026-02-15T09:00:00', '2026-02-15'),
])
def test_calendar(when, expected):
    assert due_slot(datetime.fromisoformat(when).replace(tzinfo=ZONE), datetime(2026, 1, 1, tzinfo=timezone.utc)) == expected


def test_calendar_next_and_enrollment():
    now = datetime.fromisoformat('2026-12-31T12:00:00+00:00')
    assert next_slot(now).startswith('2027-01-01T09:00:00')
    now = datetime(2026, 10, 15, 9, 1, tzinfo=ZONE)
    assert due_slot(now, now) is None


@pytest.fixture
def enrolled(auth_client):
    org = auth_client.post('/api/organizations', json={'name': 'Chrome tests'}).json()
    headers = {'X-Organization-ID': str(org['id'])}
    response = auth_client.post('/api/browser-capture/devices', json={'name': 'Test PC'}, headers=headers)
    assert response.status_code == 201, response.text
    device = response.json()
    bearer = {'Authorization': 'Bearer ' + device['token']}
    return auth_client, headers, device, bearer


def claim_test(enrolled):
    client, headers, device, bearer = enrolled
    response = client.post(f"/api/browser-capture/devices/{device['id']}/test", headers=headers)
    assert response.status_code == 200, response.text
    response = client.post('/api/browser-capture/claim', headers=bearer)
    assert response.status_code == 200, response.text
    return response.json()['job']


def payload(job):
    out = io.BytesIO()
    Image.new('RGB', (150, 150), 'white').save(out, format='PNG')
    return {key: job[key] for key in ('target_id', 'slot', 'lease')} | {
        'status': 'success', 'final_url': job['url'], 'title': 'Products',
        'text': 'Outdoor products and prices. Tent $89. Shop our outdoor products today.',
        'image': base64.b64encode(out.getvalue()).decode()}


def queued_product(enrolled, monkeypatch, links=None):
    from app.models import RunStatus, TriggerType
    from app.services.browser_links import enqueue_links
    monkeypatch.setattr('app.services.browser_links.socket.getaddrinfo', lambda *a: [(2, 1, 6, '', ('93.184.216.34', 443))])
    client, headers, device, bearer = enrolled
    with session_scope() as session:
        target = Target(organization_id=int(headers['X-Organization-ID']), name='HuntX archive',
                        url='https://huntx.example.com/', enabled=True, capture_row_links=True)
        session.add(target); session.flush()
        run = Run(target_id=target.id, status=RunStatus.success, trigger=TriggerType.manual, capture_date='2026-10-08')
        session.add(run); session.flush()
        source_id = run.id
        enqueue_links(session, run.id, links or [{'id':'42','marque':'Browning','modele':'Camera','colonne':'AMAZON','url':'https://www.amazon.com/dp/example'}])
    v2 = bearer | {'X-FaithBook-Capture-Version':'2'}
    job = client.post('/api/browser-capture/claim', headers=v2).json()['job']
    return client, headers, device, v2, job, source_id


def test_technical_retry_backoff_history_and_success(enrolled, monkeypatch):
    from app.models import BrowserLinkJob
    client, headers, device, bearer, first, source_id = queued_product(enrolled, monkeypatch)
    failure = payload(first) | {'status':'capture','image':'','reason':'net::ERR_CONNECTION_RESET'}
    response = client.post('/api/browser-capture/result', headers=bearer, json=failure)
    assert response.status_code == 200, response.text
    first_id = response.json()['run_id']
    assert client.post('/api/browser-capture/result', headers=bearer, json=failure).json()['duplicate']
    assert client.post('/api/browser-capture/claim', headers=bearer).json()['job'] is None
    with session_scope() as session:
        task = session.scalar(select(BrowserLinkJob).where(BrowserLinkJob.source_run_id == source_id))
        assert task.finished_at is None and task.attempt_count == 1
        task.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    second = client.post('/api/browser-capture/claim', headers=bearer).json()['job']
    assert second['slot'] != first['slot'] and second['slot'].endswith('-a2')
    done = client.post('/api/browser-capture/result', headers=bearer, json=payload(second))
    assert done.status_code == 200, done.text
    with session_scope() as session:
        task = session.scalar(select(BrowserLinkJob).where(BrowserLinkJob.source_run_id == source_id))
        assert task.finished_at and task.attempt_count == 2
        assert task.result_run_id != first_id
        assert session.get(Run, first_id).status.value == 'failed'


def test_retry_stops_after_three_and_does_not_restart(enrolled, monkeypatch):
    from app.models import BrowserLinkJob
    client, headers, device, bearer, job, source_id = queued_product(enrolled, monkeypatch)
    for number in range(1, 4):
        response = client.post('/api/browser-capture/result', headers=bearer,
            json=payload(job) | {'status':'capture','image':'','reason':'Loading timeout'})
        assert response.status_code == 200, response.text
        with session_scope() as session:
            task = session.scalar(select(BrowserLinkJob).where(BrowserLinkJob.source_run_id == source_id))
            assert task.attempt_count == number
            if number < 3:
                assert task.finished_at is None
                task.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            else:
                assert task.finished_at is not None and task.next_attempt_at is None
        job = client.post('/api/browser-capture/claim', headers=bearer).json()['job']
    assert job is None
    assert client.post(f"/api/browser-capture/devices/{device['id']}/retry-products", headers=headers).json()['queued'] == 0


def test_same_product_keeps_every_row_reference(enrolled, monkeypatch):
    import json
    from app.models import BrowserLinkJob, HuntxDriveArtifact
    links = [{'id':str(i),'marque':'Brand','modele':'Camera '+str(i),'colonne':'AMAZON','url':'https://www.amazon.com/dp/shared'} for i in (11, 22)]
    client, headers, device, bearer, job, source_id = queued_product(enrolled, monkeypatch, links)
    result = client.post('/api/browser-capture/result', headers=bearer, json=payload(job))
    assert result.status_code == 200, result.text
    with session_scope() as session:
        task = session.scalar(select(BrowserLinkJob).where(BrowserLinkJob.source_run_id == source_id))
        assert {ref['id'] for ref in json.loads(task.row_references)} == {'11','22'}
        artifacts = session.scalars(select(HuntxDriveArtifact).where(HuntxDriveArtifact.result_run_id == result.json()['run_id'])).all()
        assert {a.row_key for a in artifacts} == {'11','22'}
    summary = client.get('/api/browser-capture/archive', headers=headers).json()['sources'][-1]
    assert summary['total'] == 1 and summary['captured'] == 1 and summary['drive_pending'] >= 2
    other = client.post('/api/organizations', json={'name':'No archive access'}).json()
    assert client.get('/api/browser-capture/archive', headers={'X-Organization-ID':str(other['id'])}).json() == {'sources':[]}


def test_capture_date_preserves_screenshot_day_at_midnight(enrolled, monkeypatch):
    client, _, _, bearer = enrolled
    now = datetime(2026, 10, 10, 0, 1, tzinfo=ZONE)
    monkeypatch.setattr('app.api.browser_capture.utcnow', lambda:now)
    job = claim_test(enrolled)
    stamp = now - timedelta(minutes=2)
    response = client.post('/api/browser-capture/result', headers=bearer, json=payload(job) | {'captured_at':stamp.isoformat()})
    assert response.status_code == 200, response.text
    with session_scope() as session:
        assert session.get(Run, response.json()['run_id']).capture_date == '2026-10-09'


@pytest.mark.parametrize('timestamp', ['2020-01-01T00:00:00Z', '2026-01-01T12:00:00'])
def test_capture_timestamp_must_belong_to_reservation(enrolled, timestamp):
    client, _, _, bearer = enrolled
    job = claim_test(enrolled)
    response = client.post('/api/browser-capture/result', headers=bearer, json=payload(job) | {'captured_at':timestamp})
    assert response.status_code == 422


def test_import_history_and_idempotency(enrolled):
    client, headers, device, bearer = enrolled
    job = claim_test(enrolled)
    body = payload(job)
    response = client.post('/api/browser-capture/result', headers=bearer, json=body)
    assert response.status_code == 200, response.text
    run_id = response.json()['run_id']
    assert response.json()['status'] == 'success'
    again = client.post('/api/browser-capture/result', headers=bearer, json=body)
    assert again.json() == {'run_id': run_id, 'duplicate': True}
    assert client.get(f'/api/runs/{run_id}', headers=headers).status_code == 200
    assert client.get(f'/api/runs/{run_id}/thumbnail', headers=headers).status_code == 200
    with session_scope() as session:
        assert session.scalar(select(BrowserDevice).where(BrowserDevice.id == device['id'])).token_hash != device['token']


def test_revoke_and_no_secrets_in_listing(enrolled):
    client, headers, device, bearer = enrolled
    listing = client.get('/api/browser-capture/devices', headers=headers)
    assert device['token'] not in listing.text and 'token_hash' not in listing.text
    assert client.post(f"/api/browser-capture/devices/{device['id']}/revoke", headers=headers).status_code == 200
    assert client.post('/api/browser-capture/claim', headers=bearer).status_code == 401


def test_reject_cookie_only_for_device_api(enrolled):
    client, _, _, _ = enrolled
    assert client.post('/api/browser-capture/claim').status_code == 401


@pytest.mark.parametrize('change', [
    {'lease': 'forged'}, {'slot': 'forged'}, {'target_id': 999999},
    {'final_url': 'http://www.walmart.com/'}, {'final_url': 'https://www.walmart.com.evil.invalid/'},
    {'image': 'not-image'},
])
def test_reject_invalid_result(enrolled, change):
    client, _, _, bearer = enrolled
    job = claim_test(enrolled)
    response = client.post('/api/browser-capture/result', headers=bearer, json=payload(job) | change)
    assert response.status_code in (404, 409, 422), response.text


def test_challenge_does_not_create_screenshot(enrolled):
    client, headers, _, bearer = enrolled
    job = claim_test(enrolled)
    body = payload(job) | {'title': 'Robot or human?', 'text': 'Please verify you are human.'}
    response = client.post('/api/browser-capture/result', headers=bearer, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'suspended'
    with session_scope() as session:
        run = session.get(Run, response.json()['run_id'])
        assert run.screenshot_path is None


def test_foreign_org_cannot_revoke_or_import(enrolled):
    client, _, device, bearer = enrolled
    job = claim_test(enrolled)
    other = client.post('/api/organizations', json={'name': 'Other Chrome'}).json()
    headers = {'X-Organization-ID': str(other['id'])}
    assert client.post(f"/api/browser-capture/devices/{device['id']}/revoke", headers=headers).status_code == 404
    d = client.post('/api/browser-capture/devices', headers=headers, json={}).json()
    response = client.post('/api/browser-capture/result', headers={'Authorization': 'Bearer ' + d['token']}, json=payload(job))
    assert response.status_code == 404


def test_lease_expiry_and_reassignment(enrolled):
    client, _, _, bearer = enrolled
    old = claim_test(enrolled)
    with session_scope() as session:
        session.get(BrowserTarget, old['target_id']).lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    new = client.post('/api/browser-capture/claim', headers=bearer).json()['job']
    assert new['target_id'] == old['target_id'] and new['lease'] != old['lease']
    assert client.post('/api/browser-capture/result', headers=bearer, json=payload(old)).status_code == 409
    assert client.post('/api/browser-capture/result', headers=bearer, json=payload(new)).status_code == 200


@pytest.mark.asyncio
async def test_browser_target_never_runs_in_server_worker(enrolled):
    from app.scheduler import schedule_target, scheduler, job_id_for
    from app.services.runner import trigger_target
    from app.models import TriggerType
    job = claim_test(enrolled)
    with session_scope() as session:
        schedule_target(session.get(Target, job['target_id']))
    assert scheduler.get_job(job_id_for(job['target_id'])) is None
    with pytest.raises(RuntimeError, match='Cible Chrome'):
        await trigger_target(job['target_id'], TriggerType.manual)


def test_target_quota_is_atomic(enrolled):
    from app.models import Organization
    client, _, _, _ = enrolled
    org = client.post('/api/organizations', json={'name': 'Quota Chrome'}).json()
    with session_scope() as session:
        session.get(Organization, org['id']).quota_targets = 2
    headers = {'X-Organization-ID': str(org['id'])}
    assert client.post('/api/browser-capture/devices', json={}, headers=headers).status_code == 409
    assert client.get('/api/browser-capture/devices', headers=headers).json() == []


def test_extension_archive(enrolled):
    client, headers, _, _ = enrolled
    response = client.get('/api/browser-capture/extension', headers=headers)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'


def test_scheduled_slot_runs_once_per_target(enrolled, monkeypatch):
    from app.api import browser_capture
    now = datetime(2026, 10, 15, 9, 30, tzinfo=ZONE)
    monkeypatch.setattr(browser_capture, 'utcnow', lambda: now)
    client, _, device, bearer = enrolled
    with session_scope() as session:
        row = session.get(BrowserDevice, device['id'])
        row.created_at = datetime(2026, 10, 1, tzinfo=ZONE)
        row.expires_at = datetime(2027, 10, 1, tzinfo=ZONE)
    targets = []
    for _ in range(3):
        job = client.post('/api/browser-capture/claim', headers=bearer).json()['job']
        assert job['slot'] == '2026-10-15'
        targets.append(job['target_id'])
        response = client.post('/api/browser-capture/result', headers=bearer,
                               json=payload(job) | {'status': 'challenge', 'image': ''})
        assert response.status_code == 200, response.text
    assert len(set(targets)) == 3
    assert client.post('/api/browser-capture/claim', headers=bearer).json()['job'] is None


def test_cannot_silently_change_chrome_schedule(enrolled):
    client, headers, _, _ = enrolled
    job = claim_test(enrolled)
    response = client.patch(f"/api/targets/{job['target_id']}", headers=headers,
                            json={'cron_expression': '0 9 * * *'})
    assert response.status_code == 422


def test_storage_quota_does_not_leave_image_or_success(enrolled):
    from app.models import Organization
    client, headers, _, bearer = enrolled
    job = claim_test(enrolled)
    with session_scope() as session:
        session.get(Organization, int(headers['X-Organization-ID'])).quota_storage_bytes = 1
    response = client.post('/api/browser-capture/result', headers=bearer, json=payload(job))
    assert response.status_code == 409
    with session_scope() as session:
        assert session.scalar(select(Run).where(Run.target_id == job['target_id'])) is None



@pytest.mark.parametrize('error_text', ["SHOOT! THE PAGE YOU WERE LOOKING FOR COULDN'T BE FOUND.", "We couldn’t find this page. Try searching or go to the homepage."])
def test_missing_product_page_is_not_success(enrolled, error_text):
    job = claim_test(enrolled)
    client, _, _, bearer = enrolled
    body = payload(job) | {'title': '404', 'text': error_text + ' Recommended pages and contact details.'}
    response = client.post('/api/browser-capture/result', headers=bearer, json=body)
    assert response.status_code == 200
    assert response.json()['status'] == 'skipped'
    with session_scope() as s:
        run = s.get(Run, response.json()['run_id'])
        assert run.screenshot_path is None and run.error_message is None
        assert '404' in run.skipped_reason and 'HuntX' in run.skipped_reason


@pytest.mark.parametrize('status', ['success', 'capture', 'navigation'])
def test_merchant_refusal_is_not_a_failure(enrolled, status):
    client, _, _, bearer = enrolled
    job = claim_test(enrolled)
    body = payload(job) | {'status': status, 'title': 'Access Denied',
                           'text': 'You don\'t have permission to access "http://www.basspro.com/p/x" on this server. '
                                   'Reference #18.8624c317 https://errors.edgesuite.net/18.8624c317'}
    response = client.post('/api/browser-capture/result', headers=bearer, json=body)
    assert response.status_code == 200
    assert response.json()['status'] == 'skipped'
    with session_scope() as s:
        run = s.get(Run, response.json()['run_id'])
        assert run.screenshot_path is None and run.error_message is None
        assert run.skipped_reason.startswith('Refusé par le marchand')


def test_product_page_mentioning_access_denied_stays_success(enrolled):
    client, _, _, bearer = enrolled
    job = claim_test(enrolled)
    longue = 'Trail camera with 4K video and long battery life. ' * 60
    body = payload(job) | {'text': longue + ' Remote access denied alerts when the SD card is full.'}
    response = client.post('/api/browser-capture/result', headers=bearer, json=body)
    assert response.json()['status'] == 'success'


def test_generic_capture_error_is_still_a_failure(enrolled):
    client, _, _, bearer = enrolled
    job = claim_test(enrolled)
    body = payload(job) | {'status': 'capture', 'title': '', 'text': '', 'image': ''}
    response = client.post('/api/browser-capture/result', headers=bearer, json=body)
    assert response.json()['status'] == 'failed'


def test_amazon_access_screen_is_suspended(enrolled):
    client, _, _, bearer = enrolled
    job = claim_test(enrolled)
    response = client.post('/api/browser-capture/result', headers=bearer, json=payload(job) | {
        'title':'Amazon', 'text':'Click the button below to continue shopping. Continue shopping Conditions of Use Privacy Notice'})
    assert response.status_code == 200
    assert response.json()['status'] == 'suspended'


def test_failure_reason_and_diagnostic_image_are_kept(enrolled):
    client, _, _, bearer = enrolled
    job = claim_test(enrolled)
    image = payload(job)['image']
    body = payload(job) | {'status': 'capture', 'title': '', 'text': '', 'image': '',
                           'reason': 'Page trop grande pour une capture complète.', 'diagnostic_image': image}
    response = client.post('/api/browser-capture/result', headers=bearer, json=body)
    assert response.json()['status'] == 'failed'
    with session_scope() as s:
        run = s.get(Run, response.json()['run_id'])
        assert run.screenshot_path is None
        assert 'Détail : Page trop grande' in run.error_message
        assert run.diagnostic_path and run.diagnostic_path.endswith('-diagnostic.jpg')


def test_truncated_success_keeps_reason_out_of_error(enrolled):
    client, _, _, bearer = enrolled
    job = claim_test(enrolled)
    response = client.post('/api/browser-capture/result', headers=bearer,
                           json=payload(job) | {'reason': 'Page tronquée à 16 000 px de haut.'})
    assert response.json()['status'] == 'success'
