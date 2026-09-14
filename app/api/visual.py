from __future__ import annotations

import hashlib
import io
import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.api.deps import current_organization, organization_member
from app.config import settings
from app.database import get_session
from app.models import Organization, VisualAnalysis, Run, Target, RunStatus
from app.services import visual_analysis as vision
from app.services.quotas import organization_usage
from app.services.drive import drive_client

router = APIRouter(prefix="/api/visual", tags=["Analyse des captures"])
TZ = ZoneInfo("Africa/Casablanca")


def owned(session, analysis_id, context):
    row = session.get(VisualAnalysis, analysis_id)
    if not row or row.organization_id != context.organization.id:
        raise HTTPException(404, "Analyse introuvable.")
    return row


def directory(row):
    # Only server-generated UUIDs form storage paths.
    return Path(settings.data_dir) / "visual" / str(row.organization_id) / row.id


def view(row):
    return {"id": row.id, "created_at": row.created_at.isoformat(),
            "question": row.question, "source": row.source, "status": row.status,
            "error": row.error, "archive_status": row.archive_status,
            "archive": json.loads(row.archive_manifest), **json.loads(row.payload)}


@router.get("/config")
def config(context=Depends(current_organization)):
    return {"configured": vision.configured(), "drive_configured": drive_client.is_configured(),
            "provider": settings.visual_analysis_provider,
            "model": settings.visual_analysis_model, "daily_limit": settings.visual_analysis_daily_limit}


@router.get("")
def listing(session: Session = Depends(get_session), context=Depends(current_organization)):
    rows = session.scalars(select(VisualAnalysis)
        .where(VisualAnalysis.organization_id == context.organization.id)
        .order_by(VisualAnalysis.created_at.desc()).limit(50)).all()
    return [view(row) for row in rows]


@router.post("", status_code=201)
def create(question: str = Form(..., min_length=1, max_length=2000),
           source: str = Form(..., min_length=1, max_length=300),
           images: list[UploadFile] = File(...),
           session: Session = Depends(get_session), context=Depends(organization_member)):
    if not vision.configured():
        raise HTTPException(503, "Choisissez un modèle visuel et configurez son accès côté serveur.")
    if not question.strip() or not source.strip() or not 1 <= len(images) <= 4:
        raise HTTPException(422, "Indiquez une question, une source et entre 1 et 4 images.")
    originals, prepared, extensions = [], [], []
    try:
        for upload in images:
            raw = upload.file.read(vision.MAX_BYTES + 1)
            encoded, extension = vision.prepare_image(raw)
            originals.append(raw)
            prepared.append(encoded)
            extensions.append(extension)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        for upload in images:
            upload.file.close()
    now = datetime.now(timezone.utc)
    day_start = now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    # Serialize reservations per organization on PostgreSQL.
    session.execute(select(Organization).where(Organization.id == context.organization.id).with_for_update())
    used = session.scalar(select(func.count()).select_from(VisualAnalysis).where(
        VisualAnalysis.organization_id == context.organization.id,
        VisualAnalysis.created_at >= day_start))
    if used >= max(1, settings.visual_analysis_daily_limit):
        raise HTTPException(429, "Limite quotidienne d'analyses atteinte.")
    # Reserve original bytes plus bounded result/export overhead before writing.
    reservation = sum(map(len, originals)) + 1_000_000
    usage = organization_usage(session, context.organization.id)
    if not usage.storage_bytes.unlimited and usage.storage_bytes.used + reservation > usage.storage_bytes.limit:
        raise HTTPException(429, "Quota de stockage de l'organisation atteint.")
    row = VisualAnalysis(storage_bytes=reservation, id=uuid.uuid4().hex, organization_id=context.organization.id,
        created_at=now, question=question.strip(), source=source.strip(), status="running")
    session.add(row)
    session.commit()
    folder = directory(row)
    try:
        folder.mkdir(parents=True, exist_ok=False)
        sources = []
        for index, (raw, ext) in enumerate(zip(originals, extensions), 1):
            name = f"image-{index}.{ext}"
            (folder / name).write_bytes(raw)
            sources.append({"image": index, "file": name, "sha256": hashlib.sha256(raw).hexdigest()})
        row.payload = json.dumps({"images": sources, "provider": settings.visual_analysis_provider,
                                  "model": settings.visual_analysis_model}, ensure_ascii=False)
        session.commit()
        result = vision.extract(row.question, prepared)
        # Also validate injectable adapters before persistence.
        result = vision.Extraction.model_validate(result).model_dump()
        if any(item["image"] > len(sources) for item in result["items"]):
            raise ValueError("Référence d'image invalide.")
        payload = json.loads(row.payload)
        payload["result"] = result
        row.payload = json.dumps(payload, ensure_ascii=False)
        row.status = "success"
    except Exception:
        # Never disclose provider responses, keys or filesystem details to clients.
        row.status = "failed"
        row.error = "Analyse interrompue ou réponse IA invalide. Les images enregistrées restent disponibles."
    session.commit()
    return view(row)



class RunsInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    run_ids: list[int] = Field(min_length=1, max_length=4)


@router.post("/from-runs", status_code=201)
def from_runs(body: RunsInput, session: Session = Depends(get_session), context=Depends(organization_member)):
    selected = []
    for run_id in body.run_ids:
        run = session.get(Run, run_id)
        target = session.get(Target, run.target_id) if run else None
        if not run or not target or target.organization_id != context.organization.id:
            raise HTTPException(404, "Capture introuvable.")
        if run.status != RunStatus.success or not run.screenshot_path:
            raise HTTPException(409, "Capture non disponible.")
        selected.append((run, target))
    if len({target.id for _, target in selected}) != 1:
        raise HTTPException(422, "Choisissez des captures d'une seule cible.")
    uploads = []
    root = Path(settings.screenshot_dir).resolve()
    try:
        for run, _ in selected:
            path = Path(run.screenshot_path).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise HTTPException(404, "Fichier de capture local indisponible.")
            with path.open("rb") as stream:
                raw = stream.read(vision.MAX_BYTES + 1)
            uploads.append(UploadFile(filename="capture", file=io.BytesIO(raw)))
        response = create(question=body.question, source="cible-" + str(selected[0][1].id),
                          images=uploads, session=session, context=context)
        # Preserve provenance in addition to the copied original's hash.
        row = session.get(VisualAnalysis, response["id"])
        payload = json.loads(row.payload)
        payload["run_ids"] = body.run_ids
        payload["captured_at"] = [run.started_at.isoformat() for run, _ in selected]
        row.payload = json.dumps(payload, ensure_ascii=False)
        session.commit()
        return view(row)
    finally:
        for upload in uploads:
            upload.file.close()


@router.get("/{analysis_id}")
def detail(analysis_id: str, session: Session = Depends(get_session), context=Depends(current_organization)):
    row = owned(session, analysis_id, context)
    if row.status == "running":
        created = row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
        if datetime.now(timezone.utc) - created > timedelta(minutes=10):
            row.status = "failed"
            row.error = "Traitement interrompu. Relancez une nouvelle analyse avec les mêmes images."
            session.commit()
    return view(row)


@router.get("/{analysis_id}/image/{number}")
def image(analysis_id: str, number: int, session: Session = Depends(get_session), context=Depends(current_organization)):
    row = owned(session, analysis_id, context)
    source = next((x for x in json.loads(row.payload).get("images", []) if x["image"] == number), None)
    if not source or not (directory(row) / source["file"]).is_file():
        raise HTTPException(404, "Image indisponible.")
    return FileResponse(directory(row) / source["file"], headers={"Cache-Control": "private, no-store"})


def exports(row):
    data = view(row)
    result = data.get("result")
    if not result:
        raise HTTPException(409, "Analyse non terminée.")
    # Receipts are outside immutable exports: retries produce identical files.
    data.pop("archive", None)
    data.pop("archive_status", None)
    markdown = ("# Analyse des captures\n\nQuestion : " + row.question + "\n\nSource : " + row.source
                + "\n\n" + result["summary"] + "\n\n## Limites\n\n"
                + "\n".join("- " + line for line in result["limitations"])
                + "\n\nLes observations détaillées et leurs sources figurent dans resultats.json et resultats.csv.\n")
    return {"resultats.json": (json.dumps(data, ensure_ascii=False, indent=2), "application/json"),
            "resultats.csv": (vision.csv_export(result), "text/csv"),
            "synthese.md": (markdown, "text/markdown")}


