from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import (
    Base,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Run,
    RunStatus,
    Target,
    TriggerType,
    User,
)
from app.services.auth import hash_password
from app.services.legacy_migration import copy_sqlite_database


def test_copie_sqlite_conserve_utilisateur_organisation_et_role(tmp_path):
    source_path = tmp_path / "legacy.db"
    source_engine = create_engine(f"sqlite:///{source_path}", future=True)
    target_engine = create_engine(f"sqlite:///{tmp_path / 'target.db'}", future=True)
    Base.metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)

    with Session(source_engine) as session:
        user = User(
            email="migration@example.com",
            password_hash=hash_password("Mot2Passe-Migration"),
        )
        session.add(user)
        session.flush()
        organization = Organization(
            name="Organisation migrée",
            slug="organisation-migree",
            created_by_user_id=user.id,
        )
        session.add(organization)
        session.flush()
        session.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=MembershipRole.owner,
            )
        )
        session.commit()

    copied = copy_sqlite_database(source_path, target_engine)

    with Session(target_engine) as session:
        assert copied == 3
        assert session.scalar(select(func.count()).select_from(User)) == 1
        membership = session.scalars(select(OrganizationMembership)).one()
        assert membership.role == MembershipRole.owner

    source_engine.dispose()
    target_engine.dispose()


def test_copie_sqlite_accepte_une_ancienne_table_runs(tmp_path):
    source_path = tmp_path / "legacy-old.db"
    source_engine = create_engine(f"sqlite:///{source_path}", future=True)
    target_engine = create_engine(f"sqlite:///{tmp_path / 'target-new.db'}", future=True)
    Base.metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)

    with Session(source_engine) as session:
        target = Target(
            name="Ancienne cible",
            url="https://example.com/",
            run_time="09:00",
        )
        session.add(target)
        session.flush()
        session.add(
            Run(
                target_id=target.id,
                trigger=TriggerType.manual,
                capture_date="2026-07-25",
                status=RunStatus.success,
            )
        )
        session.commit()

    # Simule ensuite une base v1.5.2, antérieure aux colonnes de suivi Drive
    # v1.6.0. Les lignes existantes restent intactes.
    with source_engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_runs_drive_next_retry_at")
        connection.exec_driver_sql("DROP INDEX ix_runs_drive_status")
        for column in (
            "drive_next_retry_at",
            "drive_uploaded_at",
            "drive_last_error",
            "drive_attempts",
            "drive_status",
        ):
            connection.exec_driver_sql(f"ALTER TABLE runs DROP COLUMN {column}")

    copied = copy_sqlite_database(source_path, target_engine)

    with Session(target_engine) as session:
        run = session.scalars(select(Run)).one()
        assert copied == 2
        assert run.drive_status == "local"
        assert run.drive_attempts == 0

    source_engine.dispose()
    target_engine.dispose()
