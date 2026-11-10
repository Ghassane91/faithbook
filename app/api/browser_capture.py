from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_organization, organization_admin
from app.config import settings
from app.database import get_session
from app.models import (BrowserDevice, BrowserTarget, BrowserLinkJob, MembershipRole, Organization,
                        OrganizationMembership, Run, RunLog, RunStatus, Target, TriggerType, User, utcnow)
from app.services import quotas
from app.services.browser_schedule import SITES, ZONE, aware, due_slot, next_slot
from app.services.web_challenges import detect_challenge
from app.services.browser_links import public_url, product_binding_valid

router = APIRouter(prefix="/api/browser-capture", tags=["Chrome personnel"])
MAX_BODY = 17_000_000
MAX_PRODUCT_ATTEMPTS = 3
ERRORS = {"challenge": "Vérification humaine requise dans Chrome.",
          "navigation": "La page n'a pas pu être chargée dans Chrome.",
          "capture": "Capture Chrome impossible ou contenu non exploitable."}
# Résultats qui ne sont pas des échecs de FaithBook : ils restent visibles avec
# leur motif (statut « skipped »), sans être comptés comme des échecs.
REFUSED = "Refusé par le marchand : accès bloqué pour ce navigateur (aucun contournement tenté)."
DEAD_LINK = "Lien mort (404) : à corriger dans HuntX."
GONE = "Produit retiré par le marchand : lien à mettre à jour dans HuntX."
GONE_PAGE = re.compile(r"no longer available online|(?:product|item) is no longer available|(?:product|item) has been discontinued", re.I)


def same_site(expected, final):
    """Même domaine, avec ou sans www ; le passage http -> https est admis."""
    bare = lambda host: (host or '').lower().removeprefix('www.')
    return (bool(final.hostname) and bare(final.hostname) == bare(expected.hostname)
            and final.port in (None, 80, 443)
            and (final.scheme == expected.scheme or (expected.scheme == 'http' and final.scheme == 'https')))
REFUSED_PAGE = re.compile(r"\baccess denied\b|you don['’]t have permission to access|errors\.edgesuite\.net|\b403 forbidden\b", re.I)


def merchant_refused(title, text):
    """Page de refus du marchand (Akamai « Access Denied », 403), pas un défi humain."""
    return bool(REFUSED_PAGE.search(title or "")) or (len(text or "") < 1500 and bool(REFUSED_PAGE.search(text or "")))


