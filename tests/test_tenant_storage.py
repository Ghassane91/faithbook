from app.models import Target
from app.services.capture import organization_folder, profile_dir


def test_dossier_de_capture_est_separe_par_organisation():
    first = Target(
        name="Première",
        url="https://example.com/",
        run_time="09:00",
        organization_id=12,
    )
    second = Target(
        name="Seconde",
        url="https://example.com/",
        run_time="09:00",
        organization_id=34,
    )

    assert organization_folder(first) == "organization-12"
    assert organization_folder(second) == "organization-34"
    assert organization_folder(first) != organization_folder(second)


def test_profils_persistants_sont_separes_par_organisation():
    first = profile_dir("facebook", 12)
    second = profile_dir("facebook", 34)

    assert first != second
    assert first.parts[-4:] == ("organizations", "12", "profiles", "facebook")
