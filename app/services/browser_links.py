"""Enqueue public product links from an authenticated HuntX capture."""
import ipaddress
import json
import socket
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from app.models import BrowserDevice, BrowserTarget, BrowserLinkJob, Target, Run, RunLog, utcnow
from app.services import quotas


def public_url(value: str, *, resolve: bool = True) -> str:
    url = urlsplit(value.strip())
    host = (url.hostname or '').lower()
    if (url.scheme not in ('https', 'http') or url.username or url.password
            or url.port not in (None, 80, 443) or len(value) > 2048
            or '.' not in host or host.endswith(('.local', '.internal', '.localhost', '.test', '.invalid'))
            or host == 'localhost' or '\\' in value):
        raise ValueError('Lien produit non public ou invalide.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('Les liens produits doivent utiliser un nom de domaine public.')
    if resolve:
        addresses = socket.getaddrinfo(host, url.port or (443 if url.scheme == 'https' else 80))
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError('Le domaine ne pointe pas exclusivement vers Internet.')
    return urlunsplit((url.scheme, url.netloc.lower(), url.path or '/', url.query, ''))


def product_binding_valid(session, task, device):
    parent = session.get(Target, task.source_target_id) if task.source_target_id else None
    return bool(parent and parent.enabled and parent.capture_row_links
                and parent.organization_id == device.organization_id)


def enqueue_links(session, source_run_id: int, links: list[dict]):
    run = session.get(Run, source_run_id)
    source = session.get(Target, run.target_id) if run else None
    if not source or not source.enabled or not source.capture_row_links:
        return None
    device = session.scalar(select(BrowserDevice).where(
        BrowserDevice.organization_id == source.organization_id, BrowserDevice.active.is_(True)).with_for_update())
    if not device:
        return None
    accepted, rejected, grouped = [], [], {}
    # One browser visit per URL, but retain every HuntX row and column which
    # points to it. A category page can legitimately belong to many cameras.
    for item in links:
        raw = str(item.get('url') or '').strip()
        grouped.setdefault(raw, []).append({
            key: str(item.get(key) or '') for key in ('id', 'marque', 'modele', 'colonne', 'url')
        })
    # Validate every distinct URL, without marketplace exclusions or filename deduplication.
    for raw, references in grouped.items():
        item = references[0]
        try:
            url = public_url(raw)
        except (ValueError, OSError) as exc:
            rejected.append(f'{raw[:180]} : {str(exc)[:160]}')
            continue
        binding = session.scalar(select(BrowserTarget).join(Target, Target.id == BrowserTarget.target_id).where(
            BrowserTarget.device_id == device.id, BrowserTarget.source_target_id == source.id, Target.url == url))
        if not binding:
            quotas.enforce_target_creation(session, source.organization_id)
            label = ' · '.join(str(item.get(k) or '').strip() for k in ('marque', 'modele', 'colonne')).strip(' ·')
            target = Target(organization_id=source.organization_id, name=('HuntX · ' + (label or urlsplit(url).hostname))[:200],
                            url=url, enabled=True, full_page=True, timezone_name='Africa/Casablanca', tags='huntx,chrome,fiche-produit')
            session.add(target)
            session.flush()
            binding = BrowserTarget(target_id=target.id, device_id=device.id, source_target_id=source.id)
            session.add(binding)
            session.flush()
        job = session.scalar(select(BrowserLinkJob).where(BrowserLinkJob.target_id == binding.target_id,
                                                       BrowserLinkJob.source_run_id == run.id))
        if not job:
            job = BrowserLinkJob(target_id=binding.target_id, source_run_id=run.id)
            session.add(job)
            session.flush()
        existing = json.loads(job.row_references or '[]')
        keyed = {json.dumps(ref, sort_keys=True, ensure_ascii=False): ref for ref in existing + references}
        job.row_references = json.dumps(list(keyed.values()), ensure_ascii=False)
        accepted.append(job.id)
    # Une nouvelle campagne remplace les fiches encore en attente des campagnes
    # précédentes : sinon elles s'empilent et chaque lien est capturé plusieurs fois.
    replaced = 0
    if accepted:
        for old in session.scalars(select(BrowserLinkJob).join(
                BrowserTarget, BrowserTarget.target_id == BrowserLinkJob.target_id).where(
                BrowserTarget.source_target_id == source.id, BrowserLinkJob.source_run_id != run.id,
                BrowserLinkJob.finished_at.is_(None))):
            old.finished_at, old.next_attempt_at = utcnow(), None
            replaced += 1
    if replaced:
        session.add(RunLog(run_id=run.id, step='fiches', level='INFO',
            message=f'{replaced} fiche(s) en attente des campagnes précédentes remplacée(s) par cette campagne.'))
    session.add(RunLog(run_id=run.id, step='fiches', level='INFO',
        message=f'Chrome personnel : {len(set(accepted))} fiche(s) en file, {len(rejected)} lien(s) non admissible(s). PC et Chrome doivent rester ouverts.'))
    for reason in rejected:
        session.add(RunLog(run_id=run.id, step='fiches', level='WARNING', message=reason))
    return {'queued': len(set(accepted)), 'rejected': len(rejected)}
