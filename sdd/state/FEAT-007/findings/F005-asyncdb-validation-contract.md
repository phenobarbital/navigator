# F005 — asyncdb portability validation contract

- Query: Q010
- Type: read
- Summary: asyncdb's Windows wheel task defines explicit acceptance checks for CPython 3.10–3.14, `win_amd64` tags, `.pyd` extension contents, preservation of Linux/macOS artifacts, and validation that avoids installing all optional dependencies. Its portability task separately calls for core-wheel import isolation and platform-specific extension/tag tests without external database services. These contracts are useful test boundaries for Navigator's refactor.
- Citations:
  - `/home/jesuslara/proyectos/asyncdb/sdd/tasks/completed/TASK-26-windows-release-wheels.md:13-30,61-95,104-125`
  - `/home/jesuslara/proyectos/asyncdb/sdd/tasks/completed/TASK-27-portability-tests.md:13-29,66-99`
