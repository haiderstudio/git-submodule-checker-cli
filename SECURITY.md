# Security Policy

This tool runs locally, collects no data, sends nothing anywhere, and needs no API key or secret. It only reads the repo folders you point it at, runs read-only git commands (`ls-files`, `config`, `rev-parse`) inside them, and never initialises a submodule, never checks anything out, and never commits anything. It writes nothing except the report on standard output (and usage errors on standard error). It never contacts a submodule's remote: no fetch, no network request of any kind.

If you find a case where the tool changes a file, contacts a remote, or reports a pass for a repo whose submodule is uninitialised or checked out at a different commit from the one recorded, please open an issue describing the exact commands and input. Do not include any real secret in the report.
