#!/bin/bash
# Weekly Docker cleanup.
#
# Docker 29 uses the containerd image store, where `docker image prune -a
# --filter until=<age>` matches nothing and silently reclaims 0B. Untagged
# images are pruned without a filter, and the age cutoff for unreferenced
# tagged images is applied here instead, so images pulled ahead of a container
# recreate are not deleted before they are ever used.
set -euo pipefail

MAX_AGE_HOURS=${DOCKER_PRUNE_MAX_AGE_HOURS:-168}

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "Starting docker prune (keeping images newer than ${MAX_AGE_HOURS}h)"
df -h --output=avail / | tail -1 | xargs echo "Free on / before:"

# Untagged images left behind by re-pulls and rebuilds.
docker image prune -f

# Tagged images no container refers to, older than the cutoff.
cutoff=$(( $(date +%s) - MAX_AGE_HOURS * 3600 ))
referenced=$(docker ps -aq | xargs -r docker inspect --format '{{.Image}}')

docker images --no-trunc --format '{{.ID}} {{.Repository}}:{{.Tag}}' |
	while read -r id ref; do
		[ "$ref" = "<none>:<none>" ] && continue
		case "$referenced" in *"$id"*) continue ;; esac

		created=$(docker inspect --format '{{.Created}}' "$id")
		if [ "$(date -d "$created" +%s)" -lt "$cutoff" ]; then
			log "removing unused image $ref"
			docker rmi "$ref" >/dev/null || true
		fi
	done

docker builder prune -a -f --filter "until=${MAX_AGE_HOURS}h"

df -h --output=avail / | tail -1 | xargs echo "Free on / after:"
log "Done"
