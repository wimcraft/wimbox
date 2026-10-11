#!/usr/bin/env bash
# Upload images to Immich and print a raw, embeddable link for each one.
#
# Immich has no "give me a public URL" upload endpoint, so this does two calls:
#   1. POST /api/assets         upload the file
#   2. POST /api/shared-links   share that one asset
# showMetadata must stay on: Immich turns downloads off without it, and then the proxy can
# only serve a lossy preview instead of the original file. The proxy itself hides metadata.
# The link points at immich-public-proxy (the same host, under /share/photo/), which serves
# the original file itself, so it works in Obsidian: ![](<url>). (The plain /share/<key>
# link of a single image also opens the image, but only as a ~1440px JPEG preview.)
#
# Usage:  immich-upload.sh [-a ALBUM] file-or-url...   upload files / download then upload URLs
#         immich-upload.sh [-a ALBUM]                  macOS: interactive screenshot, then upload
#         immich-upload.sh --list-albums               print the configured album names
#
# No -a means the upload is not added to any album.
#
# Config (env or ~/.config/immich-upload.env):
#   IMMICH_URL            https://immich.example.com
#   IMMICH_API_KEY        needs permissions: asset.upload, sharedLink.create (+ albumAsset.create for albums)
#   IMMICH_ALBUM_<NAME>   album UUID, selected with -a <name> (case-insensitive). One line per album,
#                         e.g. IMMICH_ALBUM_OBSIDIAN=3f2a...; add a line to add an album.
set -euo pipefail

CONFIG=${IMMICH_UPLOAD_ENV:-${XDG_CONFIG_HOME:-$HOME/.config}/immich-upload.env}
[ ! -f "$CONFIG" ] || . "$CONFIG"
: "${IMMICH_URL:?IMMICH_URL is not set}"
: "${IMMICH_API_KEY:?IMMICH_API_KEY is not set}"
IMMICH_URL=${IMMICH_URL%/}

album_names() {
    # Names come from the IMMICH_ALBUM_* variables currently set.
    compgen -A variable IMMICH_ALBUM_ | sed 's/^IMMICH_ALBUM_//' | tr 'A-Z' 'a-z' | sort | paste -sd' ' -
}

notify() {
    if command -v osascript >/dev/null; then
        osascript -e "display notification \"$1\" with title \"Immich upload\"" || true
    elif command -v notify-send >/dev/null; then
        notify-send "Immich upload" "$1" || true
    fi
}
copy() {
    if command -v pbcopy >/dev/null; then printf '%s' "$1" | pbcopy
    elif command -v wl-copy >/dev/null; then printf '%s' "$1" | wl-copy
    elif command -v xclip >/dev/null; then printf '%s' "$1" | xclip -selection clipboard
    fi
}
api() { curl -fsS -H "x-api-key: $IMMICH_API_KEY" "$@"; }

ALBUM_NAME=
ALBUM_ID=
while [ $# -gt 0 ]; do
    case $1 in
        -a|--album) ALBUM_NAME=${2:?-a needs an album name}; shift 2 ;;
        --list-albums) echo "available albums: $(album_names)"; echo "(omit -a for no album)"; exit 0 ;;
        -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) break ;;
    esac
done

if [ -n "$ALBUM_NAME" ]; then
    var=IMMICH_ALBUM_$(printf '%s' "$ALBUM_NAME" | tr 'a-z' 'A-Z' | tr -c 'A-Z0-9\n' '_')
    ALBUM_ID=${!var:-}
    [ -n "$ALBUM_ID" ] || { echo "unknown album '$ALBUM_NAME'; available: $(album_names)" >&2; exit 1; }
fi

# Every step is checked explicitly: `set -e` does not apply inside a function that is
# called from an `if` or `||`, so a failed curl/jq would otherwise carry on with empty
# values and print a broken link.
upload() {
    local file=$1 now resp id key url
    now=$(date -u +%Y-%m-%dT%H:%M:%S.000Z)
    resp=$(api -F "assetData=@$file" -F "fileCreatedAt=$now" -F "fileModifiedAt=$now" \
            "$IMMICH_URL/api/assets") || { echo "upload request failed" >&2; return 1; }
    id=$(jq -er .id <<<"$resp") || { echo "no asset id in response: $resp" >&2; return 1; }
    # A duplicate upload returns the id of the existing asset, which is fine to share again.
    if [ -n "$ALBUM_ID" ]; then
        api -X PUT -H 'Content-Type: application/json' -d "{\"ids\":[\"$id\"]}" \
            "$IMMICH_URL/api/albums/$ALBUM_ID/assets" >/dev/null \
            || { echo "adding to album failed" >&2; return 1; }
    fi
    resp=$(api -X POST -H 'Content-Type: application/json' \
            -d "{\"type\":\"INDIVIDUAL\",\"assetIds\":[\"$id\"],\"allowDownload\":true,\"showMetadata\":true}" \
            "$IMMICH_URL/api/shared-links") || { echo "creating the share link failed" >&2; return 1; }
    key=$(jq -er .key <<<"$resp") || { echo "no share key in response: $resp" >&2; return 1; }
    url=$IMMICH_URL/share/photo/$key/$id/original
    # Immich generates the preview in the background; until then the link is a 404.
    for _ in $(seq 30); do
        [ "$(curl -s -o /dev/null -w '%{http_code}' "$url")" = 200 ] && { printf '%s\n' "$url"; return 0; }
        sleep 1
    done
    echo "link never became reachable: $url" >&2
    return 1
}

tmp=
cleanup() { [ -z "$tmp" ] || rm -rf "$tmp"; }
trap cleanup EXIT
tmp=$(mktemp -d)

files=()
if [ $# -eq 0 ]; then
    command -v screencapture >/dev/null || { echo "usage: $0 [-a album] file-or-url..." >&2; exit 2; }
    screencapture -i "$tmp/screenshot_$(date +%Y-%m-%d_%H-%M-%S).png"
    [ -s "$tmp"/screenshot_*.png ] || exit 0   # selection cancelled
    files=("$tmp"/screenshot_*.png)
fi
for arg in "$@"; do
    if [[ $arg =~ ^https?:// ]]; then
        name=${arg%%\?*}; name=${name##*/}
        dest=$tmp/$(date +%s%N)-${name:-image}
        curl -fsSL "$arg" -o "$dest" || { echo "download failed: $arg" >&2; exit 1; }
        files+=("$dest")
    elif [ -f "$arg" ]; then
        files+=("$arg")
    else
        echo "file not found: $arg" >&2; exit 1
    fi
done

urls=()
for f in "${files[@]}"; do
    if url=$(upload "$f"); then
        urls+=("$url"); echo "$url"
    else
        notify "Upload failed: ${f##*/}"; echo "upload failed: $f" >&2; exit 1
    fi
done
copy "$(printf '%s\n' "${urls[@]}")"
notify "Uploaded ${#urls[@]} file(s), link copied"
