# parainsights

> **This repository lives on GitHub: <https://github.com/ondrejchmelar/parainsights>.**
> The GitLab project at `gitlab.com/chmelar.o/parainsights` is **deprecated** — it is no
> longer updated, and its Pages site only redirects to the one below.

Tools for paragliding, published at **<https://ondrejchmelar.github.io/parainsights/>**:

| tool | the question |
|---|---|
| [meteo](https://ondrejchmelar.github.io/parainsights/meteo/) | is it worth driving anywhere today, and where? |
| [planner](https://ondrejchmelar.github.io/parainsights/planner/) | what is that task worth, and what does it cross? |
| [airspace](https://ondrejchmelar.github.io/parainsights/airspace/) | what is above me, and what does my instrument not know? |
| [flights](https://ondrejchmelar.github.io/parainsights/) | how did that flight go? |

```bash
uv sync --extra dev
uv run pytest -c pyproject.toml
```

Everything else — layout, decisions, how to publish — is in [CLAUDE.md](CLAUDE.md).
