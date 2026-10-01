#!/usr/bin/env python3
"""
Stamp request-grouping metadata into GoAccess databases that predate it.

GoAccess 1.12 records whether a persisted database was built with
--http-method / --http-protocol (SI32_DB_PROPS.db, keys "append_method" and
"append_protocol"). Databases from older versions get the value 2 ("unknown")
on their first restore, and GoAccess never overwrites "unknown" again, so the
"This database predates request-grouping metadata" warning repeats forever.

This script replaces "unknown" with the values your installed goaccess
actually uses (detected by building a throw-away reference database with the
same global config), or with values you pass explicitly.

Only do this if the http-method / http-protocol settings have NOT changed
over the lifetime of the databases; otherwise you would be stamping a false
claim and should rebuild from logs instead.

Usage:
  goaccess-fix-grouping.py --dry-run
  goaccess-fix-grouping.py
  goaccess-fix-grouping.py --method yes --protocol yes '/path/*/db'
"""
import argparse
import glob
import os
import shutil
import struct
import subprocess
import sys
import tempfile

PROPS = "SI32_DB_PROPS.db"
KEYS = ("append_method", "append_protocol")
UNKNOWN = 2
DEFAULT_GLOB = "/var/customers/webs/*/goaccess"
DB_MARKERS = (PROPS, "I32_DATES.db")


def find_db_dirs(patterns):
    """Every directory at or below the matched paths that holds a goaccess db."""
    found = set()
    for pat in patterns:
        for root in glob.glob(pat):
            if not os.path.isdir(root):
                continue
            for d, _subdirs, files in os.walk(root):
                if any(m in files for m in DB_MARKERS):
                    found.add(d)
    return sorted(found)
DUMMY_LINE = ('127.0.0.1 - - [01/Jan/2026:00:00:00 +0000] "GET / HTTP/1.1" 200 1 '
              '"-" "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"\n')


