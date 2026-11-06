"""Archivage HuntX durable, indépendant du stockage principal des captures.

L'enregistrement ne fait aucun appel réseau. Le planificateur reprend les
envois Drive ; les fichiers locaux restent disponibles après une panne ou un
redémarrage, et les noms incluant le run évitent les doublons lors d'une reprise.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from app.config import settings
from app.database import session_scope
from app.models import (
    BrowserLinkJob, BrowserTarget, HuntxDriveArtifact, Organization,
    Run, RunLog, RunStatus, Target, utcnow,
)
from app.services.drive import drive_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArtifactRetryStats:
    selected: int = 0
    uploaded: int = 0
    failed: int = 0


def safe_name(value: str, limit: int = 180) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", value)
    return re.sub(r"\s+", " ", value).strip(" .")[:limit] or "sans-nom"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _row(item: dict, fallback: str) -> tuple[str, str]:
    row_id = str(item.get("id") or "").strip()
    product = " ".join(str(item.get(k) or "").strip() for k in ("marque", "modele")).strip()
    old_name = Path(str(item.get("nom") or "")).stem
    key = row_id or "label-" + _digest(product or old_name or fallback)
    label = "Ligne " + (row_id or "sans identifiant")
    if product or old_name:
        label += " - " + (product or old_name)
    return key[:200], safe_name(label, 200)


def _source(session, source_run_id: int) -> tuple[Run, Target, Organization]:
    run = session.get(Run, source_run_id)
    target = session.get(Target, run.target_id) if run else None
    organization = session.get(Organization, target.organization_id) if target and target.organization_id else None
    if not run or not target or not organization:
        raise ValueError("Exécution HuntX ou organisation introuvable pour l'archivage.")
    return run, target, organization


def _captured_date(item: dict, target: Target, fallback: str) -> str:
    """La date de la photo fait foi, même si une reprise Drive a lieu plus tard."""
    stamp = item.get("captured_at")
    if stamp:
        try:
            moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if moment.tzinfo:
                return moment.astimezone(ZoneInfo(target.timezone_name or settings.timezone)).date().isoformat()
        except (ValueError, TypeError, KeyError):
            pass
    # Les anciens payloads ont uniquement la date locale fournie par le runner.
    return date.fromisoformat(fallback).isoformat()


def _directory(organization_id: int, run_id: int, capture_date: str) -> Path:
    directory = Path(settings.screenshot_dir) / f"organization-{organization_id}" / "huntx" / capture_date / f"run-{run_id}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _register(session, **fields) -> HuntxDriveArtifact:
    existing = session.scalar(select(HuntxDriveArtifact).where(HuntxDriveArtifact.dedupe_key == fields["dedupe_key"]))
    if existing:
        return existing
    artifact = HuntxDriveArtifact(**fields)
    session.add(artifact)
    session.flush()
    return artifact


def _write_json(path: Path, payload: dict) -> None:
    # Une reprise de la même exécution conserve le document original.
    if not path.is_file():
        _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str, *, encoding: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding=encoding) as output:
            temporary = Path(output.name)
            output.write(text)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _copy_local(original: Path, path: Path) -> None:
    """Une interruption ne laisse pas une image partielle prête à envoyer."""
    if not _has_file(original) or _has_file(path):
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
        shutil.copy2(original, temporary)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _has_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def register_source_artifacts(session, source_run_id: int, lignes: list[dict],
                              prix: list[dict], capture_date: str) -> list[HuntxDriveArtifact]:
    """Conserve images, métadonnées de chaque ligne et CSV avant l'envoi Drive."""
    session.scalar(select(Run).where(Run.id == source_run_id).with_for_update())
    source, target, organization = _source(session, source_run_id)
    # La date du run décrit l'extraction ; chaque photo peut préciser son heure.
    first_capture = next((item for item in [*(prix or []), *(lignes or [])] if item.get("captured_at")), {})
    source_date = _captured_date(first_capture, target, source.capture_date or capture_date)
    artifacts: list[HuntxDriveArtifact] = []
    rows: dict[str, dict] = {}
    for index, item in enumerate(prix or []):
        key, label = _row(item, f"prix-{index}")
        rows[key] = {"key": key, "label": label, "metadata": dict(item), "images": []}
    for index, item in enumerate(lignes or []):
        key, label = _row(item, f"ligne-{index}")
        row = rows.setdefault(key, {"key": key, "label": label, "metadata": {}, "images": []})
        row["metadata"].update({k: item[k] for k in ("id", "marque", "modele", "nom", "captured_at", "capture_error") if k in item})
        row["images"].append(item)

    for row in rows.values():
        key, label, metadata = row["key"], row["label"], row["metadata"]
        row_date = _captured_date(metadata, target, source_date)
        directory = _directory(organization.id, source.id, row_date)
        images = []
        for index, image in enumerate(row["images"]):
            image_date = _captured_date(image, target, row_date)
            image_filename = f"Ligne-{safe_name(key, 60)}-run-{source.id}-{index + 1}.jpg"
            image_path = _directory(organization.id, source.id, image_date) / image_filename
            _copy_local(Path(str(image.get("fichier") or "")), image_path)
            # Un échec de photo a son manifeste de statut ; il ne crée pas
            # une file d'envoi perpétuelle pour un JPG qui n'a jamais existé.
            if _has_file(image_path):
                images.append((index, image_date, image_filename, image_path))
        filename = f"Ligne-{safe_name(key, 60)}-run-{source.id}.json"
        path = directory / filename
        _write_json(path, {
            "source_run_id": source.id, "capture_date": row_date,
            "row_id": metadata.get("id"), "marque": metadata.get("marque", ""),
            "modele": metadata.get("modele", ""), "nom": metadata.get("nom", ""),
            "captured_at": metadata.get("captured_at"), "cellules": metadata.get("cellules", {}),
            "row_capture_available": bool(images),
            "capture_error": metadata.get("capture_error") or (None if images else "Capture de ligne absente pour cette exécution."),
        })
        artifacts.append(_register(session, source_run_id=source.id, result_run_id=None,
            dedupe_key=f"source:{source.id}:row:{_digest(key)}:json", capture_date=row_date,
            row_key=key, row_label=label, kind="row", marketplace=None,
            local_path=str(path), filename=filename))
        for index, image_date, filename, path in images:
            artifacts.append(_register(session, source_run_id=source.id, result_run_id=None,
                dedupe_key=f"source:{source.id}:row:{_digest(key)}:jpg:{index}", capture_date=image_date,
                row_key=key, row_label=label, kind="row", marketplace=None,
                local_path=str(path), filename=filename))

    if prix:
        from app.services.fiches_liens import tableau_prix
        filename = f"HuntX-prix-{source_date}-run-{source.id}.csv"
        path = _directory(organization.id, source.id, source_date) / filename
        if not path.is_file():
            _write_text(path, tableau_prix(prix, source_date), encoding="utf-8-sig")
        artifacts.append(_register(session, source_run_id=source.id, result_run_id=None,
            dedupe_key=f"source:{source.id}:price", capture_date=source_date, row_key=None,
            row_label=None, kind="price", marketplace=None, local_path=str(path), filename=filename))
    return artifacts


