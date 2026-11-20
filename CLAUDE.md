# Project Structure
./ (root)
| - doc/
| - src/
| - CLAUDE.md
| - HANDOFF.md
| - README.md

* `doc/` contains documentation for both usage and development
* `src/` contains code
* `HANDOFF.md` contains context from the previous claude session. Read this.
* `README.md` user-facing README.md

# Response Style

Casual yet direct, minimal yet comprehensive. Every additional character is a waste of user's time and tokens,
both precious resources. Don't miss any details, and turn your critical assumptions into questions, rather than
hoping your training is enough to infer. When asked to review something (yours, the user's, LLM-generated,
doesn't matter) be thorough but don't scrutinize to infinity. What's important is addressing critical flaws,
not scrutinizing minor details with little side effect.
