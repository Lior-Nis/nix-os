FROM node:22.20.0-bookworm-slim@sha256:b21fe589dfbe5cc39365d0544b9be3f1f33f55f3c86c87a76ff65a02f8f5848e

ARG OPENCODE_VERSION=1.18.29

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        ca-certificates git openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global --no-audit --no-fund "opencode-ai@${OPENCODE_VERSION}" \
    && test "$(opencode --version)" = "${OPENCODE_VERSION}" \
    && rm -f /etc/ssh/ssh_host_* \
    && groupadd --gid 10001 worker \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/sh worker \
    && usermod --password '*' worker \
    && install -d -o worker -g worker -m 0700 /home/worker/.ssh /workspaces \
    && install -d -o root -g root -m 0755 /run/sshd

COPY sshd_config /etc/ssh/sshd_config
COPY opencode.json /etc/opencode/opencode.json
COPY entrypoint.sh /usr/local/bin/specialist-worker-entrypoint

RUN chown root:root \
        /etc/ssh/sshd_config \
        /etc/opencode/opencode.json \
        /usr/local/bin/specialist-worker-entrypoint \
    && chmod 0644 /etc/ssh/sshd_config /etc/opencode/opencode.json \
    && chmod 0755 /usr/local/bin/specialist-worker-entrypoint

EXPOSE 2222
ENTRYPOINT ["/usr/local/bin/specialist-worker-entrypoint"]
