#!/usr/bin/env bash
# One-way backup of the Obsidian vault to a git remote.
#
# The vault is mounted read-only with only /vault/.git writable, so this job cannot
# alter notes. It also never pulls, merges or rebases: Obsidian Sync is the source of
# truth, and anything git wrote into the working tree would be synced to every device.
# If the remote has diverged the push fails and we alert instead of "fixing" it.
#
# What is deliberately NOT backed up (see build_excludes): the .obsidian config folder,
# bulky attachments (media/audio/video/images/pdf/archives) and anything over
# BACKUP_MAX_FILE_KB. Files already tracked in the adopted history that match these
# rules are dropped from the tip of the branch; older commits keep them.
set -euo pipefail

VAULT=${VAULT:-/vault}
BRANCH=${BACKUP_BRANCH:-main}
MAX_KB=${BACKUP_MAX_FILE_KB:-1024}

# Attachment types git should not carry. SVG stays: it is text and diffs fine.
EXTENSIONS="png jpg jpeg gif webp bmp tif tiff heic heif avif ico psd
            mp3 m4a wav flac ogg oga opus aac wma aiff
            mp4 mkv mov avi webm m4v wmv flv mpg mpeg 3gp
            pdf epub mobi djvu
            zip 7z rar tar gz tgz bz2 xz iso"

log() { printf '%s %s\n' "$(date -Is)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

# Ignore rules live in .git/info/exclude (never in the vault tree, so they are not
# synced to other devices) and are rebuilt on every run.
build_excludes() {
    cat <<'EOF'
# Obsidian config: plugins alone run to hundreds of MB. Left to Obsidian Sync.
.obsidian/
.obsidian.vimrc
.obsidian-*-copy/
*-obsidian-copy/
/obsidian_copy/

# Syncthing / OS / editor noise
.stfolder
.stignore
.stversions/
.trash/
*.sync-conflict-*
.DS_Store
*.tmp
.nrepl-port
/.lsp/
/.clj-kondo/

# Bulky attachment folders (synced between devices over WebDAV instead)
/Zulo/media/
/Zulo/assets/
/Zulo/videos/
/ReadItLater Inbox/assets/
EOF

    # Case-insensitive extension match: png -> *.[Pp][Nn][Gg]
    for ext in $EXTENSIONS; do
        pattern=
        for ((i = 0; i < ${#ext}; i++)); do
            c=${ext:i:1}
            if [[ $c == [a-z] ]]; then pattern+="[${c^^}${c}]"; else pattern+=$c; fi
        done
        printf '*.%s\n' "$pattern"
    done

    # Anything else over the size cap, listed per file. Skips trees already ignored above.
    while IFS= read -r -d '' path; do
        case $path in *$'\n'*) continue ;; esac
        path=${path#./}
        path=${path//\\/\\\\}
        path=${path//\*/\\*}
        path=${path//\?/\\?}
        path=${path//\[/\\[}
        path=${path//\]/\\]}
        [[ $path == *' ' ]] && path=${path%?}'\ '
        printf '/%s\n' "$path"
    done < <(find . \( -path ./.git -o -path ./.obsidian -o -path ./.stversions -o -path ./.trash \) -prune \
                  -o -type f -size +"${MAX_KB}k" -print0)
}

run() {
    : "${BACKUP_REMOTE:?BACKUP_REMOTE is not set}"
    cd "$VAULT"
    [ -d .git ] || die "$VAULT/.git is missing: it must be mounted read-write"
    [ -n "$(find . -mindepth 1 -maxdepth 1 ! -name .git -print -quit)" ] \
        || die "$VAULT is empty: is the vault mounted and synced?"

    [ -e .git/HEAD ] || git init -q -b "$BRANCH"
    # NTFS: no real file modes, and ctime/inode churn that would otherwise re-hash files.
    git config core.fileMode false
    git config core.checkStat minimal
    git config core.trustCTime false
    git config core.quotePath false
    if git remote get-url origin >/dev/null 2>&1; then
        git remote set-url origin "$BACKUP_REMOTE"
    else
        git remote add origin "$BACKUP_REMOTE"
    fi

    # First run: continue the existing history instead of starting an unrelated one.
    # --mixed moves the branch and index only, never the working tree.
    if ! git rev-parse -q --verify HEAD >/dev/null; then
        remote_heads=$(git ls-remote --heads origin "$BRANCH")
        if [ -n "$remote_heads" ]; then
            log "new repo: adopting existing history of origin/$BRANCH"
            git fetch -q origin "$BRANCH"
            git reset -q --mixed FETCH_HEAD
        fi
    fi

    # An unmounted or half-synced vault looks like "everything was deleted".
    tracked=$(git ls-files | wc -l)
    missing=$(git ls-files --deleted | wc -l)
    if [ "$tracked" -gt 20 ] && [ $((missing * 2)) -gt "$tracked" ]; then
        die "refusing to commit: $missing of $tracked tracked files are missing from the vault"
    fi

    mkdir -p .git/info
    build_excludes > .git/info/exclude

    git add -A
    # Excludes do not affect files that are already tracked, so untrack them explicitly.
    git ls-files -z --cached --ignored --exclude-standard | xargs -0 -r git rm -q --cached --

    if git diff --cached --quiet; then
        log "no changes"
    else
        git diff --cached --shortstat
        git commit -q -m "obsidian: auto-sync $(date -Is)"
        log "committed $(git rev-parse --short HEAD)"
    fi

    # Always push: a no-op when up to date, and it retries an earlier failed push.
    if [ "${BACKUP_DRY_RUN:-0}" = 1 ]; then
        log "dry run: not pushing"
    elif git rev-parse -q --verify HEAD >/dev/null; then
        git push -q origin "HEAD:refs/heads/$BRANCH"
    fi
}

notify_failure() {
    [ -n "${BACKUP_NTFY_ENDPOINT:-}" ] || return 0
    local mark="$VAULT/.git/backup-failed"
    # At most one alert per 12h, so a persistent failure doesn't page every 30 minutes.
    if [ -e "$mark" ] && [ -z "$(find "$mark" -mmin +720 2>/dev/null)" ]; then
        return 0
    fi
    touch "$mark"
    local auth=()
    [ -z "${BACKUP_NTFY_TOKEN:-}" ] || auth=(-H "Authorization: Bearer $BACKUP_NTFY_TOKEN")
    curl -fsS -m 20 "${auth[@]}" \
        -H "Title: Obsidian vault backup failed" -H "Priority: high" -H "Tags: warning" \
        -d "See: docker logs obsidian-backup" \
        "${BACKUP_NTFY_ENDPOINT%/}/${BACKUP_NTFY_TOPIC:-obsidian-backup}" >/dev/null \
        || log "could not send the failure notification"
}

if [ "${1:-}" = run ]; then
    run
    exit
fi

export GIT_SSH_COMMAND="ssh -i /ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/ssh/github_known_hosts"
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="$VAULT"

exec 9>/tmp/obsidian-backup.lock
flock -n 9 || { log "previous run still in progress, skipping"; exit 0; }

# Re-run ourselves so `set -e` stays active inside run() (it is ignored in an `if`).
if bash "$0" run; then
    rm -f "$VAULT/.git/backup-failed"
    touch "$VAULT/.git/backup-last-ok"
else
    rc=$?
    log "backup FAILED (exit $rc)" >&2
    notify_failure
    exit "$rc"
fi
