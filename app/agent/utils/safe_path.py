from pathlib import Path

WORKDIR = Path.cwd() / "agent_workspace"
WORKDIR.mkdir(exist_ok=True)

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path