# goaccess-fix-grouping.py

Silences GoAccess ≥ 1.12's *"This database predates request-grouping metadata"* warning by stamping the real `--http-method` / `--http-protocol` values into old databases.

Designed for Froxlor installations, so by default it operates on `/var/customers/webs/*/goaccess`.

```sh
goaccess-fix-grouping.py --dry-run      # show what would change
goaccess-fix-grouping.py                # fix all DBs under /var/customers/webs/*/goaccess
goaccess-fix-grouping.py /other/path    # other locations (searched recursively)
goaccess-fix-grouping.py --method no --protocol yes   # force values instead of auto-detect
```

- Run as root while the Froxlor traffic cron is idle.
- Keeps a backup as `SI32_DB_PROPS.db.bak`.
- Only valid if `http-method` / `http-protocol` never changed over the databases' lifetime.
