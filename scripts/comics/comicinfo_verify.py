#!/usr/bin/env python3
"""Audit the final ComicInfo.xml state of a comics tree.

Checks, for every CBZ:
  * a ComicInfo.xml exists at the archive root, where BookOrbit looks for it;
  * it parses and carries a non-empty <Series>;
  * <Number> is unique within its series (a duplicate means a mis-parse);
  * the archive's entry list still reads (catches a corrupted rewrite).
"""
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("MEDIA_ROOT", "/mnt/media"), "library", "comics")

total = tagged = 0
no_root_tag, unparseable, no_series, broken = [], [], [], []
series_numbers = defaultdict(list)
series_files = defaultdict(int)

for dirpath, _d, filenames in os.walk(ROOT):
    for fn in sorted(filenames):
        if fn.startswith(".") or not fn.lower().endswith(".cbz"):
            continue
        full = os.path.join(dirpath, fn)
        rel = os.path.relpath(full, ROOT)
        total += 1
        try:
            with zipfile.ZipFile(full) as z:
                names = z.namelist()
                if "ComicInfo.xml" not in names:
                    no_root_tag.append(rel)
                    continue
                raw = z.read("ComicInfo.xml").decode(errors="replace")
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{rel}: {exc}")
            continue

        try:
            el = ET.fromstring(raw)
        except ET.ParseError:
            unparseable.append(rel)
            continue

        series = (el.findtext("Series") or "").strip()
        if not series:
            no_series.append(rel)
            continue
        tagged += 1
        series_files[series] += 1
        num = (el.findtext("Number") or "").strip()
        if num:
            series_numbers[series].append((num, rel))

dupes = []
for series, entries in series_numbers.items():
    seen = defaultdict(list)
    for num, rel in entries:
        seen[num].append(rel)
    for num, rels in seen.items():
        if len(rels) > 1:
            dupes.append((series, num, rels))

print(f"tree: {ROOT}")
print(f"  CBZ files                      : {total}")
print(f"  with a readable root <Series>   : {tagged}")
print(f"  distinct series                 : {len(series_files)}")
print(f"  of those, with a <Number>       : {sum(len(v) for v in series_numbers.values())}")
print()
for label, items in (("no ComicInfo.xml at archive root", no_root_tag),
                     ("ComicInfo.xml does not parse", unparseable),
                     ("no <Series> value", no_series),
                     ("archive unreadable", broken)):
    print(f"  {label:<34}: {len(items)}")
    for it in items:
        print(f"      {it}")

print()
if dupes:
    print(f"  DUPLICATE (series, number) pairs : {len(dupes)}")
    for series, num, rels in dupes:
        print(f"      {series} #{num}")
        for r in rels:
            print(f"        {r}")
else:
    print("  duplicate (series, number) pairs : 0")

print()
print("  multi-volume series:")
for series, n in sorted(series_files.items(), key=lambda kv: (-kv[1], kv[0].lower())):
    if n > 1:
        nums = sorted((int(x[0]) for x in series_numbers.get(series, []) if x[0].isdigit()))
        span = f"{nums[0]}-{nums[-1]}" if nums else "no numbers"
        print(f"    {series[:44]:<45} {n:>3} files   [{span}]")

sys.exit(1 if (no_root_tag or unparseable or no_series or broken or dupes) else 0)
