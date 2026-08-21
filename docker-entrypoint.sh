#!/usr/bin/env bash
# Démarre la pile d'affichage virtuel (pour la connexion manuelle noVNC) puis
# l'API. Le navigateur de connexion s'affiche sur DISPLAY=:99, exposé en lecture
# et contrôle via noVNC. Les captures, elles, restent headless.
set -e

export DISPLAY=:99

# Écran virtuel : la résolution couvre le plus grand rendu de capture.
# Un redemarrage du conteneur (docker restart) conserve le systeme de fichiers :
# Xvfb retrouve alors /tmp/.X99-lock et refuse de demarrer (Server is already
# active for display 99), ce qui faisait boucler le conteneur backend. On
# nettoie les verrous residuels avant de lancer l ecran virtuel.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

Xvfb :99 -screen 0 ${XVFB_SCREEN:-1920x1080x24} -nolisten tcp >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!

port_listening() {
    netstat -lnt 2>/dev/null | awk -v port="$1" \
        '$6 == "LISTEN" && $4 ~ (":" port "$") { found=1 } END { exit(found ? 0 : 1) }'
}

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

# Le socket X11 peut exister quelques instants avant que Xvfb accepte réellement
# les connexions. x11vnc échouait alors une seule fois puis disparaissait,
# laissant noVNC actif mais incapable de joindre le port 5900. On relance
# x11vnc jusqu'à ce que le port soit effectivement en écoute.
: > /tmp/x11vnc.log
X11VNC_PID=""
VNC_READY=false
for _ in $(seq 1 60); do
    if ! kill -0 "${XVFB_PID}" 2>/dev/null; then
        echo "Xvfb s'est arrêté avant le démarrage de x11vnc." >&2
        cat /tmp/xvfb.log >&2
        exit 1
    fi
    if [ -z "${X11VNC_PID}" ] || ! kill -0 "${X11VNC_PID}" 2>/dev/null; then
        x11vnc ${VNC_OPTS} >>/tmp/x11vnc.log 2>&1 &
        X11VNC_PID=$!
    fi
    if port_listening 5900; then
        VNC_READY=true
        break
    fi
    sleep 0.25
done

if [ "${VNC_READY}" != "true" ]; then
    echo "Serveur VNC indisponible sur le port 5900." >&2
    cat /tmp/x11vnc.log >&2
    exit 1
fi

# noVNC : sert le client web et pont WebSocket -> VNC.
websockify --web /usr/share/novnc "${NOVNC_PORT:-6080}" localhost:5900 \
    >/tmp/novnc.log 2>&1 &
NOVNC_PID=$!
NOVNC_READY=false
for _ in $(seq 1 40); do
    if port_listening "${NOVNC_PORT:-6080}"; then
        NOVNC_READY=true
        break
    fi
    if ! kill -0 "${NOVNC_PID}" 2>/dev/null; then
        break
    fi
    sleep 0.25
done

if [ "${NOVNC_READY}" != "true" ]; then
    echo "Serveur noVNC indisponible sur le port ${NOVNC_PORT:-6080}." >&2
    cat /tmp/novnc.log >&2
    exit 1
fi

exec "$@"
