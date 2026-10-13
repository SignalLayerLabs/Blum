"""Check the maintained HF Space card before a source push can be rejected."""
from pathlib import Path
import re

readme = (Path(__file__).resolve().parents[1] / 'README.md').read_text()
frontmatter = re.match(r'\A---\s*\n(.*?)\n---\s*\n', readme, re.S)
if not frontmatter:
    raise SystemExit('HF Space card frontmatter is missing.')
description = re.search(r'^short_description:\s*(.*?)\s*$', frontmatter[1], re.M)
if not description or not 1 <= len(description[1].strip('"\'')) <= 60:
    raise SystemExit('HF short_description must contain 1–60 characters.')
print('HF Space short_description validated.')
