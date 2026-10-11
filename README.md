# wimbox

Lightweight, reproducible homelab configuration for small single-board computers.

## Media layout

Book, comic, and audiobook files live in one app-neutral tree so that several
readers can be pointed at the same content without one of them owning the path:

```
/mnt/media/library/
  ebooks/      Kavita (/books), BookOrbit (/books/ebooks)
  comics/      Kavita (/comics), BookOrbit (/books/comics)
  manga/       Kavita (/manga)
  audiobooks/  Audiobookshelf (/audiobooks), BookOrbit (/books/audiobooks, read-only)
  podcasts/    Audiobookshelf (/podcasts)
  inbox/       BookOrbit Book Dock staging - never add it as a library folder
```

Audiobookshelf owns audiobook playback and identifies items by path, so BookOrbit
mounts `audiobooks/` read-only: it can catalogue them, but cannot rename files or
write metadata back and orphan Audiobookshelf's progress. The two do not share
reading progress - there is no API compatibility between them.

Application state (databases, caches, thumbnails) always belongs under
`APPDATA_ROOT`, never in the media tree. `/mnt/media` is NTFS via ntfs-3g, where
ownership is not enforced and PostgreSQL cannot run.

Comic archives carry their series and volume in an embedded `ComicInfo.xml`,
which both BookOrbit and Kavita read. `scripts/comics/` derives those tags from
the folder layout, audits them, and repacks CBR to CBZ so it can hold one.

When repointing an app at a new host path, keep its **container** path unchanged:
Kavita and Audiobookshelf store absolute container paths in their databases, so
moving only the host side needs no database surgery.

## Obsidian vault

`stacks/obsidian/` keeps a copy of the vault on wimbox at `/mnt/media/obsidian`:

- `obsidian-sync` runs the headless Obsidian Sync client (`ob sync --continuous`),
  so the vault stays current without any Obsidian app open. **Obsidian Sync is the
  source of truth.** Login state lives in `APPDATA_ROOT/obsidian/sync-home`.
- `obsidian-backup` commits and pushes the vault to a private GitHub repo every
  30 minutes (`OBSIDIAN_BACKUP_SCHEDULE`). It is strictly one-way: the vault is
  mounted read-only (only `.git` is writable), and it never pulls, merges or
  rebases, so it cannot write into notes that Obsidian Sync would spread to every
  device. If the remote diverges, the push fails and an alert goes to ntfy.

The backup deliberately skips the `.obsidian` config folder (plugins run to
hundreds of MB), `Zulo/media|assets|videos`, images, audio, video, PDFs, archives,
and any file over `OBSIDIAN_BACKUP_MAX_FILE_KB` (1 MiB). Ignore rules live in
`.git/info/exclude`, regenerated on every run, so they never enter the vault. It
also refuses to commit when over half the tracked files are missing (an unmounted
or empty vault), and the container is unhealthy if no run succeeded for 2 hours.

First-time setup:

```
cd stacks/obsidian
docker compose build
docker compose run --rm -it obsidian-sync ob login
docker compose run --rm -it obsidian-sync ob sync-setup --vault "<vault name>" --path /vault --device-name wimbox
```

Do this into an empty `/mnt/media/obsidian` so the current vault is pulled from
Obsidian Sync rather than merged with an old copy. Then add
`APPDATA_ROOT/obsidian/backup-ssh/id_ed25519.pub` as a **deploy key with write
access** on the backup repo, and `docker compose up -d`. On its first run the
backup adopts the existing history of `OBSIDIAN_BACKUP_BRANCH` rather than
starting an unrelated one. Optional, since wimbox needs no plugins:
`ob sync-config --path /vault --configs ""` stops config/plugin sync to this host.

Quick notes from the phone go through Syncthing, scoped to the Drafting paths only
(add `${MEDIA_ROOT}/obsidian` as folder `/obsidian`, with this `.stignore`) so the
whole vault is never shared and Syncthing and Obsidian Sync do not fight over it:

```
!/gravity.md
!/Writings/Drafting
*
```

## Immich image links

`immich-public-proxy` runs next to Immich and Traefik sends `/share/*` and `/s/*` on
`immich.<domain>` to it; the UI and API stay on Immich. A share of a single image is
served as a raw image (only a ~1440px preview at `/share/<key>`, the original at
`/share/photo/<key>/<asset>/original`), so `scripts/immich-upload.sh` (upload, share,
print the original-file URL) gives a link that embeds in Obsidian. Immich's **External domain** setting must be
`https://immich.<domain>`, and Cloudflare should bypass cache for `/share/video/*` and
`/share/*/download`.

## Maintenance

### Docker image/build cache pruning

Unused Docker images and build cache accumulate over time and can fill the disk.
`scripts/docker_prune.sh` removes anything not attached to a container and older
than 7 days, run weekly via a user-level systemd timer.

To enable it on a new system:

```
mkdir -p ~/.config/systemd/user
ln -sf ~/homelab/scripts/systemd/docker-prune.service ~/.config/systemd/user/docker-prune.service
ln -sf ~/homelab/scripts/systemd/docker-prune.timer ~/.config/systemd/user/docker-prune.timer
systemctl --user daemon-reload
systemctl --user enable --now docker-prune.timer
loginctl enable-linger "$USER"
```

`loginctl enable-linger` lets the timer run even when no session is logged in
(needed on a headless box). Check it's scheduled with:

```
systemctl --user list-timers docker-prune.timer
```

## Bugsink

`stacks/bugsink` collects crash reports and in-app bug reports from my own
apps (pepperlingo first) over the Sentry protocol. First start:

```
mkdir -p "$APPDATA_ROOT/bugsink" && sudo chown 14237:14237 "$APPDATA_ROOT/bugsink"
docker compose -f stacks/bugsink/compose.yaml up -d
```

Add `bugsink.<domain>` to the Cloudflare tunnel like the other hosts. Do not
put it behind Cloudflare Access: the apps post to `/api/<project>/envelope/`
without a login. The web UI has its own (admin from `BUGSINK_ADMIN`; nobody
can register).

Then, in the UI: create a team and a project per app, and copy the project's
DSN into that app's build (pepperlingo: the `REPORT_DSN` repository secret).
For reading issues from scripts or Claude Code, create a token under Tokens
and use the API at `/api/canonical/0/` (schema at
`/api/canonical/0/schema/`); a token can read and change everything, so keep
it out of repositories.

For a push notification on each new issue, add a "Custom webhook" messaging
service pointing at `https://ntfy.<domain>/bugsink` (the public hostname:
Bugsink refuses webhooks to private addresses). If the topic needs a token,
pass it in the URL with ntfy's `?auth=` parameter.
