# F002 — Navigator release workflow scope

- Query: Q005, Q006
- Type: read/grep
- Summary: `.github/workflows/release.yml` builds a matrix containing only Ubuntu runners and CPython 3.11, 3.12, and 3.13. It invokes cibuildwheel only for Linux, sets a manylinux image, and skips Windows/musllinux/i686. Its structural extension verification is Linux-specific (`.so`) and runs only for the Linux matrix. Deployment moves only `*-manylinux*.whl` files into `dist/linux` and uploads only those wheels. Post-deploy installation tests run only on Ubuntu and Python 3.11–3.13.
- Citations:
  - `.github/workflows/release.yml:7-102`
  - `.github/workflows/release.yml:131-200`
