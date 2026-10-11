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
