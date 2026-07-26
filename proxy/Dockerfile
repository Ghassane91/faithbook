FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends squid squidclient ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY squid.conf /etc/squid/squid.conf

EXPOSE 3128

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD squidclient -h 127.0.0.1 -p 3128 mgr:info >/dev/null 2>&1 || exit 1

CMD ["/bin/sh", "-c", "rm -f /run/squid.pid && exec squid --foreground -f /etc/squid/squid.conf"]

