# F006 — Navigator native build scope

- Query: Q006, Q011
- Type: grep/tree
- Summary: Navigator's tracked native source surface is Cython-only: the repository contains the two `.pyx` files and matching `.pxd` files cited in F001, but no tracked `Cargo.toml`, Rust source, PyO3 module, or maturin configuration was found outside the virtual environment. The user's mention of mixed Cython and Rust therefore describes a possible future build-infrastructure requirement, not an existing Navigator implementation contract.
- Citations:
  - `navigator/types.pyx`
  - `navigator/types.pxd`
  - `navigator/utils/types.pyx`
  - `navigator/utils/types.pxd`
