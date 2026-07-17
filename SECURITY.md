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

Instead, contact the repository maintainer privately through the GitHub security advisory feature once the repository is published. Include a minimal reproduction, affected version/commit, impact, and proposed mitigation if available.

## Deployment assumptions

Obsidian AI Brain is designed for a single local user. Keep REST bound to loopback, keep `AI_BRAIN_TOKEN` private when enabled, and do not commit `.env`, Chroma persistence, or personal vault data. Chroma anonymized telemetry is disabled by the client configuration. `/status` reports absolute local vault/database paths, so shared-machine users should set `AI_BRAIN_TOKEN` and avoid forwarding the local port through proxies or tunnels.
