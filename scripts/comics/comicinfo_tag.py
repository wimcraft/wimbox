#!/usr/bin/env python3
"""Derive ComicInfo.xml (Series / Number / Count) for a comics tree and report or write it.

Series comes from the immediate parent folder name, Number from a volume/issue marker in
the filename. Dry run by default: nothing is written unless --write is passed.
"""
import argparse
import os
import re
import sys
import zipfile
from collections import defaultdict
from xml.sax.saxutils import escape

# Default tree: override with MEDIA_ROOT, or pass --root.
ROOT = os.path.join(os.environ.get("MEDIA_ROOT", "/mnt/media"), "library", "comics")
COMIC_EXT = {".cbz", ".cbr", ".cb7"}
OTHER_EXT = {".pdf"}

# Ordered most-explicit first. Only these produce a Number; nothing is guessed.
# NB: the leading guard is (?<![A-Za-z]) rather than \b, because "_" is a word
# character -- "Foo_vol1" has no \b before "vol" and would never match.
NUMBER_PATTERNS = [
    ("vol",   re.compile(r"(?<![A-Za-z])vol(?:ume)?[ ._-]*(\d{1,3})(?![\d])", re.I)),
    ("v",     re.compile(r"(?<![A-Za-z])v[ ._-]*(\d{1,3})(?![\d])", re.I)),
    ("hash",  re.compile(r"#[ ]*(\d{1,3})(?![\d])")),
    ("issue", re.compile(r"(?<![A-Za-z])(?:issue|no|num)[ ._-]*(\d{1,3})(?![\d])", re.I)),
    ("book",  re.compile(r"(?<![A-Za-z])(?:book|part|tp)[ ._-]*(\d{1,3})(?![\d])", re.I)),
    ("trail", re.compile(r"[ ._-](\d{1,3})$")),
    # Last resort: "vol" run together with the preceding word, e.g. "witchbladerebirthvol01".
    ("vol~",  re.compile(r"vol(?:ume)?[ ._-]*(\d{1,3})(?![\d])", re.I)),
]


def derive_number(stem):
    """Return (number, which_pattern) or (None, None)."""
    # Strip a trailing 4-digit year in parentheses so it is never read as an index.
    cleaned = re.sub(r"\((?:19|20)\d{2}\).*$", "", stem).strip()
    for name, pat in NUMBER_PATTERNS:
        m = pat.search(cleaned)
        if m:
            return str(int(m.group(1))), name
    return None, None


def has_comicinfo(path):
    """True only for a ComicInfo.xml at the archive root.

    This deliberately mirrors BookOrbit's own lookup, which is an exact
    `entry.name.toLowerCase() === 'comicinfo.xml'` (cbz-metadata.ts:325). A tag
    nested in a subfolder is invisible to BookOrbit, so treating it as "already
    tagged" would leave the book with no series at all.
    """
    try:
        with zipfile.ZipFile(path) as z:
            return any(n.lower() == "comicinfo.xml" for n in z.namelist())
    except (zipfile.BadZipFile, OSError):
        return None  # unreadable / not a zip


