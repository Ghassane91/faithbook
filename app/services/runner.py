from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import session_scope
from app.models import (
    Account,
    AccountStatus,
    Organization,
    Run,
    RunLog,
    RunStatus,
    Target,
    TriggerType,
    utcnow,
)
from app.services import crypto, drive_sync, pagination, quotas, run_queue
from app.services import ai_summary, extraction_diff, extraction_store
from app.services.capture import (
    SessionExpired,
    build_filename,
    capture_page,
    image_change_ratio,
    legacy_thumb_path,
    make_thumbnail,
    organization_folder,
    site_label,
    slugify,
    diff_lignes,
    text_change_ratio,
    thumb_path,
)
from app.services.notify import (
    notify_change,
    notify_extraction,
    notify_failure,
    notify_session_suspended,
)
from app.services.session_check import encrypted_state_to_storage
from app.services.ssrf import UrlRejected

logger = logging.getLogger(__name__)

# Une seule capture a la fois : Chromium est gourmand, et cela evite
# deux executions concurrentes sur la meme cible.
_capture_semaphore = asyncio.Semaphore(1)
_running_targets: set[int] = set()


class DuplicateRun(Exception):
    """Une execution reussie existe deja pour cette cible et cette date."""


def target_tz(target: Target) -> ZoneInfo:
    try:
        return ZoneInfo(target.timezone_name or settings.timezone)
    except Exception:  # fuseau invalide -> repli UTC
        logger.warning("Fuseau invalide pour la cible %s, repli sur UTC", target.id)
        return ZoneInfo("UTC")


def local_now(target: Target) -> datetime:
    return datetime.now(target_tz(target))


def log_step(
    session: Session, run: Run, step: str, message: str, level: str = "INFO", attempt: int | None = None
) -> None:
    session.add(
        RunLog(run_id=run.id, step=step, message=message, level=level, attempt=attempt)
    )
    session.commit()
    logger.log(
        getattr(logging, level, logging.INFO),
        "run=%s target=%s step=%s %s",
        run.id,
        run.target_id,
        step,
        message,
    )


def find_existing_success(session: Session, target_id: int, capture_date: str) -> Run | None:
    return session.scalars(
        select(Run)
        .where(
            Run.target_id == target_id,
            Run.capture_date == capture_date,
            Run.status == RunStatus.success,
        )
        .order_by(Run.id.desc())
        .limit(1)
    ).first()


def find_by_hash(session: Session, target_id: int, sha256: str) -> Run | None:
    return session.scalars(
        select(Run)
        .where(
            Run.target_id == target_id,
            Run.content_sha256 == sha256,
            Run.status == RunStatus.success,
        )
        .order_by(Run.id.desc())
        .limit(1)
    ).first()