@router.get("/{analysis_id}/export")
def export(analysis_id: str, format: str = Query("json", pattern="^(json|csv|md)$"),
           session: Session = Depends(get_session), context=Depends(current_organization)):
    row = owned(session, analysis_id, context)
    name = "synthese.md" if format == "md" else "resultats." + format
    content, mime = exports(row)[name]
    return Response(content, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"})


@router.get("/{analysis_id}/compare/{before_id}")
def compare(analysis_id: str, before_id: str, session: Session = Depends(get_session), context=Depends(current_organization)):
    after, before = owned(session, analysis_id, context), owned(session, before_id, context)
    if after.source != before.source or before.created_at >= after.created_at:
        raise HTTPException(422, "Choisissez une analyse plus ancienne de la même source.")
    a, b = json.loads(before.payload).get("result"), json.loads(after.payload).get("result")
    if not a or not b:
        raise HTTPException(409, "Les deux analyses doivent être terminées.")
    return {"changes": vision.compare(a, b),
            "note": "Comparaison des observations, à confirmer sur les images. Les références absentes ou ambiguës ne prouvent pas une suppression."}


@router.post("/{analysis_id}/archive")
def archive(analysis_id: str, session: Session = Depends(get_session), context=Depends(organization_member)):
    row = owned(session, analysis_id, context)
    if row.status != "success":
        raise HTTPException(409, "Analyse non terminée.")
    if row.archive_status == "uploaded":
        return view(row)
    if not drive_client.is_configured():
        raise HTTPException(503, "Google Drive n'est pas configuré sur le serveur.")
    now = datetime.now(timezone.utc)
    # Database lease prevents concurrent sends and can recover a stopped process.
    claimed = session.execute(update(VisualAnalysis).where(
        VisualAnalysis.id == row.id,
        (VisualAnalysis.archive_status != "uploading") |
        (VisualAnalysis.archive_started_at < now - timedelta(minutes=10))
    ).values(archive_status="uploading", archive_started_at=now))
    if not claimed.rowcount:
        raise HTTPException(409, "Un envoi est déjà en cours.")
    session.commit()
    session.refresh(row)
    manifest = json.loads(row.archive_manifest)
    try:
        drive_client.check_access()
        if not manifest.get("folder_id"):
            created = row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
            day = drive_client.ensure_folder(created.astimezone(TZ).strftime("%Y-%m-%d"))
            org = drive_client.ensure_folder("organisation-" + str(row.organization_id), day)
            parent = drive_client.ensure_folder("analyse-" + row.id, org)
            manifest["folder_id"] = parent
            row.archive_manifest = json.dumps(manifest)
            session.commit()
        folder = directory(row)
        assets = [(folder / x["file"], {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[x["file"].split(".")[-1]])
                  for x in json.loads(row.payload)["images"]]
        for name, (content, mime) in exports(row).items():
            path = folder / name
            path.write_text(content, encoding="utf-8")
            assets.append((path, mime))
        receipts = manifest.setdefault("files", {})
        for path, mime in assets:
            if path.name in receipts:
                continue
            # Content hash in remote name makes name-based retries unambiguous.
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            uploaded = drive_client.upload(path, manifest["folder_id"],
                filename=f"{path.stem}-{digest[:16]}{path.suffix}", mimetype=mime)
            if not uploaded.file_id:
                raise ValueError("Réception Drive non confirmée.")
            receipts[path.name] = {"id": uploaded.file_id, "sha256": digest}
            row.archive_manifest = json.dumps(manifest)
            session.commit()
        row.archive_status = "uploaded"
        manifest.pop("error", None)
    except Exception:
        row.archive_status = "failed"
        manifest["error"] = "Envoi incomplet. Vérifiez l'accès Drive puis réessayez ; l'analyse IA ne sera pas relancée."
    row.archive_manifest = json.dumps(manifest)
    session.commit()
    return view(row)


@router.delete("/{analysis_id}", status_code=204)
def delete(analysis_id: str, session: Session = Depends(get_session), context=Depends(organization_member)):
    row = owned(session, analysis_id, context)
    if row.status == "running" or row.archive_status == "uploading":
        raise HTTPException(409, "Traitement en cours.")
    folder = directory(row).resolve()
    root = (Path(settings.data_dir) / "visual" / str(row.organization_id)).resolve()
    if folder.parent != root:
        raise HTTPException(409, "Dossier invalide.")
    if folder.is_dir():
        shutil.rmtree(folder)
    session.delete(row)
    session.commit()
