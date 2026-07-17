# Security policy

## Supported version

The current `main` branch is the supported development version.

## Reporting a vulnerability

Please do **not** open a public issue for a suspected vulnerability involving:

- vault data disclosure;
- path traversal or symlink/junction escapes;
- REST exposure outside loopback;
- unsafe source ingestion or DOCX parsing;
- secret/credential disclosure;
- MCP tool authorization or denial-of-service risks.

Use GitHub private vulnerability reporting when it is enabled for this repository. If that feature is unavailable, open a public issue containing **no vulnerability details** and ask the maintainer to establish a private reporting channel. Include a minimal reproduction, affected version/commit, impact, and proposed mitigation only in the private report.

## Deployment assumptions

Obsidian AI Brain is designed for a single local user. The bundled runner binds only to loopback and the application rejects non-loopback request clients; do not expose it through a reverse proxy or port-forwarding tunnel. Keep `AI_BRAIN_TOKEN` private when enabled, and do not commit `.env`, Chroma persistence, or personal vault data. Chroma anonymized telemetry is disabled by the client configuration. `/status` reports absolute local vault/database paths, so shared-machine users should set `AI_BRAIN_TOKEN`.
