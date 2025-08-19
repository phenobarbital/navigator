# Contributing Guidelines

If you are lazy like me – just do pull request, but it can be rejected.

Most important (about pull request):
- Check your code with `tox` before `git push`.
- Pull request must be small and change just one thing (bug/feature/support/etc).

The next part of the text is just a formality. But formally the right part.

## Development Setup

1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Clone the repository: `git clone https://github.com/phenobarbital/navigator.git`
3. Set up development environment: `make develop`
4. Run tests: `make test`

## Code of Conduct

This project is intended to be a safe, welcoming space for collaboration.
All contributors are expected to adhere to the [Contributor Covenant](http://contributor-covenant.org) code of conduct.
Thank you for being kind to each other!

## Contributions welcome!

**Before spending lots of time on something, ask for feedback on your idea first!**

Please search [issues](../../issues/) and [pull requests](../../pulls/) before adding something new!
This helps avoid duplicating efforts and conversations.

This project welcomes any kind of contribution! Here are a few suggestions:

- **Ideas**: participate in an issue thread or start your own to have your voice heard.
- **Writing**: contribute your expertise in an area by helping expand the included content.
- **Copy editing**: fix typos, clarify language, and generally improve the quality of the content.
- **Formatting**: help keep content easy to read with consistent formatting.
- **Code**: help maintain and improve the project codebase.

## Project Governance

**This is an [OPEN Open Source Project](http://openopensource.org/).**

Individuals making significant and valuable contributions are given commit access to the project to contribute
as they see fit. This project is more like an open wiki than a standard guarded open source project.

### Rules

There are a few basic ground rules for collaborators:

1. **No `--force` pushes** or modifying the Git history in any way.
1. **Non-master branches** ought to be used for ongoing work.
1. **External API changes and significant modifications** ought to be subject to an **internal pull request**
   to solicit feedback from other contributors.
1. Internal pull requests to solicit feedback are *encouraged* for any other non-trivial contribution but left
   to the discretion of the contributor.
1. Contributors should attempt to adhere to the prevailing code style.

### Releases

Declaring formal releases remains the prerogative of the project maintainer.

### Changes to this arrangement

This is an experiment and feedback is welcome! This document may also be subject to pull requests or changes
by contributors where you believe you have something valuable to add or change.
