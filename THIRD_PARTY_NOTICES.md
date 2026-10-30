# Third-Party Notices

This file covers the components bundled into the portable Windows release
(`safe-workspace-mcp-<version>-windows-x64.zip`) of Safe Workspace MCP.

The portable release is built with PyInstaller and embeds a CPython runtime.
Only `mcp` and `dulwich` are pinned; the other packages are resolved when the
release is built. The exact versions shipped in each release are listed in
`BUILD-ENVIRONMENT.txt` inside the ZIP (releases up to 0.1.2 do not include it).

## Safe Workspace MCP

- License: Apache License 2.0 (see `LICENSE`)

## Bundled Python packages

| Package | License |
|---|---|
| annotated-types | MIT |
| anyio | MIT |
| attrs | MIT |
| cffi | MIT-0 |
| click | BSD-3-Clause |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| dulwich | Apache-2.0 OR GPL-2.0-or-later |
| h11 | MIT |
| httpcore2 | BSD-3-Clause |
| httpx2 | BSD-3-Clause |
| idna | BSD-3-Clause |
| jsonschema | MIT |
| jsonschema-specifications | MIT |
| mcp | MIT |
| mcp-types | MIT |
| opentelemetry-api | Apache-2.0 |
| pycparser | BSD-3-Clause |
| pydantic | MIT |
| pydantic_core | MIT |
| PyJWT | MIT |
| python-multipart | Apache-2.0 |
| pywin32 | Python Software Foundation License |
| referencing | MIT |
| rpds-py | MIT |
| sse-starlette | BSD-3-Clause |
| starlette | BSD-3-Clause |
| truststore | MIT |
| typing_extensions | PSF-2.0 |
| typing-inspection | MIT |
| urllib3 | MIT |
| uvicorn | BSD-3-Clause |

Dulwich is dual-licensed `Apache-2.0 OR GPL-2.0-or-later`; Safe Workspace MCP
redistributes it under the Apache-2.0 license path.

## Python runtime and native libraries

- **CPython 3.12** (PSF License). The embedded runtime includes CPython's own
  third-party components (for example OpenSSL, libffi, zlib, bzip2, xz/liblzma,
  expat); their licenses are listed at <https://docs.python.org/3/license.html>.
- **Microsoft Visual C++ runtime** DLLs, redistributed with the Python runtime
  under Microsoft's redistribution terms.
- **cryptography** wheels include a statically linked OpenSSL 3 (Apache-2.0).

## Build toolchain

- **PyInstaller** (GPL-2.0-or-later with the bootloader exception). Only its
  bootloader is part of the release, embedded in `safe-workspace-mcp.exe`; the
  exception permits distributing it under this project's license.

## External components downloaded at first launch (never bundled)

`Start-SafeWorkspaceMCP.ps1` downloads the official OpenAI Secure MCP Tunnel
client (`tunnel-client`) from `github.com/openai/tunnel-client` releases and
verifies it against a pinned SHA-256 checksum before use. tunnel-client is
licensed Apache-2.0 by OpenAI. Its version pin and checksums live in the
launcher script and are listed in the release notes.