@router.get("/extension")
def extension_download(context=Depends(organization_admin)):
    root = Path(__file__).resolve().parents[2] / "chrome-extension"
    files = ["manifest.json", "policy.mjs", "worker.js", "options.html", "options.js", "options.css"]
    if not all((root / name).is_file() for name in files):
        raise HTTPException(503, "Extension absente de cette image serveur.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(root / name, name)
    return Response(output.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": 'attachment; filename="faithbook-chrome.zip"'})


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def device_auth(authorization: str = Header(default=""), session: Session = Depends(get_session)):
    if not authorization.startswith("Bearer ") or len(authorization) > 200:
        raise HTTPException(401, "Appairage Chrome requis.")
    device = session.scalar(select(BrowserDevice).where(
        BrowserDevice.token_hash == digest(authorization[7:])).with_for_update())
    if not device or not device.active or aware(device.expires_at) <= utcnow():
        raise HTTPException(401, "Appairage Chrome expiré ou révoqué.")
    user = session.get(User, device.user_id)
    membership = session.scalar(select(OrganizationMembership).where(
        OrganizationMembership.user_id == device.user_id,
        OrganizationMembership.organization_id == device.organization_id))
    if not user or not user.is_active or not membership or membership.role not in (MembershipRole.owner, MembershipRole.admin):
        raise HTTPException(403, "L'administrateur de cet appareil n'a plus accès.")
    device.last_seen_at = utcnow()
    return device


class DeviceIn(BaseModel):
    name: str = Field(default="Mon Chrome", min_length=1, max_length=100)


@router.get("/devices")
def devices(context=Depends(current_organization), session: Session = Depends(get_session)):
    result = []
    for device in session.scalars(select(BrowserDevice).where(BrowserDevice.organization_id == context.organization.id)):
        tasks = []
        for task in session.scalars(select(BrowserTarget).where(BrowserTarget.device_id == device.id)):
            target = session.get(Target, task.target_id)
            run = session.get(Run, task.last_run_id) if task.last_run_id else None
            tasks.append({"target_id": target.id, "name": target.name, "url": target.url,
                          "enabled": target.enabled, "last_run_id": task.last_run_id,
                          "status": run.status if run else None, "error": run.error_message if run else None,
                          "source_target_id": task.source_target_id})
        result.append({"id": device.id, "name": device.name, "active": device.active,
                       "expires_at": device.expires_at, "last_seen_at": device.last_seen_at,
                       "next_at": next_slot(utcnow()) if device.active else None, "targets": tasks})
    return result


@router.get('/zyte')
def zyte_status(context=Depends(organization_admin)):
    from app.services.zyte_capture import api_key
    scoped = settings.zyte_organization_id == context.organization.id
    return {'enabled': scoped and settings.zyte_enabled,
            'configured': scoped and bool(api_key()),
            'daily_limit': settings.zyte_daily_limit if scoped else None,
            'mode': 'fallback', 'attempts_per_link': 1}


@router.get('/archive')
def archive(context=Depends(current_organization), session: Session = Depends(get_session)):
    """Latest HuntX batch and its durable Drive exports, scoped to this tenant."""
    from app.models import HuntxDriveArtifact
    sources = []
    for target in session.scalars(select(Target).where(
            Target.organization_id == context.organization.id, Target.capture_row_links.is_(True))):
        source_run = session.scalar(select(Run).where(Run.target_id == target.id).order_by(Run.id.desc()).limit(1))
        if not source_run:
            continue
        summary = dict(source_target_id=target.id, source_name=target.name, source_run_id=source_run.id,
                       capture_date=source_run.capture_date, total=0, captured=0, pending=0,
                       unavailable=0, failed=0, drive_total=0, drive_uploaded=0,
                       drive_pending=0, drive_failed=0, folders=[], errors=[])
        for job in session.scalars(select(BrowserLinkJob).where(BrowserLinkJob.source_run_id == source_run.id)):
            summary['total'] += 1
            run = session.get(Run, job.result_run_id) if job.result_run_id else None
            if job.finished_at is None:
                key = 'pending'
            elif run and run.status == RunStatus.success:
                key = 'captured'
            elif run and run.status == RunStatus.failed:
                key = 'failed'
            else:
                key = 'unavailable'
            summary[key] += 1
            if run and key in ('failed', 'unavailable') and len(summary['errors']) < 20:
                product = session.get(Target, job.target_id)
                summary['errors'].append(dict(target_name=product.name,
                    message=run.error_message or run.skipped_reason or 'Capture absente.'))
        folders = set()
        for artifact in session.scalars(select(HuntxDriveArtifact).where(HuntxDriveArtifact.source_run_id == source_run.id)):
            summary['drive_total'] += 1
            key = 'drive_uploaded' if artifact.drive_status == 'uploaded' else 'drive_failed' if artifact.drive_status == 'failed' else 'drive_pending'
            summary[key] += 1
            if artifact.drive_folder_id and artifact.row_label:
                folder = (artifact.capture_date, artifact.row_label, artifact.drive_folder_id)
                folders.add(folder)
        summary['folders'] = [dict(date=day, row_label=label, url=f'https://drive.google.com/drive/folders/{folder_id}')
                              for day, label, folder_id in sorted(folders)[:12]]
        sources.append(summary)
    return {'sources': sources}


@router.post("/devices", status_code=201)
def create_device(payload: DeviceIn, context=Depends(organization_admin), session: Session = Depends(get_session)):
    session.scalar(select(Organization).where(Organization.id == context.organization.id).with_for_update())
    if session.scalar(select(BrowserDevice.id).where(BrowserDevice.organization_id == context.organization.id, BrowserDevice.active.is_(True))):
        raise HTTPException(409, "Un Chrome est déjà lié. Révoquez-le avant un nouvel appairage.")
    token = secrets.token_urlsafe(32)
    device = BrowserDevice(organization_id=context.organization.id, user_id=context.user.id,
                           name=payload.name, token_hash=digest(token), expires_at=utcnow() + timedelta(days=365))
    session.add(device)
    session.flush()
    for name, url in SITES.items():
        try:
            quotas.enforce_target_creation(session, context.organization.id)
        except quotas.QuotaExceeded as exc:
            raise HTTPException(409, str(exc)) from None
        target = Target(organization_id=context.organization.id, name=f"Chrome · {name.title()}",
                        url=url, enabled=True, full_page=True, timezone_name="Africa/Casablanca",
                        cron_expression="0 9 1,15 * *", wait_until="domcontentloaded")
        session.add(target)
        session.flush()
        session.add(BrowserTarget(target_id=target.id, device_id=device.id))
    session.commit()
    return {"id": device.id, "token": token, "expires_at": device.expires_at}


def owned_device(session, device_id, context):
    device = session.scalar(select(BrowserDevice).where(BrowserDevice.id == device_id,
        BrowserDevice.organization_id == context.organization.id).with_for_update())
    if not device:
        raise HTTPException(404, "Appareil introuvable.")
    return device


@router.post("/devices/{device_id}/revoke")
def revoke(device_id: int, context=Depends(organization_admin), session: Session = Depends(get_session)):
    device = owned_device(session, device_id, context)
    device.active = False
    for task in session.scalars(select(BrowserTarget).where(BrowserTarget.device_id == device.id)):
        session.get(Target, task.target_id).enabled = False
    session.commit()
    return {"revoked": True}


def request_test(session, device):
    if not device.active:
        raise HTTPException(409, "Appareil révoqué.")
    for task in session.scalars(select(BrowserTarget).where(BrowserTarget.device_id == device.id)):
        if task.source_target_id:
            continue  # HuntX products are queued by a fresh source capture.
        # Un clic répété ne remplace ni une demande ni une capture en cours.
        if not task.manual_key:
            task.manual_key = "test-" + secrets.token_hex(12)
    session.commit()
    return {"queued": True}


@router.post("/devices/{device_id}/test")
def test_device(device_id: int, context=Depends(organization_admin), session: Session = Depends(get_session)):
    return request_test(session, owned_device(session, device_id, context))


def requeue_failed_products(session, device):
    """Retry technical failures, retaining every previous Run and idempotency key."""
    now = utcnow()
    queued = 0
    jobs = session.scalars(select(BrowserLinkJob).join(BrowserTarget, BrowserTarget.target_id == BrowserLinkJob.target_id)
        .where(BrowserTarget.device_id == device.id, BrowserLinkJob.finished_at.is_not(None))).all()
    for job in jobs:
        binding = session.get(BrowserTarget, job.target_id)
        previous = session.get(Run, job.result_run_id) if job.result_run_id else None
        if (not previous or previous.status != RunStatus.failed
                or not product_binding_valid(session, binding, device)
                or (binding.lease_until and aware(binding.lease_until) > now)):
            continue
        # Legacy results predate attempt_count. The first slot remains reserved
        # for their historical result, so the next slot must be distinct.
        job.attempt_count = max(job.attempt_count, previous.attempts or 1)
        if job.attempt_count >= MAX_PRODUCT_ATTEMPTS:
            continue
        job.finished_at, job.next_attempt_at = None, now
        session.add(RunLog(run_id=job.source_run_id, step='fiches', level='INFO',
                           message=f'Reprise technique de la fiche #{job.id} ; historique #{previous.id} conservé.'))
        queued += 1
    return {'queued': queued}


@router.post('/devices/{device_id}/retry-products')
def retry_products(device_id: int, context=Depends(organization_admin), session: Session = Depends(get_session)):
    device = owned_device(session, device_id, context)
    if not device.active:
        raise HTTPException(409, 'Appareil révoqué.')
    summary = requeue_failed_products(session, device)
    session.commit()
    return summary


@router.post("/test")
def extension_test(device=Depends(device_auth), session: Session = Depends(get_session)):
    return request_test(session, device)


@router.post("/claim")
def claim(device=Depends(device_auth), session: Session = Depends(get_session),
          x_faithbook_capture_version: str = Header(default="1")):
    now = utcnow()
    scheduled = due_slot(now, device.created_at)
    for task in session.scalars(select(BrowserTarget).where(BrowserTarget.device_id == device.id).order_by(BrowserTarget.target_id)):
        target = session.get(Target, task.target_id)
        if not target.enabled or target.organization_id != device.organization_id:
            continue
        if task.source_target_id:
            if x_faithbook_capture_version != '2' or not product_binding_valid(session, task, device):
                continue
            queued = session.scalar(select(BrowserLinkJob).where(BrowserLinkJob.target_id == task.target_id,
                BrowserLinkJob.finished_at.is_(None)).order_by(BrowserLinkJob.id))
            if not queued:
                continue
            if queued.next_attempt_at and aware(queued.next_attempt_at) > now:
                continue
            source_run = session.get(Run, queued.source_run_id)
            if not source_run or source_run.target_id != task.source_target_id:
                continue
            try:
                public_url(target.url)
            except (ValueError, OSError):
                queued.finished_at = now
                session.add(RunLog(run_id=queued.source_run_id, step='fiches', level='WARNING',
                    message=f'Chrome : lien #{queued.id} devenu inaccessible ou non public ; aucune navigation.'))
                continue
            slot = f'link-{queued.id}' + (f'-a{queued.attempt_count + 1}' if queued.attempt_count else '')
        else:
            if target.url not in SITES.values():
                continue
            slot = task.manual_key or (scheduled if scheduled != task.completed_slot else None)
        if not slot or (task.lease_until and aware(task.lease_until) > now):
            continue
        nonce = secrets.token_urlsafe(24)
        task.lease_key, task.lease_hash = slot, digest(nonce)
        task.lease_until = now + timedelta(minutes=10)
        session.commit()
        return {"job": {"target_id": target.id, "url": target.url, "slot": slot, "lease": nonce,
                        "kind": "product" if task.source_target_id else "homepage"},
                "next_at": next_slot(now)}
    session.commit()
    return {"job": None, "next_at": next_slot(now)}


class ResultIn(BaseModel):
    target_id: int
    slot: str = Field(max_length=40)
    lease: str = Field(max_length=64)
    status: Literal["success", "challenge", "navigation", "capture"]
    final_url: str = Field(default="", max_length=2048)
    title: str = Field(default="", max_length=500)
    text: str = Field(default="", max_length=100000)
    image: str = Field(default="", max_length=16_000_000)
    # Extension 1.2 : raison précise d'un échec et vue de l'écran au moment de l'échec.
    reason: str = Field(default="", max_length=300)
    diagnostic_image: str = Field(default="", max_length=4_000_000)
    captured_at: datetime | None = None


def image_bytes(value):
    try:
        raw = base64.b64decode(value, validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ("PNG", "JPEG") or min(image.size) < 100:
                raise ValueError()
            pixels = image.width * image.height
            if pixels > 24_000_000:
                # Chrome screenshots can have twice the CSS resolution on HiDPI
                # displays. JPEG draft downsamples during decoding, before loading
                # the pixels, rather than allocating the full high-resolution image.
                if image.format != 'JPEG' or pixels > 96_000_000:
                    raise ValueError()
                factor = 2
                while pixels // (factor * factor) > 24_000_000:
                    factor *= 2
                image.draft('RGB', (image.width // factor, image.height // factor))
                if image.width * image.height > 24_000_000:
                    raise ValueError()
                import logging
                logging.getLogger(__name__).info('Capture JPEG HiDPI normalisÃ©e avant dÃ©codage : %s x %s.', image.width, image.height)
            image.load()
            output = io.BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=85)
            return output.getvalue()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(422, "Image invalide ou trop grande.") from None


async def _receive_result(request: Request, device, session: Session):
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > MAX_BODY:
            raise HTTPException(413, "Capture trop volumineuse.")
        body.extend(part)
    try:
        payload = ResultIn.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Résultat de capture invalide.") from None
    task = session.get(BrowserTarget, payload.target_id)
    if not task or task.device_id != device.id:
        raise HTTPException(404, "Cible introuvable.")
    # Authentifier aussi les répétitions ; le nonce d'une ancienne tâche ne peut
    # pas déposer une image sur une tâche réattribuée.
    if not task.lease_hash or not secrets.compare_digest(task.lease_hash, digest(payload.lease)) or task.lease_key != payload.slot:
        raise HTTPException(409, "Réservation remplacée.")
    if task.last_result_key == payload.slot:
        return {"run_id": task.last_run_id, "duplicate": True}
    if not task.lease_until or aware(task.lease_until) < utcnow():
        raise HTTPException(409, "Réservation expirée.")
    target = session.get(Target, task.target_id)
    if not target.enabled or target.organization_id != device.organization_id:
        raise HTTPException(409, "Cible modifiée ou désactivée.")
    product_job = None
    if task.source_target_id:
        if not product_binding_valid(session, task, device) or not payload.slot.startswith('link-'):
            raise HTTPException(409, "Source HuntX modifiée ou désactivée.")
        try:
            product_job = session.get(BrowserLinkJob, int(payload.slot[5:].split('-')[0]))
        except ValueError:
            pass
        source_run = session.get(Run, product_job.source_run_id) if product_job else None
        if not product_job or product_job.target_id != target.id or not source_run or source_run.target_id != task.source_target_id:
            raise HTTPException(409, "Fiche HuntX introuvable.")
    elif target.url not in SITES.values():
        raise HTTPException(409, "Cible modifiée ou désactivée.")
    data = None
    captured_at = utcnow()
    if payload.captured_at is not None:
        stamp = payload.captured_at
        # Preserve the day of the screenshot if the outbox crosses midnight.
        # Accept a small clock skew, but never a date outside this reservation.
        if (stamp.tzinfo is None or stamp > captured_at + timedelta(minutes=2)
                or stamp < aware(task.lease_until) - timedelta(minutes=12)):
            raise HTTPException(422, "Horodatage de capture hors de la réservation.")
        captured_at = stamp
    state = payload.status
    missing_page = bool(re.search(r"(?:couldn['’]t|cannot|can['’]t) find (?:this|that|the) page|page not found|404\s*[-:]?\s*not found|couldn['’]t be found|page (?:does not|doesn't) exist|page introuvable", payload.title + '\n' + payload.text, re.I))
    product_gone = bool(GONE_PAGE.search(payload.text[:20000]))
    if state == "success":
        final = urlsplit(payload.final_url)
        expected = urlsplit(target.url)
        if not same_site(expected, final) or final.username or final.password:
            raise HTTPException(422, "La capture doit rester sur le site prévu.")
        if detect_challenge(payload.title, payload.text) or "click the button below to continue shopping" in payload.text.lower():
            state = "challenge"
        elif merchant_refused(payload.title, payload.text):
            state = "capture"
        elif missing_page:
            state = 'navigation'
        elif product_gone:
            state = 'capture'
        elif len(payload.text.strip()) < 50 or "something went wrong" in payload.text.lower():
            state = "capture"
        else:
            data = image_bytes(payload.image)
    skipped_reason = None
    if not data and state != "challenge":
        if merchant_refused(payload.title, payload.text):
            skipped_reason = REFUSED
        elif missing_page:
            skipped_reason = DEAD_LINK
        elif product_gone:
            skipped_reason = GONE
    try:
        quotas.enforce_capture_creation(session, device.organization_id)
        run = Run(target_id=target.id, status=RunStatus.success if data else
                  (RunStatus.suspended if state == "challenge" else
                   RunStatus.skipped if skipped_reason else RunStatus.failed),
                  trigger=TriggerType.manual if payload.slot.startswith("test-") else TriggerType.scheduled,
                  capture_date=captured_at.astimezone(ZONE).date().isoformat(),
                  idempotency_key=f"chrome:{target.id}:{payload.slot}", attempts=(product_job.attempt_count + 1) if product_job else 1,
                  finished_at=utcnow(), page_title=payload.title, final_url=payload.final_url,
                  metrics=json.dumps({'captured_at': captured_at.isoformat(), 'quality': payload.reason}, ensure_ascii=False),
                  body_text=payload.text, drive_status="pending" if data and settings.storage_backend == "google_drive" else "local",
                  skipped_reason=skipped_reason,
                  error_message=None if data or skipped_reason else (
                      ERRORS.get(state, ERRORS["capture"]) + (f" Détail : {payload.reason}" if payload.reason else "")))
        session.add(run)
        session.flush()
        if data:
            quotas.enforce_capture_size(session, device.organization_id, len(data), run_id=run.id)
    except quotas.QuotaExceeded as exc:
        raise HTTPException(409, str(exc)) from None
    path = None
    try:
        if data:
            path = Path(settings.screenshot_dir) / f"organization-{device.organization_id}" / run.capture_date / f"chrome-{run.id}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            run.screenshot_path, run.screenshot_bytes = str(path), len(data)
            run.content_sha256 = hashlib.sha256(data).hexdigest()
        elif payload.diagnostic_image and not skipped_reason:
            # Image de diagnostic d'un échec : conservée à part, jamais comptée comme capture.
            try:
                diag = image_bytes(payload.diagnostic_image)
            except HTTPException:
                diag = None
            if diag:
                path = Path(settings.screenshot_dir) / f"organization-{device.organization_id}" / run.capture_date / f"chrome-{run.id}-diagnostic.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(diag)
                run.diagnostic_path = str(path)
        session.add(RunLog(run_id=run.id, step="chrome",
                           message=("Capture reçue du Chrome appairé." + (f' Qualité : {payload.reason}' if payload.reason else '')) if data else (run.skipped_reason or run.error_message),
                           level="WARNING" if data and payload.reason else "INFO" if data or skipped_reason else "WARNING"))
        task.last_result_key, task.last_run_id = payload.slot, run.id
        task.lease_until = None
        if product_job:
            product_job.result_run_id = run.id
            product_job.attempt_count += 1
            retryable = (not data and not skipped_reason and state in ('capture', 'navigation')
                         and 'redirection' not in payload.reason.lower())
            if retryable and product_job.attempt_count < MAX_PRODUCT_ATTEMPTS:
                product_job.next_attempt_at = utcnow() + timedelta(minutes=1)
            else:
                product_job.finished_at = utcnow()
                product_job.next_attempt_at = None
            from app.services.huntx_drive import register_product_artifacts
            register_product_artifacts(session, product_job, run)
            session.add(RunLog(run_id=product_job.source_run_id, step='fiches', level='INFO' if data else 'WARNING',
                message=f'Chrome : {target.name} — {run.status.value}, exécution #{run.id}, tentative {product_job.attempt_count}/{MAX_PRODUCT_ATTEMPTS}.'
                        + (' Reprise automatique programmée.' if product_job.next_attempt_at else '')))
        elif payload.slot.startswith("test-"):
            task.manual_key = None
        else:
            task.completed_slot = payload.slot
        session.commit()
    except Exception:
        session.rollback()
        if path:
            path.unlink(missing_ok=True)
        raise
    return {"run_id": run.id, "status": run.status}


@router.post("/result")
async def result(request: Request, device=Depends(device_auth), session: Session = Depends(get_session)):
    try:
        return await _receive_result(request, device, session)
    except HTTPException as exc:
        if exc.status_code == 422:
            import logging
            # Controlled server messages only: never log screenshots, tokens or body.
            logging.getLogger(__name__).warning('Chrome rÃ©sultat rejetÃ© (device %s): %s', device.id, exc.detail)
        raise
