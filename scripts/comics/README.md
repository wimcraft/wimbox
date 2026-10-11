# Comic metadata tooling

BookOrbit's Comics library runs in **File as Book** mode, where sidecar files are
never associated with a book. That leaves an embedded `ComicInfo.xml` as the only
local source of metadata, and most scene releases ship without one. These scripts
derive `Series` and `Number` from the folder layout and write that tag into the
archives, which both BookOrbit and Kavita then read.

All three default to `$MEDIA_ROOT/library/comics` and take `--root` to override.
Every script is dry-run by default; `--write` is what modifies files.

## comicinfo_tag.py

Walks the tree, takes `<Series>` from each book's parent folder and `<Number>`
from a volume marker in the filename, and injects a `ComicInfo.xml` at the
archive root.

```
./comicinfo_tag.py                       # report only
./comicinfo_tag.py --exclude "junk/" --write
```

It writes **only** `Series` and `Number`, deliberately:

- `<Title>` would win over BookOrbit's filename parser (`comicMetadata?.title ?? fb.title`),
  replacing a cleaned-up title with the raw filename stem.
- `<Count>` maps to `seriesTotalBooks`, and "volumes I happen to own" is not the
  number of books in the series. Leave it to a metadata provider.

An archive that already has a root-level `ComicInfo.xml` is left alone, so
release-group metadata is never clobbered. The check is an exact root-level
match, mirroring BookOrbit's own `entry.name.toLowerCase() === 'comicinfo.xml'`:
a tag nested inside a subfolder is invisible to BookOrbit, so it does not count
as already tagged.

## comicinfo_verify.py

Audits the tree and exits non-zero on any problem: a missing or unparseable root
tag, an empty `<Series>`, an unreadable archive, or a duplicate
`(series, number)` pair — the last being the check that catches a filename
mis-parse.

```
./comicinfo_verify.py
```

## cbr_to_cbz.py

RAR cannot be written by zip tooling, so a CBR can never carry a ComicInfo tag.
This repacks CBR to CBZ, copying every page byte-for-byte (stored, not
recompressed — the pages are already JPEG) and verifying each entry's SHA-256
against the extracted original before replacing anything. The original `.cbr` is
moved to `$MEDIA_ROOT/library/.originals/` rather than deleted; the leading dot
keeps BookOrbit's scanner out of it.

```
./cbr_to_cbz.py            # report only
./cbr_to_cbz.py --write
```

It needs a real RAR reader and prefers a local `bsdtar` or `unar`, falling back
to a throwaway container (`--docker` forces that path).

> Note: `p7zip` as packaged for Debian and Raspberry Pi OS *lists* a RAR happily
> and then fails every entry with `Unsupported Method`, because the RAR decoder
> is the non-free part. A successful `7z l` proves nothing. Install `bsdtar` with
> `sudo apt install libarchive-tools`.

## After writing tags

Rescan the Comics library in BookOrbit, and Kavita on its next scan. Neither
picks up an in-place archive change on its own.

Keep **Rename files after metadata changes** and **Write metadata to files** off
on a library that Kavita also reads: BookOrbit renames and moves files into
`{authors:first}/...` on metadata edits, which strands Kavita's stored paths.
