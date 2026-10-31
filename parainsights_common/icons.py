"""Render the tab icon to PNG: `uv run python -m parainsights_common.icons`.

Run it after changing `favicon_svg` or its colours. It writes the two 64 px PNGs the pages
inline (`icons/`) and `public/favicon.ico`, which a browser asks for when it finds no icon
it can draw. Needs Inkscape and ImageMagick; nothing in the build does.
"""
import subprocess
import tempfile
from pathlib import Path

from parainsights_common import FAVICON_COLOURS, favicon_svg

HERE = Path(__file__).parent
PUBLIC = HERE.parent / "public"


def render(svg: str, size: int, out: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".svg") as f:
        f.write(svg)
        f.flush()
        subprocess.run(["inkscape", f.name, "--export-type=png", f"--export-filename={out}",
                        f"--export-width={size}", f"--export-height={size}"],
                       check=True, capture_output=True)


def main() -> None:
    for name, colours in FAVICON_COLOURS.items():
        render(favicon_svg(*colours), 64, HERE / "icons" / f"favicon-{name}.png")
    with tempfile.TemporaryDirectory() as tmp:
        sizes = [Path(tmp) / f"{s}.png" for s in (16, 32, 48)]
        for size, out in zip((16, 32, 48), sizes):
            render(favicon_svg(*FAVICON_COLOURS["light"]), size, out)
        subprocess.run(["convert", *map(str, sizes), str(PUBLIC / "favicon.ico")], check=True)
    for path in (*sorted((HERE / "icons").glob("*.png")), PUBLIC / "favicon.ico"):
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
