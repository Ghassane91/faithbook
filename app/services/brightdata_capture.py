"""Bounded, opt-in Bright Data fallback for finished HuntX merchant jobs.

Never forwards HuntX login cookies. A durable reservation permits at most
one two-request provider attempt per job, including after a process crash.
"""
import base64
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.database import session_scope
from app.models import (BrowserDevice, BrowserLinkJob, BrowserTarget, Organization,
                        Run, RunLog, RunStatus, Target, TriggerType, utcnow)
from app.services.browser_links import public_url, product_binding_valid
from app.services.browser_schedule import ZONE, aware
from app.services import quotas

logger = logging.getLogger(__name__)


def api_key():
    value = settings.brightdata_api_key.get_secret_value().strip()
    if value:
        return value
    try:
        return Path(settings.brightdata_api_key_file).read_text().strip()
    except OSError:
        return ""


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.title, self.hidden, self.in_title = [], [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
        if self.in_title:
            self.title.append(data)


def provider_request(client, payload, key):
    with client.stream('POST', 'https://api.brightdata.com/request',
                       headers={'Authorization': f'Bearer {key}'}, json=payload) as response:
        if response.status_code != 200:
            raise ValueError(f'Bright Data HTTP {response.status_code}.')
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > 25_000_000:
                raise ValueError('Réponse Bright Data trop volumineuse.')
        return bytes(body)


def extract(url, key):
    # Two separately billed calls; reserve both before making either request.
    import re
    zone = settings.brightdata_zone.strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', zone):
        raise ValueError('Zone Web Unlocker manquante ou invalide.')
    payload = {'zone': zone, 'url': public_url(url), 'format': 'json', 'render': 'true'}
    with httpx.Client(timeout=180, follow_redirects=False, trust_env=False) as client:
        document = json.loads(provider_request(client, payload, key))
        if not isinstance(document, dict) or document.get('status_code') != 200:
            raise ValueError('Page Bright Data indisponible.')
        html = document.get('body')
        if not isinstance(html, str):
            raise ValueError('Contenu HTML Bright Data absent.')
        result = {'url': url, 'browserHtml': html, 'statusCode': 200}
        validate_page(result, url)
        png = provider_request(client, dict(payload, format='raw', data_format='screenshot'), key)
        if not png.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Image PNG Bright Data absente.')
        result['screenshot'] = base64.b64encode(png).decode('ascii')
        return result


def validate_page(response, expected):
    from app.api.browser_capture import image_bytes, merchant_refused
    from app.services.web_challenges import detect_challenge
    final = public_url(response.get('url', ''), resolve=False)
    if urlsplit(final).netloc != urlsplit(expected).netloc or urlsplit(final).scheme != urlsplit(expected).scheme:
        raise ValueError('Redirection Bright Data hors du site prévu.')
    page = PageText()
    page.feed(response.get('browserHtml', ''))
    text, title = ' '.join(page.parts).strip(), ''.join(page.title).strip()
    if detect_challenge(title, text) or 'click the button below to continue shopping' in text.lower():
        raise ValueError('Vérification humaine encore présente dans la réponse Bright Data.')
    if merchant_refused(title, text):
        raise ValueError('Accès toujours refusé par le marchand.')
    import re
    if re.search(r'page not found|404\s*[-:]?\s*not found|page introuvable|couldn[’\x27]t find (?:this|that|the) page', title + '\n' + text, re.I):
        raise ValueError('Lien mort dans la réponse Bright Data.')
    if response.get('statusCode', 200) >= 400 or len(text) < 50:
        raise ValueError('Contenu Bright Data incomplet ou indisponible.')
    return final, title[:500], text[:100000]


def validate_response(response, expected):
    from app.api.browser_capture import image_bytes
    final, title, text = validate_page(response, expected)
    return final, title, text, image_bytes(response.get('screenshot', ''))


def run_one(job_id=None, include_unavailable=False):
    # Retesting a recorded 404 requires a specifically selected administrative job.
    if include_unavailable and job_id is None:
        raise ValueError('Une fiche précise est requise pour revérifier un lien indisponible.')
    from app.services import brightdata_browser
    key = api_key() if settings.brightdata_enabled else ''
    unlocker_ready = bool(key and settings.brightdata_zone.strip())
    browser_ready = settings.brightdata_browser_enabled and brightdata_browser.configured()
    if not settings.brightdata_enabled or not settings.brightdata_organization_id or not (unlocker_ready or browser_ready):
        return {'state': 'disabled'}
    now = utcnow()
    day = now.astimezone(ZONE).date().isoformat()
    day_start = datetime.fromisoformat(day).replace(tzinfo=ZONE).astimezone(timezone.utc)
    with session_scope() as session:
        # Serialize reservations and the daily allowance across worker processes.
        organization = session.scalar(select(Organization).where(
            Organization.id == settings.brightdata_organization_id).with_for_update())
        if not organization:
            return {'state': 'disabled'}
        used = session.scalar(select(func.count(Run.id)).join(Target).where(
            Target.organization_id == organization.id, Run.started_at >= day_start,
            Run.started_at < day_start + timedelta(days=1),
            Run.idempotency_key.like('brightdata:%')))
        if used * 2 + 2 > settings.brightdata_daily_limit:
            return {'state': 'daily_limit'}
        jobs = session.scalars(select(BrowserLinkJob).join(Target, Target.id == BrowserLinkJob.target_id)
            .where(Target.organization_id == organization.id, BrowserLinkJob.finished_at.is_not(None))
            .order_by(BrowserLinkJob.id)).all()
        chosen = None
        for job in jobs:
            if job_id is not None and job.id != job_id:
                continue
            previous = session.get(Run, job.result_run_id) if job.result_run_id else None
            eligible = (RunStatus.failed, RunStatus.suspended, RunStatus.skipped) if include_unavailable else (RunStatus.failed, RunStatus.suspended)
            if not previous or previous.status not in eligible:
                continue
            # Zyte has priority. Never race its in-flight or not-yet-attempted job.
            if not include_unavailable and settings.zyte_enabled and settings.zyte_organization_id == organization.id:
                prior = session.scalar(select(Run).where(Run.idempotency_key == f'zyte:job:{job.id}'))
                if not prior or prior.status not in (RunStatus.failed, RunStatus.suspended):
                    continue
            target = session.get(Target, job.target_id)
            use_browser = brightdata_browser.eligible(target.url)
            if (use_browser and not browser_ready) or (not use_browser and not unlocker_ready):
                continue
            if use_browser:
                browser_used = session.scalar(select(func.count(Run.id)).join(Target).where(
                    Target.organization_id == organization.id, Run.started_at >= day_start,
                    Run.started_at < day_start + timedelta(days=1),
                    Run.idempotency_key.like('brightdata:job:%:browser-api')))
                if browser_used >= settings.brightdata_browser_daily_limit:
                    continue
            marker = f'brightdata:job:{job.id}' + (':browser-api' if use_browser else '')
            if session.scalar(select(Run.id).where(Run.idempotency_key == marker)):
                continue
            task = session.get(BrowserTarget, job.target_id)
            target = session.get(Target, job.target_id)
            device = session.get(BrowserDevice, task.device_id) if task else None
            source = session.get(Run, job.source_run_id)
            if (not task or not device or not device.active or device.organization_id != organization.id
                    or not target.enabled or not product_binding_valid(session, task, device)
                    or not source or source.target_id != task.source_target_id
                    or (task.lease_until and aware(task.lease_until) > now)):
                continue
            public_url(target.url)
            quotas.enforce_capture_creation(session, organization.id)
            run = Run(target_id=target.id, status=RunStatus.running, trigger=TriggerType.scheduled,
                      capture_date=day, idempotency_key=marker, attempts=1,
                      metrics=json.dumps({'provider': 'brightdata', 'reserved_requests': 2,
                                          'engine': 'browser_api' if use_browser else 'web_unlocker'}), drive_status='local')
            session.add(run)
            session.flush()
            # Finished jobs stay invisible to Chrome while the provider is running.
            chosen = (job.id, run.id, target.url, organization.id, use_browser)
            session.commit()
            break
    if chosen is None:
        return {'state': 'idle'}
    job_id, run_id, url, org_id, use_browser = chosen
    path = None
    try:
        result = brightdata_browser.extract(url) if use_browser else extract(url, key)
        final, title, text, data = validate_response(result, url)
        captured = utcnow()
        with session_scope() as session:
            job, run = session.get(BrowserLinkJob, job_id), session.get(Run, run_id)
            target = session.get(Target, job.target_id)
            task = session.get(BrowserTarget, job.target_id)
            device = session.get(BrowserDevice, task.device_id)
            if (not target.enabled or target.organization_id != org_id or not device.active
                    or device.organization_id != org_id or not product_binding_valid(session, task, device)):
                raise ValueError('Configuration HuntX modifiée pendant la capture Bright Data.')
            quotas.enforce_capture_size(session, org_id, len(data), run_id=run.id)
            run.capture_date = captured.astimezone(ZONE).date().isoformat()
            path = Path(settings.screenshot_dir) / f'organization-{org_id}' / run.capture_date / f'brightdata-{run.id}.jpg'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            run.status, run.finished_at = RunStatus.success, captured
            run.final_url, run.page_title, run.body_text = final, title, text
            run.screenshot_path, run.screenshot_bytes = str(path), len(data)
            run.content_sha256 = hashlib.sha256(data).hexdigest()
            run.metrics = json.dumps({'provider': 'brightdata', 'captured_at': captured.isoformat(),
                                     'reserved_requests': 2, 'engine': 'browser_api' if use_browser else 'web_unlocker',
                                     'quality': ('HTML et image de la même session ; chargement des images contrôlé.' if use_browser else
                                                 'HTML et image issus de deux requêtes distinctes ; contrôle visuel requis.')})
            job.result_run_id, job.finished_at = run.id, captured
            from app.services.huntx_drive import register_product_artifacts
            register_product_artifacts(session, job, run)
            session.add(RunLog(run_id=run.id, step='brightdata', message='Capture de secours Bright Data reçue et mise en file Drive.'))
            session.commit()
        return {'state': 'success', 'run_id': run_id}
    except Exception as exc:
        if path:
            path.unlink(missing_ok=True)
        # Only controlled validation messages are persisted; arbitrary HTTP exceptions
        # can contain credentials or provider response bodies.
        message = str(exc) if isinstance(exc, ValueError) else 'Erreur technique Bright Data ; consulter la configuration et le quota fournisseur.'
        with session_scope() as session:
            run = session.get(Run, run_id)
            run.status, run.finished_at, run.error_message = RunStatus.failed, utcnow(), message[:300]
            session.add(RunLog(run_id=run.id, step='brightdata', level='WARNING', message=run.error_message))
            session.commit()
        return {'state': 'failed', 'run_id': run_id}


def scheduled_fallback():
    try:
        run_one()
    except Exception:
        logger.warning('Bright Data : reprise interrompue avant la capture ; vérifier la configuration.')
