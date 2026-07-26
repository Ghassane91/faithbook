from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_backend_non_publie_sur_hote():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    backend = compose.split("\n  frontend:", 1)[0].split("\n  backend:", 1)[1]
    assert "\n    ports:" not in backend
    assert '- "8000"' in backend


def test_proxy_bloque_reseaux_prives_et_metadata():
    config = (ROOT / "proxy" / "squid.conf").read_text(encoding="utf-8")
    for network in ("127.0.0.0/8", "10.0.0.0/8", "169.254.0.0/16", "192.168.0.0/16"):
        assert network in config
    assert "http_access deny blocked_ipv4" in config


def test_proxy_supprime_pid_perime_avant_demarrage():
    # Apres un redemarrage brutal (ex. Docker Desktop), l'ancien fichier
    # /run/squid.pid persiste dans le systeme de fichiers du conteneur. Squid
    # le trouve, croit qu'une instance tourne deja, et boucle en crash-restart.
    dockerfile = (ROOT / "proxy" / "Dockerfile").read_text(encoding="utf-8")
    assert "rm -f /run/squid.pid" in dockerfile
    # exec est necessaire pour que squid devienne PID 1 et recoive les
    # signaux Docker (sinon /bin/sh reste PID 1 et squid ignore SIGTERM).
    assert "exec squid" in dockerfile
