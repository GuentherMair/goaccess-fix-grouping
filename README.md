# goaccess-fix-grouping.py

Silences GoAccess ≥ 1.12's *"This database predates request-grouping metadata"* warning by stamping the real `--http-method` / `--http-protocol` values into old databases.

Designed for Froxlor installations, so by default it operates on `/var/customers/webs/*/goaccess`.

```sh
goaccess-fix-grouping.py --dry-run      # show what would change
goaccess-fix-grouping.py                # fix all DBs under /var/customers/webs/*/goaccess
goaccess-fix-grouping.py /other/path    # other locations (searched recursively)
goaccess-fix-grouping.py --method no --protocol yes   # force values instead of auto-detect
goaccess-fix-grouping.py --restore      # undo: put SI32_DB_PROPS.db.bak back (combine with --dry-run to preview)
goaccess-fix-grouping.py --cleanup      # delete the backups once you're happy (asks "are you sure?")
```

- Run as root while the Froxlor traffic cron is idle.
- Keeps a backup as `SI32_DB_PROPS.db.bak`.
- Only valid if `http-method` / `http-protocol` never changed over the databases' lifetime.

## What's happening

GoAccess 1.12 started recording in each database whether it was built with `--http-method` / `--http-protocol` (`append_method` / `append_protocol` in `SI32_DB_PROPS.db`). On the first `--restore` of an older database it can't know, so it stores `2` ("unknown"). GoAccess deliberately never overwrites an unknown value, so the warning repeats on every Froxlor traffic run. The official fix is rebuilding the database from logs, which is usually impossible once Froxlor has rotated them away.

## The workaround

The script runs the installed `goaccess` once on a throwaway one-line log, using the same global config Froxlor's call picks up (Froxlor passes no `-p`), and reads back the values GoAccess writes for a fresh database. It then replaces the "unknown" values in every old database with those, after saving a backup. Databases that already carry real values are left alone.

Afterwards the warning is gone, the historical data is unchanged, and GoAccess stops with an error if the `--http-method` / `--http-protocol` settings ever stop matching the database — the protection this metadata was introduced for.
