#!/bin/sh
set -eu

: "${BACKUP_SCHEDULE:=*/30 * * * *}"

echo "$BACKUP_SCHEDULE /usr/local/bin/backup.sh" > /tmp/crontab

# Run once at start so a broken setup shows up immediately, not at the next tick.
if [ "${BACKUP_RUN_ON_START:-1}" = 1 ]; then
    /usr/local/bin/backup.sh || true
fi

exec supercronic /tmp/crontab
