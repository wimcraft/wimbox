FROM node:22-slim

# Pinned: obsidian-headless is pre-1.0 and its CLI is still changing.
ARG OBSIDIAN_HEADLESS_VERSION=0.0.14

RUN npm install -g "obsidian-headless@${OBSIDIAN_HEADLESS_VERSION}" \
    && npm cache clean --force

# The base image's `node` user is uid/gid 1000, matching PUID/PGID elsewhere.
USER node
WORKDIR /vault

CMD ["ob", "sync", "--continuous"]
