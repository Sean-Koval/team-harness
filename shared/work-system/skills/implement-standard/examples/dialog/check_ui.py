"""Forbid raw dialog tags in this example's feature HTML."""
import sys
from html.parser import HTMLParser
from pathlib import Path


class FeatureHTML(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag == "dialog":
            line, column = self.getpos()
            self.errors.append(
                f"{self.path}:{line}:{column + 1} UI001 "
                "Use confirmRemoval() from confirm-dialog.js. Pass the opener and "
                "a visible fallback so keyboard focus survives deletion."
            )


def inspect(path):
    parser = FeatureHTML(path)
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser.errors


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    paths = [Path(arg) for arg in sys.argv[1:]] or [root / "index.html", *sorted((root / "features").rglob("*.html"))]
    errors = [error for path in paths for error in inspect(path)]
    for error in errors:
        print(error, file=sys.stderr)
    sys.exit(bool(errors))
