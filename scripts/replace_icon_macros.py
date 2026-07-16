"""One-shot: replace inline icon macros with shared import."""
import re
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates"
pat = re.compile(
    r"\{% macro icon\(name, cls='w-5 h-5'\) %\}.*?\{% endmacro %\}\s*\n",
    re.DOTALL,
)
import_line = '{% from "_icons.html" import icon %}\n'

for path in sorted(root.glob("*.html")):
    if path.name.startswith("_"):
        continue
    text = path.read_text(encoding="utf-8")
    if "{% macro icon" not in text:
        continue
    new, n = pat.subn(import_line, text, count=1)
    if n:
        path.write_text(new, encoding="utf-8")
        print(f"replaced in {path.name}")
    else:
        print(f"NO MATCH {path.name}")
