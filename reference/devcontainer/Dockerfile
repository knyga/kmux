# Dev image for __PROJECT__: Debian bookworm + tmux + Claude Code + Codex CLI.
# Full internet access; no egress firewall.
# Swap the base for the project's stack (docs/devcontainer.md § 2), e.g.
#   mcr.microsoft.com/devcontainers/python:1-3.12-bookworm
#   mcr.microsoft.com/devcontainers/typescript-node:24-bookworm
FROM mcr.microsoft.com/devcontainers/base:bookworm

ARG DEBIAN_FRONTEND=noninteractive
# Some devcontainers base images ship a stale Yarn apt source whose signing key has expired; drop it.
# tmux (bookworm: 3.3a >= 3.2) for kmux; python3 (3.11) for xclaude/xcodex helpers and tools/tasks.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      tmux python3 git ripgrep jq less procps unzip curl ca-certificates \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

USER vscode
ENV PATH="/home/vscode/bin:/home/vscode/.local/bin:${PATH}"

# Claude Code, native installer (no Node required)
RUN curl -fsSL https://claude.ai/install.sh | bash

# Keep installer packages outside ~/.codex so the config volume cannot hide upgrades.
RUN curl -fsSL https://chatgpt.com/codex/install.sh -o /tmp/install-codex.sh \
 && CODEX_HOME=/home/vscode/.local/share/codex CODEX_NON_INTERACTIVE=1 sh /tmp/install-codex.sh \
 && rm /tmp/install-codex.sh \
 && codex --version

WORKDIR /workspaces/__PROJECT__
