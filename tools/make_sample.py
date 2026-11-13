"""Make docs/sample_report.html from a synthetic log with known faults."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from padlab.analysis import analyse  # noqa: E402
from padlab.logfile import read_log  # noqa: E402
from padlab.report import render  # noqa: E402
from synth import build  # noqa: E402

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "synthetic.csv.gz")
    build(p)
    html = render(analyse(read_log(p)), "synthetic test log")
out = os.path.join(ROOT, "docs", "sample_report.html")
with open(out, "w", encoding="utf-8") as fh:
    fh.write(html)
print(out)