def build_xml(series, number, count, title):
    parts = ['<?xml version="1.0" encoding="utf-8"?>',
             '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">']
    parts.append(f"  <Series>{escape(series)}</Series>")
    if number:
        parts.append(f"  <Number>{escape(number)}</Number>")
    if count:
        parts.append(f"  <Count>{count}</Count>")
    if title:
        parts.append(f"  <Title>{escape(title)}</Title>")
    parts.append("</ComicInfo>")
    return "\n".join(parts) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--write", action="store_true", help="actually inject ComicInfo.xml")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing ComicInfo.xml")
    ap.add_argument("--exclude", action="append", default=[],
                    help="skip any file whose path contains this substring (repeatable)")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    plans, skips, others = [], [], []

    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            stem, ext = os.path.splitext(fn)
            ext = ext.lower()
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)

            if any(pat in rel for pat in args.exclude):
                skips.append((rel, "excluded on the command line"))
                continue

            if ext in OTHER_EXT:
                others.append((rel, "PDF - ComicInfo.xml not supported in this container"))
                continue
            if ext not in COMIC_EXT:
                continue

            parent = os.path.basename(dirpath)
            if os.path.abspath(dirpath) == root:
                skips.append((rel, "file sits at the library root - no folder to take a series from"))
                continue

            if ext != ".cbz":
                others.append((rel, f"{ext[1:].upper()} - archive cannot be written, needs manual handling"))
                continue

            existing = has_comicinfo(full)
            if existing is None:
                skips.append((rel, "archive unreadable / not a valid zip"))
                continue
            if existing and not args.overwrite:
                skips.append((rel, "already has ComicInfo.xml - left alone"))
                continue

            number, how = derive_number(stem)
            plans.append({"rel": rel, "full": full, "series": parent,
                          "number": number, "how": how, "title": stem})

    # <Count> only where a series genuinely has multiple numbered entries.
    per_series = defaultdict(int)
    for p in plans:
        if p["number"]:
            per_series[p["series"]] += 1

    numbered = [p for p in plans if p["number"]]
    unnumbered = [p for p in plans if not p["number"]]

    print(f"root: {root}")
    print(f"mode: {'WRITE' if args.write else 'DRY RUN (nothing will be modified)'}")
    print()
    print(f"{'=' * 96}")
    print(f"WOULD TAG WITH SERIES + NUMBER  ({len(numbered)} files)")
    print(f"{'=' * 96}")
    print(f"{'SERIES':<34} {'NUM':>4} {'CNT':>4}  {'VIA':<6} FILE")
    for p in sorted(numbered, key=lambda x: (x["series"].lower(), int(x["number"]))):
        cnt = per_series[p["series"]]
        print(f"{p['series'][:33]:<34} {p['number']:>4} {cnt:>4}  {p['how']:<6} {p['rel']}")

    print()
    print(f"{'=' * 96}")
    print(f"WOULD TAG WITH SERIES ONLY - no volume/issue number found  ({len(unnumbered)} files)")
    print("these are probably one-shots / graphic novels; review before writing")
    print(f"{'=' * 96}")
    for p in sorted(unnumbered, key=lambda x: x["series"].lower()):
        print(f"{p['series'][:44]:<45} {p['rel']}")

    if skips:
        print()
        print(f"{'=' * 96}")
        print(f"SKIPPED  ({len(skips)} files)")
        print(f"{'=' * 96}")
        for rel, why in sorted(skips):
            print(f"{why:<52} {rel}")

    if others:
        print()
        print(f"{'=' * 96}")
        print(f"NEEDS MANUAL HANDLING  ({len(others)} files)")
        print(f"{'=' * 96}")
        for rel, why in sorted(others):
            print(f"{why:<52} {rel}")

    print()
    print(f"{'=' * 96}")
    print("SUMMARY")
    print(f"{'=' * 96}")
    print(f"  series + number : {len(numbered)}")
    print(f"  series only     : {len(unnumbered)}")
    print(f"  skipped         : {len(skips)}")
    print(f"  manual          : {len(others)}")
    print(f"  distinct series : {len({p['series'] for p in plans})}")

    if not args.write:
        print()
        print("Dry run only. Re-run with --write to inject ComicInfo.xml.")
        return 0

    written = failed = 0
    for p in plans:
        # Series + Number only. <Title> would beat the filename parser's cleaned-up
        # title, and <Count> maps to seriesTotalBooks -- "volumes I own" is not the
        # number of books in the series, so leave it for a provider to supply.
        xml = build_xml(p["series"], p["number"], count=None, title=None)
        try:
            with zipfile.ZipFile(p["full"], "a") as z:
                before = len(z.namelist())
                if args.overwrite and any(n.lower().endswith("comicinfo.xml") for n in z.namelist()):
                    print(f"  ! cannot replace in place, skipping: {p['rel']}", file=sys.stderr)
                    failed += 1
                    continue
                z.writestr("ComicInfo.xml", xml)

            # Reopen and confirm the archive still reads and the entry round-trips.
            # An append rewrites the central directory, so this is the check that
            # catches a truncated or corrupted archive straight away.
            with zipfile.ZipFile(p["full"]) as z:
                names = z.namelist()
                if len(names) != before + 1:
                    raise RuntimeError(f"entry count {before} -> {len(names)}, expected {before + 1}")
                if z.read("ComicInfo.xml").decode() != xml:
                    raise RuntimeError("ComicInfo.xml did not round-trip")
            written += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  ! FAILED {p['rel']}: {exc}", file=sys.stderr)
            failed += 1

    print(f"\nwrote and verified {written} files, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