def create_run(
    session: Session, target: Target, trigger: TriggerType, capture_date: str
) -> Run:
    run = Run(
        target_id=target.id,
        trigger=trigger,
        capture_date=capture_date,
        status=RunStatus.pending,
        idempotency_key=f"{target.id}:{capture_date}:{trigger.value}:{utcnow().timestamp():.0f}",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


async def execute_run(run_id: int, force: bool = False) -> None:
    """Execute une capture de bout en bout : Playwright -> disque -> Drive.

    Chaque etape est journalisee. En cas d'echec, on reessaie avec un backoff
    exponentiel jusqu'a MAX_ATTEMPTS avant de marquer l'execution en echec.
    """
    async with _capture_semaphore:
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is None:
                logger.error("Execution %s introuvable", run_id)
                return
            target = session.get(Target, run.target_id)
            if target is None:
                run.status = RunStatus.failed
                run.error_message = "Cible supprimee"
                run.finished_at = utcnow()
                return

            run.status = RunStatus.running
            session.commit()
            log_step(session, run, "start", f"Demarrage pour {target.url}")

            # --- Deduplication (avant tout travail couteux) ---------------
            if not force and settings.dedupe_mode in ("per_day", "both"):
                existing = find_existing_success(session, target.id, run.capture_date)
                if existing and existing.id != run.id:
                    run.status = RunStatus.skipped
                    run.skipped_reason = (
                        f"Capture deja reussie le {run.capture_date} (execution #{existing.id})"
                    )
                    run.drive_file_id = existing.drive_file_id
                    run.drive_file_link = existing.drive_file_link
                    run.drive_folder_id = existing.drive_folder_id
                    run.drive_status = existing.drive_status
                    run.drive_attempts = existing.drive_attempts
                    run.drive_last_error = existing.drive_last_error
                    run.drive_uploaded_at = existing.drive_uploaded_at
                    run.drive_next_retry_at = existing.drive_next_retry_at
                    run.finished_at = utcnow()
                    run.duration_ms = _elapsed_ms(run)
                    log_step(session, run, "dedupe", run.skipped_reason)
                    return

            started = datetime.now(timezone.utc)
            last_error: Exception | None = None

            for attempt in range(1, settings.max_attempts + 1):
                run.attempts = attempt
                session.commit()
                try:
                    await _attempt_once(session, run, target, attempt, force=force)
                    run.status = RunStatus.success
                    run.error_message = None
                    run.finished_at = utcnow()
                    run.duration_ms = int(
                        (datetime.now(timezone.utc) - started).total_seconds() * 1000
                    )
                    session.commit()
                    log_step(
                        session, run, "done", f"Termine en {run.duration_ms} ms", attempt=attempt
                    )
                    return
                except DuplicateRun as exc:
                    run.status = RunStatus.skipped
                    run.skipped_reason = str(exc)
                    run.finished_at = utcnow()
                    run.duration_ms = int(
                        (datetime.now(timezone.utc) - started).total_seconds() * 1000
                    )
                    session.commit()
                    log_step(session, run, "dedupe", str(exc), attempt=attempt)
                    return
                except SessionExpired as exc:
                    # Une reconnexion/2FA ne sera jamais réparée par un retry.
                    run.status = RunStatus.suspended
                    run.session_status = exc.account_status.value
                    run.error_message = str(exc)
                    run.finished_at = utcnow()
                    run.duration_ms = _elapsed_ms(run)
                    account = session.get(Account, target.account_id) if target.account_id else None
                    if account is not None:
                        account.status = exc.account_status
                        account.last_error = str(exc)
                        account.last_verified_at = utcnow()
                    session.commit()
                    log_step(
                        session,
                        run,
                        "suspended",
                        f"Capture suspendue : {exc}",
                        level="WARNING",
                        attempt=attempt,
                    )
                    notify_session_suspended(target, run, account)
                    return
                except UrlRejected as exc:
                    # Condition permanente (SSRF) : reessayer ne changerait rien.
                    run.status = RunStatus.failed
                    run.error_message = f"URL refusee : {exc}"
                    run.finished_at = utcnow()
                    run.duration_ms = _elapsed_ms(run)
                    session.commit()
                    log_step(session, run, "failed", run.error_message, level="ERROR", attempt=attempt)
                    notify_failure(target, run)
                    return
                except quotas.QuotaExceeded as exc:
                    # Un quota ne sera pas réparé par un retry et ne doit pas
                    # consommer plusieurs captures Chromium.
                    run.status = RunStatus.failed
                    run.error_message = str(exc)
                    run.finished_at = utcnow()
                    run.duration_ms = _elapsed_ms(run)
                    session.commit()
                    log_step(
                        session,
                        run,
                        "quota",
                        str(exc),
                        level="ERROR",
                        attempt=attempt,
                    )
                    notify_failure(target, run)
                    return
                except Exception as exc:  # noqa: BLE001 - on journalise tout
                    last_error = exc
                    log_step(
                        session,
                        run,
                        "error",
                        f"Tentative {attempt}/{settings.max_attempts} echouee : {exc}",
                        level="ERROR",
                        attempt=attempt,
                    )
                    if attempt < settings.max_attempts:
                        delay = settings.retry_backoff_seconds * (2 ** (attempt - 1))
                        log_step(
                            session, run, "retry", f"Nouvel essai dans {delay}s", attempt=attempt
                        )
                        await asyncio.sleep(delay)

            run.status = RunStatus.failed
            run.error_message = str(last_error) if last_error else "Echec inconnu"
            run.finished_at = utcnow()
            run.duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            session.commit()
            log_step(
                session,
                run,
                "failed",
                f"Abandon apres {settings.max_attempts} tentatives",
                level="ERROR",
            )
            # Alerte immediate : l'echec ne doit pas passer inapercu.
            notify_failure(target, run)


async def _resume_ia(
    prev: Run,
    result,
    source_url: str | None = None,
) -> str | None:
    """Synthese IA du contenu apparu depuis la capture precedente.

    Desactivee par defaut : sans fournisseur configure on renvoie None sans
    rien tenter, et une panne du service ne fait jamais echouer la capture.
    """
    if not ai_summary.is_configured():
        return None
    ajoutees, retirees = diff_lignes(
        prev.body_text,
        result.body_text,
        source_url,
    )
    if not ajoutees and not retirees:
        return None
    return await asyncio.to_thread(
        ai_summary.resumer_changements, ajoutees, retirees, result.page_title
    )


async def _alertes_extraction(session: Session, run: Run, target: Target, pe, attempt: int) -> None:
    """Compare avec l extraction precedente et alerte en un seul message.

    Premiere extraction d une cible : sert de reference, aucune alerte.
    Page identique (reprise) : rien ne peut avoir change.
    """
    try:
        if pe.reprise:
            return
        avant = extraction_store.precedente(session, target.id, run.id)
        if avant is None or avant.regle != pe.regle:
            return
        evenements = extraction_diff.comparer(
            pe.regle, extraction_store.lignes(avant), extraction_store.lignes(pe)
        )
        if not evenements:
            return
        log_step(
            session, run, "extraction",
            f"{len(evenements)} changement(s) : "
            + " ; ".join(f"{e.ligne} {e.detail}" for e in evenements[:5])[:900],
            attempt=attempt,
        )
        if settings.extraction_alerts_enabled:
            await asyncio.to_thread(notify_extraction, target, run, evenements)
    except Exception:  # noqa: BLE001 - une alerte ne casse jamais une capture
        logger.warning("Comparaison des extractions impossible (run=%s)", run.id, exc_info=True)


def _elapsed_ms(run: Run) -> int:
    end = run.finished_at or utcnow()
    start = run.started_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return int((end - start).total_seconds() * 1000)


async def _attempt_once(
    session: Session, run: Run, target: Target, attempt: int, force: bool
) -> None:
    # --- 1. Capture -------------------------------------------------------
    now = local_now(target)
    stamp = now.strftime("%H%M%S")
    filename = build_filename(target, run.capture_date, stamp)

    # Une racine par organisation, puis un dossier par site. L'API filtre les
    # lignes en base et le disque applique la même séparation physique.
    org_folder_name = organization_folder(target)
    folder_name = site_label(target.url)
    destination = Path(settings.screenshot_dir) / org_folder_name / folder_name
    if target.subfolder:
        destination = destination / slugify(target.subfolder)
    destination = destination / filename

    # Session d'un compte connecté (facultatif) : capture en étant connecté.
    account: Account | None = None
    account_storage = None
    account_profile_slug = None
    if target.account_id:
        account = session.get(Account, target.account_id)
        if account is None:
            raise SessionExpired(
                "Le compte lié est introuvable.",
                AccountStatus.disconnected,
            )
        account_profile_slug = account.profile_slug
        if not account.encrypted_state and not crypto.profile_exists(account.profile_slug):
            raise SessionExpired(
                f"Le compte « {account.name} » n'a aucune session enregistrée.",
                AccountStatus.disconnected,
            )
        if not account.encrypted_state:
            log_step(
                session,
                run,
                "capture",
                f"Compte « {account.name} » chargé depuis son coffre chiffré",
                attempt=attempt,
            )
        else:
            account_storage = encrypted_state_to_storage(account.encrypted_state)
            if account_storage is None and not crypto.profile_exists(account.profile_slug):
                raise SessionExpired(
                    f"Session du compte « {account.name} » illisible.",
                    AccountStatus.disconnected,
                )
            else:
                log_step(session, run, "capture",
                         f"Session du compte « {account.name} » chargée", attempt=attempt)

    log_step(session, run, "capture", f"Ouverture de {target.url}", attempt=attempt)
    result = await capture_page(
        target,
        destination,
        account_storage=account_storage,
        account_profile_slug=account_profile_slug,
    )

    if target.organization_id is not None:
        try:
            quotas.enforce_capture_size(
                session,
                target.organization_id,
                result.size_bytes,
                run_id=run.id,
            )
        except quotas.QuotaExceeded:
            Path(result.path).unlink(missing_ok=True)
            thumb_path(Path(result.path)).unlink(missing_ok=True)
            legacy_thumb_path(Path(result.path)).unlink(missing_ok=True)
            raise

    # Réserver immédiatement les octets dans le run, avant tout commit lié au
    # rafraîchissement d'une session connectée. Un autre worker sérialisé sur
    # l'organisation verra ainsi ce PNG même si ce run est encore "running".
    run.screenshot_path = str(result.path)
    run.screenshot_bytes = result.size_bytes
    run.content_sha256 = result.sha256
    run.page_title = result.page_title
    run.body_text = result.body_text
    run.final_url = result.final_url

    if account is not None and result.storage_state is not None:
        account.encrypted_state = crypto.encrypt_text(json.dumps(result.storage_state))
        account.status = AccountStatus.connected
        account.last_verified_at = utcnow()
        account.last_success_at = utcnow()
        account.last_error = None
        run.session_status = AccountStatus.connected.value
        session.commit()
        log_step(
            session,
            run,
            "session",
            f"Cookies rafraîchis et rescellés pour « {account.name} »",
            attempt=attempt,
        )

    await asyncio.to_thread(make_thumbnail, destination)

    if result.metrics:
        run.metrics = json.dumps(result.metrics)
        libelle = ", ".join(f"{k}={v}" for k, v in result.metrics.items())
        log_step(session, run, "metrics", f"Métriques relevées : {libelle}", attempt=attempt)
    session.commit()
    log_step(
        session,
        run,
        "capture",
        (
            f"Capture OK ({result.size_bytes} octets, sha256={result.sha256[:12]}..., "
            f"défilements={result.scroll_steps}, hauteur={result.document_height or 'inconnue'} px)"
        ),
        attempt=attempt,
    )

    # --- 1bis. Détection de changement vs la capture réussie précédente ---
    prev = session.scalars(
        select(Run)
        .where(
            Run.target_id == target.id,
            Run.id != run.id,
            Run.status == RunStatus.success,
            Run.screenshot_path.is_not(None),
        )
        .order_by(Run.id.desc())
    ).first()
    if prev is not None:
        # La comparaison de texte prime : elle ignore la position des elements,
        # donc un fil reordonne sans contenu nouveau ne compte pas comme un
        # changement. Repli sur les pixels si le texte manque (anciens runs,
        # page sans texte exploitable).
        ratio = text_change_ratio(prev.body_text, result.body_text, target.url)
        if ratio is None and prev.screenshot_path and Path(prev.screenshot_path).exists():
            ratio = await asyncio.to_thread(
                image_change_ratio, Path(prev.screenshot_path), destination
            )
        if ratio is not None:
            run.change_ratio = ratio
            run.changed = ratio >= settings.change_threshold
            session.commit()
            pct = round(ratio * 100, 1)
            if run.changed:
                log_step(session, run, "diff",
                         f"Page modifiée : {pct} % de changement depuis la capture précédente",
                         attempt=attempt)
                run.ai_summary = await _resume_ia(prev, result, target.url)
                if run.ai_summary:
                    session.commit()
                    log_step(session, run, "ia", run.ai_summary, attempt=attempt)
                if settings.notify_on_change:
                    notify_change(target, run, prev)
            else:
                log_step(session, run, "diff",
                         f"Page inchangée ({pct} % de différence)", attempt=attempt)

    # --- 1ter. Extraction IA (produits, prix, forfaits, annonces) ---------
    # Desactivee tant que EXTRACTION_ENABLED=false. Ne fait jamais echouer la
    # capture : une panne laisse simplement cette capture sans extraction.
    pe = await extraction_store.extraire_et_enregistrer_async(session, run, target)
    if pe is not None:
        session.commit()
        log_step(session, run, "extraction", extraction_store.resume(pe), attempt=attempt)
        await _alertes_extraction(session, run, target, pe, attempt)

    # --- 2. Deduplication par contenu ------------------------------------
    if not force and settings.dedupe_mode in ("content_hash", "both"):
        twin = find_by_hash(session, target.id, result.sha256)
        if twin and twin.id != run.id:
            run.drive_file_id = twin.drive_file_id
            run.drive_file_link = twin.drive_file_link
            run.drive_folder_id = twin.drive_folder_id
            run.drive_status = twin.drive_status
            run.drive_attempts = twin.drive_attempts
            run.drive_last_error = twin.drive_last_error
            run.drive_uploaded_at = twin.drive_uploaded_at
            run.drive_next_retry_at = twin.drive_next_retry_at
            # Le PNG doublon est supprimé : il ne doit plus être présenté ni
            # compté dans le stockage de l'organisation.
            run.screenshot_path = None
            run.screenshot_bytes = None
            session.commit()
            destination.unlink(missing_ok=True)
            raise DuplicateRun(
                f"Contenu identique a l'execution #{twin.id} (sha256 {result.sha256[:12]}) "
                "- upload evite"
            )

    # --- 3. Envoi vers Google Drive ou S3 (backend principal, optionnel) --
    if settings.storage_backend not in ("google_drive", "s3"):
        log_step(
            session,
            run,
            "upload",
            f"Enregistré dans '{org_folder_name}/{folder_name}' : {destination}",
            attempt=attempt,
        )
    else:
        run.drive_status = "pending"
        session.commit()
        log_step(
            session,
            run,
            "drive",
            "Préparation du dossier daté et de l'envoi reprenable",
            attempt=attempt,
        )
        try:
            run.drive_attempts = (run.drive_attempts or 0) + 1
            placement = await asyncio.to_thread(
                drive_sync.upload_capture,
                destination,
                target,
                run.capture_date,
                filename,
            )
            drive_sync.mark_success(run, placement)
            session.commit()
            log_step(
                session,
                run,
                "upload",
                (
                    "Fichier déjà présent sur Drive : "
                    if placement.upload.deduplicated
                    else "Envoyé sur Drive : "
                )
                + "/".join(placement.folders)
                + f"/{filename}",
                attempt=attempt,
            )
        except Exception as exc:  # noqa: BLE001
            # La capture locale est réussie et ne doit pas être refaite. La tâche
            # automatique Drive reprendra uniquement cet envoi avec backoff.
            run.drive_attempts = max(0, (run.drive_attempts or 1) - 1)
            drive_sync.mark_failure(run, exc)
            session.commit()
            log_step(
                session,
                run,
                "drive",
                f"Capture conservée localement ; envoi Drive à reprendre : {run.drive_last_error}",
                level="ERROR",
                attempt=attempt,
            )

    # --- 3bis. Copie additionnelle vers Drive (independante du backend) ---
    # N'existe que pour permettre une consultation facile (telephone,
    # tablette) ; ne remplace jamais le backend principal ci-dessus et n'a
    # aucune file de reprise dediee. STORAGE_BACKEND=google_drive envoie deja
    # sur Drive ci-dessus : pas de deuxieme copie dans ce cas.
    if settings.google_drive_dual_write_enabled and settings.storage_backend != "google_drive":
        try:
            organisation = (
                session.get(Organization, target.organization_id)
                if target.organization_id is not None
                else None
            )
            extra = await asyncio.to_thread(
                drive_sync.upload_capture_extra,
                destination,
                target,
                run.capture_date,
                filename,
                organisation.name if organisation is not None else None,
            )
            log_step(
                session,
                run,
                "drive_extra",
                "Copie supplémentaire envoyée sur Drive : "
                + "/".join(extra.folders)
                + f"/{filename}",
                attempt=attempt,
            )
            await _envoyer_pdf_par_ecran(
                session, run, target, destination, filename, attempt, organisation
            )
        except Exception as exc:  # noqa: BLE001
            log_step(
                session,
                run,
                "drive_extra",
                f"Copie Drive supplémentaire échouée (capture conservée par ailleurs) : {exc}",
                level="ERROR",
                attempt=attempt,
            )


async def _envoyer_pdf_par_ecran(
    session: Session,
    run: Run,
    target: Target,
    capture: Path,
    filename: str,
    attempt: int,
    organisation: Organization | None,
) -> None:
    """Depose sur Drive, a cote de la capture, un PDF d'une page par ecran.

    Strictement best-effort et sans effet sur le reste : la capture de
    reference est deja envoyee quand cette fonction est appelee, et un echec
    ici ne fait que produire une ligne de journal.
    """
    if not settings.capture_pdf_pages:
        return
    dossier_temporaire = Path(tempfile.mkdtemp(prefix="faithbook-pdf-"))
    try:
        pdf = dossier_temporaire / (Path(filename).stem + ".pdf")
        pages = await asyncio.to_thread(
            pagination.pdf_par_ecran,
            capture,
            settings.default_viewport_height,
            pdf,
        )
        if pages is None:
            return  # La capture tient sur un ecran : le PDF n'apporterait rien.
        await asyncio.to_thread(
            drive_sync.upload_capture_extra,
            pdf,
            target,
            run.capture_date,
            pdf.name,
            organisation.name if organisation is not None else None,
        )
        log_step(
            session,
            run,
            "drive_extra",
            f"PDF lisible envoyé sur Drive ({pages} pages) : {pdf.name}",
            attempt=attempt,
        )
    except Exception as exc:  # noqa: BLE001
        log_step(
            session,
            run,
            "drive_extra",
            f"PDF lisible non généré (capture inchangée) : {exc}",
            level="ERROR",
            attempt=attempt,
        )
    finally:
        shutil.rmtree(dossier_temporaire, ignore_errors=True)


async def trigger_target(
    target_id: int, trigger: TriggerType, force: bool = False
) -> tuple[int, RunStatus, str]:
    """Cree une execution et la lance en tache de fond. Retourne (run_id, statut, detail)."""
    inline = settings.queue_backend == "inline"
    if inline and target_id in _running_targets:
        raise RuntimeError("Une execution est deja en cours pour cette cible")

    reserved = False
    with session_scope() as session:
        target = session.get(Target, target_id)
        if target is None:
            raise LookupError("Cible introuvable")
        capture_date = local_now(target).strftime("%Y-%m-%d")

        if not force and settings.dedupe_mode in ("per_day", "both"):
            existing = find_existing_success(session, target_id, capture_date)
            if existing:
                return (
                    existing.id,
                    RunStatus.skipped,
                    f"Capture deja realisee aujourd'hui (execution #{existing.id}). "
                    "Utilisez force=true pour relancer.",
                )

        if target.organization_id is not None:
            quotas.enforce_capture_creation(session, target.organization_id)

        if not inline:
            reserved = await asyncio.to_thread(run_queue.reserve_target, target_id)
            if not reserved:
                raise RuntimeError(
                    "Une exécution est déjà en cours ou en attente pour cette cible"
                )
        run = create_run(session, target, trigger, capture_date)
        run_id = run.id

    if not inline:
        try:
            await asyncio.to_thread(
                run_queue.enqueue,
                run_queue.QueuedRun(run_id=run_id, target_id=target_id, force=force),
            )
        except Exception:
            if reserved:
                await asyncio.to_thread(run_queue.release_target, target_id)
            with session_scope() as session:
                failed = session.get(Run, run_id)
                if failed is not None:
                    failed.status = RunStatus.failed
                    failed.error_message = "File d'exécution Redis indisponible"
                    failed.finished_at = utcnow()
            raise RuntimeError("File d'exécution indisponible") from None
        return run_id, RunStatus.pending, "Exécution placée dans la file du worker"

    _running_targets.add(target_id)

    async def _wrapper() -> None:
        try:
            await execute_run(run_id, force=force)
        finally:
            _running_targets.discard(target_id)

    asyncio.create_task(_wrapper())
    return run_id, RunStatus.pending, "Execution lancee"
