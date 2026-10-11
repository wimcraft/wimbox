#!/usr/bin/env python3
"""Convert CBR (RAR) comics to CBZ so they can carry a ComicInfo.xml tag.

RAR archives cannot be written by zip tooling, so a CBR can never hold the
ComicInfo.xml that BookOrbit and Kavita read. Repacking to CBZ fixes that
without touching the page images: every entry is copied byte-for-byte and
stored uncompressed, since comic pages are already JPEG.

An existing ComicInfo.xml inside the CBR is preserved as-is; one is only
generated when the archive has none.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comicinfo_tag import ROOT, build_xml, derive_number  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# Reading RAR needs a real extractor. Note that p7zip as shipped by Debian and
# Raspberry Pi OS *lists* a RAR happily and then fails every entry with
# "Unsupported Method", because the RAR decoder is the non-free part -- so a
# successful `7z l` proves nothing. libarchive (bsdtar) and unar both work.
DOCKER_IMAGE = "alpine"
DOCKER_SETUP = "apk add --no-cache libarchive-tools >/dev/null 2>&1"


class Extractor:
    """Whichever RAR reader this host actually has, or a throwaway container."""

    def __init__(self, mode, root, workdir):
        self.mode = mode
        self.root = root
        self.workdir = workdir

    @classmethod
    def detect(cls, root, workdir, prefer_docker=False):
        if not prefer_docker:
            for tool in ("bsdtar", "unar"):
                if shutil.which(tool):
                    return cls(tool, root, workdir)
        if shutil.which("docker"):
            return cls("docker", root, workdir)
        return None

    def _docker(self, inner_args):
        return ["docker", "run", "--rm",
                "-v", f"{self.root}:/in:ro", "-v", f"{self.workdir}:/out",
                DOCKER_IMAGE, "sh", "-c", f"{DOCKER_SETUP} && exec {inner_args}"]

    def list(self, cbr):
        rel = os.path.relpath(cbr, self.root)
        if self.mode == "bsdtar":
            cmd = ["bsdtar", "-tf", cbr]
        elif self.mode == "unar":
            cmd = ["lsar", cbr]
        else:
            cmd = self._docker('bsdtar -tf "$1"') + ["_", f"/in/{rel}"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr.strip()[:200]
        names = [l for l in r.stdout.splitlines() if l.strip() and not l.endswith("/")]
        if self.mode == "unar":  # lsar prints the archive name first
            names = names[1:]
        return names, None

    def extract(self, cbr, dest):
        rel = os.path.relpath(cbr, self.root)
        if self.mode == "bsdtar":
            cmd = ["bsdtar", "-xf", cbr, "-C", dest]
        elif self.mode == "unar":
            cmd = ["unar", "-q", "-D", "-o", dest, cbr]
        else:
            reldest = os.path.relpath(dest, self.workdir)
            cmd = self._docker('bsdtar -xf "$1" -C "$2"') + ["_", f"/in/{rel}", f"/out/{reldest}"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return (True, None) if r.returncode == 0 else (False, r.stderr.strip()[:200])


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def convert(cbr, ex, workdir, originals_dir, dry_run):
    folder = os.path.dirname(cbr)
    stem = os.path.splitext(os.path.basename(cbr))[0]
    series = os.path.basename(folder)
    number, _how = derive_number(stem)
    cbz = os.path.join(folder, stem + ".cbz")

    if os.path.exists(cbz):
        return "skip", f"{stem}.cbz already exists"

    entries, err = ex.list(cbr)
    if entries is None:
        return "fail", f"cannot list: {err}"
    images = [e for e in entries if os.path.splitext(e)[1].lower() in IMAGE_EXT]
    has_tag = any(os.path.basename(e).lower() == "comicinfo.xml" for e in entries)

    plan = (f"{len(entries)} entries ({len(images)} images), "
            f"tag: {'existing, preserved' if has_tag else f'new Series={series} Number={number}'}")
    if dry_run:
        return "plan", plan

    extract = tempfile.mkdtemp(dir=workdir)
    try:
        ok, err = ex.extract(cbr, extract)
        if not ok:
            return "fail", f"extract failed: {err}"

        onbox = []
        for dp, _d, fns in os.walk(extract):
            for fn in fns:
                full = os.path.join(dp, fn)
                onbox.append((os.path.relpath(full, extract), full))
        onbox.sort(key=lambda t: t[0])
        if len(onbox) != len(entries):
            return "fail", f"extracted {len(onbox)} files, archive listed {len(entries)}"

        digests = {rel: sha(full) for rel, full in onbox}

        tmp_cbz = cbz + ".part"
        # ZIP_STORED: the pages are already-compressed JPEG, so deflate would burn
        # CPU for nothing and is what makes a repack slow on a Pi.
        with zipfile.ZipFile(tmp_cbz, "w", zipfile.ZIP_STORED) as z:
            for rel, full in onbox:
                z.write(full, rel)
            if not has_tag:
                z.writestr("ComicInfo.xml", build_xml(series, number, count=None, title=None))

        # Verify every page survived the repack bit for bit.
        with zipfile.ZipFile(tmp_cbz) as z:
            names = set(z.namelist())
            expected = set(digests) | (set() if has_tag else {"ComicInfo.xml"})
            if names != expected:
                return "fail", f"entry mismatch: missing {expected - names}, extra {names - expected}"
            for rel, want in digests.items():
                h = hashlib.sha256()
                with z.open(rel) as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                if h.hexdigest() != want:
                    return "fail", f"content differs for {rel}"

        os.replace(tmp_cbz, cbz)
        os.makedirs(originals_dir, exist_ok=True)
        shutil.move(cbr, os.path.join(originals_dir, os.path.basename(cbr)))
        return "ok", f"{len(onbox)} entries verified byte-identical, original moved aside"
    finally:
        shutil.rmtree(extract, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    media = os.environ.get("MEDIA_ROOT", "/mnt/media")
    ap.add_argument("--workdir", default=os.path.join(media, "temp"))
    ap.add_argument("--originals", default=os.path.join(media, "library", ".originals"))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--docker", action="store_true",
                    help="extract in a throwaway container instead of using a local tool")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    cbrs = sorted(os.path.join(dp, fn) for dp, _d, fns in os.walk(root)
                  for fn in fns if fn.lower().endswith(".cbr"))
    if not cbrs:
        print("no .cbr files found")
        return 0

    os.makedirs(args.workdir, exist_ok=True)
    ex = Extractor.detect(root, os.path.abspath(args.workdir), prefer_docker=args.docker)
    if ex is None:
        print("no RAR extractor available. Install one with:\n"
              "  sudo apt install libarchive-tools   # bsdtar\n"
              "or run with --docker to use a container instead.", file=sys.stderr)
        return 1

    print(f"mode: {'WRITE' if args.write else 'DRY RUN'}   files: {len(cbrs)}   extractor: {ex.mode}")
    rc = 0
    for cbr in cbrs:
        status, detail = convert(cbr, ex, args.workdir, args.originals, not args.write)
        print(f"  [{status}] {os.path.relpath(cbr, root)}")
        print(f"          {detail}")
        if status == "fail":
            rc = 1
    if not args.write:
        print("\nDry run only. Re-run with --write.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