def read_props(path):
    """Parse a tpl 'A(su)' image. Returns (endian, list of [key, value])."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:3] != b"tpl":
        raise ValueError("not a tpl file")
    flags = data[3]
    if not flags & 2:
        raise ValueError("unsupported (pre-1.3) tpl string format")
    e = ">" if flags & 1 else "<"
    (size,) = struct.unpack_from(e + "I", data, 4)
    if size != len(data):
        raise ValueError("size header mismatch (truncated file?)")
    fmt_end = data.index(b"\0", 8)
    if data[8:fmt_end] != b"A(su)":
        raise ValueError("unexpected format %r" % data[8:fmt_end])
    pos = fmt_end + 1
    (count,) = struct.unpack_from(e + "I", data, pos)
    pos += 4
    items = []
    for _ in range(count):
        (slen,) = struct.unpack_from(e + "I", data, pos)
        pos += 4
        n = slen - 1 if slen > 1 else 0
        key = data[pos:pos + n].decode()
        pos += n
        (val,) = struct.unpack_from(e + "I", data, pos)
        pos += 4
        items.append([key, val])
    if pos != len(data):
        raise ValueError("trailing bytes after array")
    return e, items


def write_props(path, e, items):
    body = struct.pack(e + "I", len(items))
    for key, val in items:
        kb = key.encode()
        body += struct.pack(e + "I", len(kb) + 1) + kb + struct.pack(e + "I", val)
    flags = 2 | (1 if e == ">" else 0)
    head_rest = b"A(su)\0"
    size = 4 + 4 + len(head_rest) + len(body)
    image = b"tpl" + bytes([flags]) + struct.pack(e + "I", size) + head_rest + body

    st = os.stat(path)
    tmp = path + ".fixtmp"
    with open(tmp, "wb") as f:
        f.write(image)
    os.chmod(tmp, st.st_mode & 0o7777)
    try:
        os.chown(tmp, st.st_uid, st.st_gid)
    except PermissionError:
        pass
    os.replace(tmp, path)


def detect_reference(goaccess):
    """Build a tiny database with the installed goaccess and read its values."""
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run(
            [goaccess, "-", "--log-format=COMBINED", "--persist",
             "--process-and-exit", "--no-parsing-spinner", "--db-path=" + d],
            input=DUMMY_LINE, text=True, capture_output=True)
        p = os.path.join(d, PROPS)
        if not os.path.exists(p):
            sys.exit("Reference run produced no %s (is goaccess >= 1.12?)\n%s"
                     % (PROPS, r.stderr))
        _, items = read_props(p)
    vals = dict(items)
    if any(vals.get(k) not in (0, 1) for k in KEYS):
        sys.exit("Reference database has no usable grouping values: %r" % vals)
    return {k: vals[k] for k in KEYS}


def yn(v):
    return "yes" if v else "no"


def yesno(s):
    s = s.lower()
    if s in ("yes", "1", "true"):
        return 1
    if s in ("no", "0", "false"):
        return 0
    raise argparse.ArgumentTypeError("use yes or no")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="*", default=[DEFAULT_GLOB],
                    help="directories or globs, searched recursively for "
                         "goaccess databases (default: %s)" % DEFAULT_GLOB)
    ap.add_argument("--goaccess", default="goaccess", help="goaccess binary")
    ap.add_argument("--method", type=yesno, help="force --http-method value (yes/no)")
    ap.add_argument("--protocol", type=yesno, help="force --http-protocol value (yes/no)")
    ap.add_argument("--dry-run", action="store_true", help="only report")
    ap.add_argument("--no-backup", action="store_true",
                    help="do not keep SI32_DB_PROPS.db.bak")
    a = ap.parse_args()

    if a.method is None or a.protocol is None:
        ref = detect_reference(a.goaccess)
        if a.method is not None:
            ref["append_method"] = a.method
        if a.protocol is not None:
            ref["append_protocol"] = a.protocol
    else:
        ref = {"append_method": a.method, "append_protocol": a.protocol}
    print("Target: --http-method=%s --http-protocol=%s"
          % (yn(ref["append_method"]), yn(ref["append_protocol"])))

    dirs = find_db_dirs(a.dirs)
    if not dirs:
        sys.exit("No goaccess databases found under: %s" % " ".join(a.dirs))

    counts = {"fixed": 0, "ok": 0, "skipped": 0, "error": 0}
    for d in dirs:
        p = os.path.join(d, PROPS)
        if not os.path.exists(p):
            if os.path.exists(os.path.join(d, "I32_DATES.db")):
                print("SKIP   %s (no %s yet - let goaccess 1.12 run once first)" % (d, PROPS))
            else:
                print("SKIP   %s (no goaccess database)" % d)
            counts["skipped"] += 1
            continue
        try:
            e, items = read_props(p)
        except (ValueError, struct.error) as ex:
            print("ERROR  %s: %s" % (p, ex))
            counts["error"] += 1
            continue
        cur = dict(items)
        known = {k: cur[k] for k in KEYS if k in cur and cur[k] != UNKNOWN}
        if len(known) == 2:
            if all(known[k] == ref[k] for k in KEYS):
                print("OK     %s" % d)
                counts["ok"] += 1
            else:
                print("SKIP   %s (already stamped method=%s protocol=%s; leaving it)"
                      % (d, yn(known["append_method"]), yn(known["append_protocol"])))
                counts["skipped"] += 1
            continue
        if known:
            print("SKIP   %s (only partially known: %r)" % (d, cur))
            counts["skipped"] += 1
            continue

        print("%s %s" % ("WOULD " if a.dry_run else "FIX   ", d))
        if a.dry_run:
            counts["fixed"] += 1
            continue
        for k in KEYS:
            for it in items:
                if it[0] == k:
                    it[1] = ref[k]
                    break
            else:
                items.append([k, ref[k]])
        if not a.no_backup:
            shutil.copy2(p, p + ".bak")
        write_props(p, e, items)
        read_props(p)  # sanity re-read
        counts["fixed"] += 1

    print("\n%(fixed)d fixed, %(ok)d already ok, %(skipped)d skipped, %(error)d errors" % counts)
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
