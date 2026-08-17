# Third-Party Notices

This file covers the components bundled into the portable Windows release
(`safe-workspace-mcp-vX.Y.Z-windows-x64.zip`) of Safe Workspace MCP.

The portable release embeds a Python runtime built with PyInstaller. The
bundled dependency closure below was generated from the actual build
environment (exact pins) and is reproducible via `packaging/build-portable.ps1`.

## Safe Workspace MCP

- License: Apache License 2.0 (see `LICENSE`)

## Bundled runtime dependencies

| Package | Version | License |
|---|---|---|
| annotated-types | 0.8.0 | MIT |
| anyio | 4.14.2 | MIT |
| attrs | 26.1.0 | MIT |
| cffi | 2.1.1 | MIT-0 |
| click | 8.4.2 | BSD-3-Clause |
| colorama | 0.4.6 | BSD (per classifiers) |
| cryptography | 50.0.0 | Apache-2.0 OR BSD-3-Clause |
| dulwich | 1.2.6 | Apache-2.0 OR GPL-2.0-or-later |
| h11 | 0.16.0 | MIT |
| httpcore2 | 2.10.0 | BSD-3-Clause |
| httpx2 | 2.10.0 | BSD-3-Clause |
| idna | 3.18 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| mcp | 2.0.0 | MIT |
| mcp-types | 2.0.0 | MIT |
| opentelemetry-api | 1.44.0 | Apache-2.0 |
| pycparser | 3.0 | BSD-3-Clause |
| pydantic | 2.13.4 | MIT |
| pydantic_core | 2.46.4 | MIT |
| PyJWT | 2.13.0 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| pywin32 | 312 | Python Software Foundation License |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.6.3 | MIT |
| sse-starlette | 3.4.8 | BSD-3-Clause |
| starlette | 1.6.0 | BSD-3-Clause |
| truststore | 0.10.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| urllib3 | 2.7.0 | MIT |
| uvicorn | 0.52.3 | BSD-3-Clause |

Dulwich is dual-licensed `Apache-2.0 OR GPL-2.0-or-later`; Safe Workspace MCP
redistributes it under the Apache-2.0 license path.

## Build toolchain (not bundled into the release)

| Tool | Version | License |
|---|---|---|
| PyInstaller | 6.22.1 | PyInstaller License (GPL with special exception allowing bundled output to be under any license) |
| Python | 3.12 | PSF License |

## External components downloaded at first launch (never bundled)

`Start-SafeWorkspaceMCP.ps1` downloads the official OpenAI Secure MCP Tunnel
client (`tunnel-client`) from `github.com/openai/tunnel-client` releases and
verifies it against a pinned SHA-256 checksum before use. tunnel-client is
licensed Apache-2.0 by OpenAI. Its version pin and checksum live in the
launcher script and are mirrored in the release notes for each release.
