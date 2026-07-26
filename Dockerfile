# Image officielle Playwright : Chromium et toutes ses dependances systeme
# sont deja installes, et la version doit correspondre a celle du requirements.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Ecran virtuel de la connexion manuelle noVNC. Defini au niveau du conteneur
    # (et pas seulement exporte dans l'entrypoint) pour etre herite par TOUS les
    # process, y compris le worker uvicorn qui lance le navigateur headful.
    DISPLAY=:99

WORKDIR /app

# curl/tzdata + pile d'affichage virtuel pour la connexion manuelle noVNC :
#   xvfb       : ecran virtuel
#   x11vnc     : serveur VNC sur cet ecran
#   novnc      : client VNC dans le navigateur
#   websockify : pont WebSocket entre noVNC et le VNC
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl tzdata xvfb x11vnc novnc websockify \
    && rm -rf /var/lib/apt/lists/*

# Python systeme de l'image (gere par la distribution, d'ou --break-system-packages) :
# c'est celui pour lequel Chromium est deja installe dans /ms-playwright.
COPY requirements.txt .
# --ignore-installed : la pile d'affichage (novnc/websockify) a tire des paquets
# python3-* de la distribution que pip ne peut pas desinstaller. On installe donc
# nos versions epinglees dans /usr/local (qui a la priorite sur le sys.path) sans
# toucher aux paquets geres par apt.
RUN pip install --break-system-packages --ignore-installed -r requirements.txt

COPY alembic.ini .
COPY pytest.ini .
COPY migrations ./migrations
COPY app ./app
COPY tests ./tests
COPY scripts ./scripts
# Artefacts lus par les tests d'exploitation Phase 1c. Ils sont copiés dans
# l'image afin que la même suite pytest fonctionne sur l'hôte et dans Docker.
COPY Dockerfile ./Dockerfile
COPY .github/workflows/ci.yml ./.github/workflows/ci.yml
# Ces deux fichiers sont lus par les tests de securite du deploiement. Ils sont
# copies en lecture seule dans l'image afin que la meme commande pytest
# fonctionne en local et dans le conteneur.
COPY docker-compose.yml ./docker-compose.yml
COPY proxy/squid.conf ./proxy/squid.conf
COPY proxy/Dockerfile ./proxy/Dockerfile
# Lu par les tests d'exploitation exécutés depuis /app dans le conteneur.
# La seconde copie est l'entrypoint réellement exécuté.
COPY docker-entrypoint.sh ./docker-entrypoint.sh
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p /data/screenshots /secrets

EXPOSE 8000 6080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
