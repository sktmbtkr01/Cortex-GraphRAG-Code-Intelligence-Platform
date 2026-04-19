import urllib.request as r, json, sys

req = r.Request(
    'http://127.0.0.1:8001/api/v1/ingest',
    headers={'Content-Type': 'application/json'},
    data=json.dumps({'repo':'octocat/hello-world', 'branch':'master'}).encode()
)
try:
    print(r.urlopen(req).read().decode())
except Exception as e:
    print(e.read().decode() if hasattr(e, 'read') else str(e))
