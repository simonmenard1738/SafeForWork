import re
import time
import sys
import urllib.request
import urllib.error

with open('index.html', 'r', encoding='utf-8') as f:
    text = f.read()

entries = re.findall(r'{\s*"name":\s*"([^"]+)"\s*,\s*"image":\s*"([^"]+)"\s*,\s*"category":\s*"([^"]+)"\s*}', text)
if not entries:
    raise SystemExit('No entries found in index.html')

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0 Safari/537.36'
}

invalid = []

for name, url, category in entries:
    if not url or not isinstance(url, str):
        invalid.append((name, url, 'missing-image'))
        continue

    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            final = resp.geturl()
            ct = resp.headers.get('Content-Type', '')
            status = resp.status
            if status != 200 or not ct.lower().startswith('image/'):
                invalid.append((name, url, status, ct, final))
    except urllib.error.HTTPError as exc:
        final = exc.geturl() if hasattr(exc, 'geturl') else url
        invalid.append((name, url, exc.code, str(exc), final))
    except Exception as exc:
        invalid.append((name, url, 'error', str(exc)))

    time.sleep(0.5)

print('\nINVALID COUNT:', len(invalid))
for entry in invalid:
    print(entry)
