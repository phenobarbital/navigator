# F009 — Wheel availability of Navigator's native dependency chain (PyPI, 2026-09-08)

- Query: `https://pypi.org/pypi/<pkg>/json` for navigator-api, navconfig, asyncdb, python-datamodel, uvloop, cassandra-driver, xmlsec, pymssql, python-magic
- Type: external metadata read (resolves U2 / U4)
- Summary:

| Package | Latest | manylinux | win_amd64 | macOS | cp314 |
|---|---|---|---|---|---|
| navigator-api | 3.2.2 | cp311–313 | never | never | no |
| navconfig | 2.5.1 (2026-09-07) | cp310–314 | cp310–314 (new in 2.5.1) | never | yes |
| asyncdb | 2.16.0 (2026-09-07) | cp310–313 | cp310–313 | x86_64 + arm64 | **no** |
| python-datamodel | 0.10.21 | cp310–313 (+musllinux) | cp310–313 (+win32) | never | **no** |
| uvloop | 0.22.1 | yes | **none** | yes | yes |
| cassandra-driver | 3.30.1 | yes | yes | yes | yes |
| xmlsec / pymssql | 1.3.17 / 2.4.1 | yes | yes | yes | yes |
| python-magic | 0.4.27 | pure Python | — | — | — |

- Consequences:
  - **Windows install blocker**: `pyproject.toml` base deps request `asyncdb[uvloop,default,boto3]`; asyncdb's `uvloop` extra pins `uvloop==0.21.0`, which has no Windows wheels and cannot compile there. `pip install navigator-api` will fail on Windows until `uvloop` is removed from the base extras or guarded with `sys_platform != 'win32'` (navconfig 2.5.1 does exactly this; `navigator/__init__.py` already tolerates a missing uvloop).
  - **Windows ABI**: every upstream wheel is `win_amd64` only. No `win32` (asyncdb skips it), no `win_arm64` anywhere. Windows AMD64 is the only viable target.
  - **3.14 install gap**: asyncdb and python-datamodel publish no cp314 wheels, so a 3.14 user installing navigator-api compiles both from sdist (needs a C compiler; MSVC on Windows). Navigator's own cp314 wheels are buildable regardless.
  - **macOS**: navconfig and python-datamodel have never shipped macOS wheels, so a macOS Navigator wheel would still compile those two from sdist on the user's machine.
- Citations: PyPI JSON `releases` file lists, saved to the session scratchpad as `<pkg>.json`.