def _marketplace(reference: dict, run: Run, target: Target) -> str:
    from app.services.fiches_liens import Lien
    return safe_name(Lien(str(reference.get("marque") or ""), str(reference.get("modele") or ""),
                          str(reference.get("colonne") or ""),
                          str(reference.get("url") or run.final_url or target.url)).marketplace, 140)


def register_product_artifacts(session, job: BrowserLinkJob, run: Run) -> list[HuntxDriveArtifact]:
    """Une capture partagée est archivée dans chacune de ses lignes d'origine.

Un résultat bloqué reçoit un document de statut explicite, jamais une image
anti-robot présentée comme une fiche produit réussie.
    """
    source, parent, organization = _source(session, job.source_run_id)
    target = session.get(Target, run.target_id)
    binding = session.get(BrowserTarget, job.target_id)
    if (not target or target.organization_id != organization.id or run.target_id != job.target_id
            or not binding or binding.source_target_id != parent.id):
        raise ValueError("Résultat produit hors de l'organisation ou de la source HuntX.")
    capture_date = date.fromisoformat(run.capture_date).isoformat()
    try:
        references = json.loads(job.row_references or "[]")
    except (TypeError, ValueError):
        references = []
    references = [item for item in references if isinstance(item, dict)] if isinstance(references, list) else []
    if not references:
        references = [{"nom": f"Fiche {job.id} - ligne non identifiée"}]
    artifacts: list[HuntxDriveArtifact] = []
    seen = set()
    try:
        run_metrics = json.loads(run.metrics or "{}")
    except (TypeError, ValueError):
        run_metrics = {}
    captured_at = run_metrics.get("captured_at") if isinstance(run_metrics, dict) else None
    captured_at = captured_at or (run.finished_at.isoformat() if run.finished_at else None)
    for reference in references:
        key, label = _row(reference, f"job-{job.id}")
        marketplace = _marketplace(reference, run, target)
        identity = _digest(key + "|" + marketplace)
        if identity in seen:
            continue
        seen.add(identity)
        directory = _directory(organization.id, source.id, capture_date)
        stem = f"Fiche-{safe_name(key, 50)}-job-{job.id}-run-{run.id}-{identity[:8]}"
        status_path = directory / (stem + ".json")
        status = run.status.value if isinstance(run.status, RunStatus) else str(run.status)
        image_path = None
        filename = None
        if status == "success" and run.screenshot_path:
            original = Path(run.screenshot_path)
            filename = stem + (original.suffix.lower() or ".jpg")
            # Une seule copie locale sert toutes les lignes partageant l'URL.
            path = directory / f"Capture-job-{job.id}-run-{run.id}{original.suffix.lower() or '.jpg'}"
            _copy_local(original, path)
            if _has_file(path):
                image_path = path
        _write_json(status_path, {
            "source_run_id": source.id, "result_run_id": run.id, "job_id": job.id,
            "capture_date": capture_date, "captured_at": captured_at,
            "row_id": reference.get("id"), "marque": reference.get("marque", ""),
            "modele": reference.get("modele", ""), "marketplace": marketplace,
            "url": reference.get("url") or target.url, "final_url": run.final_url,
            "status": status, "capture_available": bool(image_path),
            "reason": run.error_message or run.skipped_reason or ("Capture locale absente pour cette exécution." if status == "success" and not image_path else None),
            "quality": run_metrics.get("quality") if isinstance(run_metrics, dict) else None,
        })
        artifacts.append(_register(session, source_run_id=source.id, result_run_id=run.id,
            dedupe_key=f"product:{job.id}:{run.id}:{identity}:json", capture_date=capture_date,
            row_key=key, row_label=label, kind="product", marketplace=marketplace,
            local_path=str(status_path), filename=status_path.name))
        if image_path:
            artifacts.append(_register(session, source_run_id=source.id, result_run_id=run.id,
                dedupe_key=f"product:{job.id}:{run.id}:{identity}:image", capture_date=capture_date,
                row_key=key, row_label=label, kind="product", marketplace=marketplace,
                local_path=str(image_path), filename=filename))
    return artifacts


