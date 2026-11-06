import base64
import io
import json

import pytest
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select

from app.config import settings
from app.database import session_scope
from app.models import BrowserLinkJob, HuntxDriveArtifact, Run, RunStatus, Target, TriggerType, utcnow
from app.services import zyte_capture as zyte
from test_browser_capture import enrolled


def response(url='https://www.amazon.com/product'):
    out = io.BytesIO()
    Image.new('RGB', (150, 150), 'white').save(out, format='JPEG')
    return {'url': url, 'browserHtml': '<title>Camera</title><p>Outdoor camera with specifications, images and a price of $149. Available today.</p>',
            'screenshot': base64.b64encode(out.getvalue()).decode()}


@pytest.mark.parametrize('change', [
    {'url': 'https://evil.com/product'},
    {'browserHtml': '<title>Access denied</title>'},
    {'browserHtml': '<title>404 Not Found</title>'},
    {'browserHtml': '<title>Camera</title><p>Click the button below to continue shopping</p>'},
    {'screenshot': 'invalid'},
    {'statusCode': 404},
])
def test_reject_unusable_capture(change):
    with pytest.raises(Exception):
        zyte.validate_response(response() | change, 'https://www.amazon.com/product')


def test_disabled_never_calls_provider(monkeypatch):
    monkeypatch.setattr(settings, 'zyte_enabled', False)
    monkeypatch.setattr(zyte, 'extract', lambda *a: pytest.fail('Unexpected paid request'))
    assert zyte.run_one() == {'state': 'disabled'}


def test_key_file_and_missing_key(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'zyte_api_key', SecretStr(''))
    monkeypatch.setattr(settings, 'zyte_api_key_file', str(tmp_path / 'key'))
    assert zyte.api_key() == ''
    (tmp_path / 'key').write_text('secret\n')
    assert zyte.api_key() == 'secret'


@pytest.mark.parametrize('failure', [False, True])
def test_fallback_preserves_history_archives_once_and_caps_spend(enrolled, monkeypatch, failure):
    from app.services.browser_links import enqueue_links
    client, headers, device, bearer = enrolled
    org_id = int(headers['X-Organization-ID'])
    monkeypatch.setattr('app.services.browser_links.socket.getaddrinfo', lambda *a: [(2, 1, 6, '', ('93.184.216.34', 443))])
    with session_scope() as s:
        source = Target(organization_id=org_id, name='HuntX', url='https://huntx.example.com/', enabled=True, capture_row_links=True)
        s.add(source); s.flush()
        original = Run(target_id=source.id, status=RunStatus.success, trigger=TriggerType.manual, capture_date='2026-10-09')
        s.add(original); s.flush()
        enqueue_links(s, original.id, [{'id':'camera-1', 'url':'https://www.amazon.com/product'}])
        job = s.scalar(select(BrowserLinkJob).where(BrowserLinkJob.source_run_id == original.id))
        old = Run(target_id=job.target_id, status=RunStatus.suspended, trigger=TriggerType.manual, capture_date='2026-10-09')
        s.add(old); s.flush()
        job.result_run_id, job.finished_at = old.id, utcnow()
        old_id, job_id = old.id, job.id
    monkeypatch.setattr(settings, 'zyte_enabled', True)
    monkeypatch.setattr(settings, 'zyte_api_key', SecretStr('fake'))
    monkeypatch.setattr(settings, 'zyte_organization_id', org_id)
    calls = []
    def fake(url, key):
        calls.append(url)
        if failure:
            raise RuntimeError('secret credential fake must not leak')
        return response(url)
    monkeypatch.setattr(zyte, 'extract', fake)
    result = zyte.run_one()
    assert result['state'] == ('failed' if failure else 'success')
    assert zyte.run_one()['state'] == 'idle'
    assert len(calls) == 1
    with session_scope() as s:
        job, run = s.get(BrowserLinkJob, job_id), s.get(Run, result['run_id'])
        assert s.get(Run, old_id).status == RunStatus.suspended
        if failure:
            assert job.result_run_id == old_id
            assert 'secret credential' not in run.error_message
        else:
            assert job.result_run_id == run.id
            assert json.loads(run.metrics)['provider'] == 'zyte'
            artifacts = s.scalars(select(HuntxDriveArtifact).where(HuntxDriveArtifact.result_run_id == run.id)).all()
            assert {a.filename.rsplit('.', 1)[-1] for a in artifacts} == {'jpg', 'json'}
    monkeypatch.setattr(settings, 'zyte_daily_limit', 1)
    assert zyte.run_one()['state'] == 'daily_limit'
