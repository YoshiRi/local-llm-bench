"""Print per-element tool definition sizes without exposing tool contents."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('request', type=Path)
a = p.parse_args()
d = json.loads(a.request.read_text())
tools = d['tools']
total = len(json.dumps(tools, ensure_ascii=False))
rows = []
for t in tools:
    chars = len(json.dumps(t, ensure_ascii=False))
    rows.append(dict(name=t.get('name', t['type']), type=t['type'], chars=chars,
                     percent_of_tools=round(chars/total*100, 2),
                     nested_tools=len(t.get('tools', []))))
print(json.dumps(dict(source=str(a.request), tools_chars=total,
                      array_syntax_chars=total-sum(r['chars'] for r in rows),
                      rows=sorted(rows, key=lambda r: r['chars'], reverse=True)), indent=2))
