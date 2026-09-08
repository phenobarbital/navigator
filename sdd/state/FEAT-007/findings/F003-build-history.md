# F003 — Recent build history and known regression surface

- Query: Q007
- Type: git_log/read
- Summary: Recent history contains repeated release/build fixes. Commit `4650fd5` (2026-09-03) changed package discovery from a hardcoded top-level package to `setuptools.packages.find`, added explicit Cython extension checks, and retained a cp313 install-test skip because a transitive `cassandra-driver` dependency lacks a cp313 manylinux wheel and its sdist fails under Python 3.13. The current branch contains that fix through merge commit `225176a`.
- Citations:
  - `git:4650fd5`
  - `git:225176a`
  - `.github/workflows/release.yml:59-72`
