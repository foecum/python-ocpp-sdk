"""``python -m tools.gen``: regenerate the generated modules."""

from tools.gen import ROOT, write

for written in write():
    print(f"wrote {written.relative_to(ROOT)}")
