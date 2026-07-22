#!/usr/bin/env bash
# Démarre la pile d'affichage virtuel (pour la connexion manuelle noVNC) puis
# l'API. Le navigateur de connexion s'affiche sur DISPLAY=:99, exposé en lecture
# et contrôle via noVNC. Les captures, elles, restent headless.
set -e

export DISPLAY=:99

# Écran virtuel : la résolution couvre le plus grand rendu de capture.
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &

# Laisse le temps à Xvfb de créer le socket.
for _ in $(seq 1 30); do
    [ -e /tmp/.X11-unix/X99 ] && break
    sleep 0.2
done

# Serveur VNC sur l'écran virtuel. Mot de passe obligatoire s'il est fourni :
# sans mot de passe, on n'écoute qu'en local (accès uniquement via le proxy).
VNC_OPTS="-display :99 -forever -shared -rfbport 5900 -noxdamage -quiet"
if [ -n "${VNC_PASSWORD:-}" ]; then
    mkdir -p /tmp/vnc
    x11vnc -storepasswd "${VNC_PASSWORD}" /tmp/vnc/passwd >/dev/null 2>&1
    VNC_OPTS="${VNC_OPTS} -rfbauth /tmp/vnc/passwd"
else
    VNC_OPTS="${VNC_OPTS} -localhost -nopw"
fi
x11vnc ${VNC_OPTS} >/tmp/x11vnc.log 2>&1 &

# noVNC : sert le client web et pont WebSocket -> VNC.
websockify --web /usr/share/novnc "${NOVNC_PORT:-6080}" localhost:5900 \
    >/tmp/novnc.log 2>&1 &

exec "$@"