def folder_names(session, artifact: HuntxDriveArtifact) -> tuple[str, ...]:
    _, _, organization = _source(session, artifact.source_run_id)
    # L'identifiant fait partie du nom même si deux organisations portent le
    # même libellé ou que celui-ci contient des caractères transformés.
    names = [f"{safe_name(organization.name, 100)} [org-{organization.id}]", "HuntX", artifact.capture_date]
    if artifact.row_label:
        names.append(artifact.row_label)
    if artifact.kind == "product" and artifact.marketplace:
        names.append(artifact.marketplace)
    return tuple(names)


def retry_due_artifacts() -> ArtifactRetryStats:
    """Réessaie sans refaire les photos ni supprimer les fichiers locaux."""
    if not drive_client.is_configured():
        return ArtifactRetryStats()
    now = utcnow()
    selected = uploaded = failed = 0
    attempted: set[int] = set()
    folder_cache: dict[tuple[str | None, str], str] = {}
    for _ in range(max(1, settings.google_drive_retry_batch_size)):
        with session_scope() as session:
            artifact = session.scalar(select(HuntxDriveArtifact).where(
                HuntxDriveArtifact.drive_status.in_(["pending", "failed"]),
                or_(HuntxDriveArtifact.next_retry_at.is_(None), HuntxDriveArtifact.next_retry_at <= now),
                HuntxDriveArtifact.id.not_in(attempted),
            ).order_by(HuntxDriveArtifact.id).limit(1).with_for_update(skip_locked=True))
            if artifact is None:
                break
            attempted.add(artifact.id)
            selected += 1
            artifact.attempts = (artifact.attempts or 0) + 1
            try:
                path = Path(artifact.local_path)
                if not path.is_file() or not path.stat().st_size:
                    raise FileNotFoundError(f"Fichier HuntX introuvable ou vide : {path}")
                names = folder_names(session, artifact)
                folder = settings.google_drive_parent_folder_id or None
                for name in names:
                    key = (folder, name)
                    if key not in folder_cache:
                        folder_cache[key] = drive_client.ensure_folder(name, folder)
                    folder = folder_cache[key]
                result = drive_client.upload(path, folder, artifact.filename)
                artifact.drive_folder_id = result.folder_id
                artifact.drive_file_id = result.file_id
                artifact.drive_file_link = result.web_link
                artifact.drive_status = "uploaded"
                artifact.last_error = None
                artifact.next_retry_at = None
                artifact.uploaded_at = utcnow()
                uploaded += 1
            except Exception as exc:  # noqa: BLE001 - une panne d'un fichier n'arrête pas les autres
                # Un dossier déplacé/supprimé peut rendre son ID invalide :
                # après une erreur, le prochain fichier le recherche à nouveau.
                folder_cache.clear()
                artifact.drive_status = "failed"
                artifact.last_error = str(exc)[:2000]
                delay = min(360, max(1, settings.google_drive_retry_minutes) * 2 ** min(artifact.attempts - 1, 6))
                artifact.next_retry_at = utcnow() + timedelta(minutes=delay)
                session.add(RunLog(run_id=artifact.source_run_id, step="huntx-drive", level="WARNING",
                    message=f"Envoi Drive à reprendre ({artifact.filename}) : {artifact.last_error}"))
                failed += 1
    if selected:
        logger.info("Archivage HuntX Drive : %d sélectionnés, %d envoyés, %d à reprendre", selected, uploaded, failed)
    return ArtifactRetryStats(selected, uploaded, failed)
