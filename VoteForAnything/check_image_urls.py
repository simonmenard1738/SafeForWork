import re
import requests
from pathlib import Path
text = Path('index.html').read_text(encoding='utf-8')
urls = re.findall(r'"image":\s*"([^\"]+)"', text)
print('total', len(urls))
seen = set()
for u in urls:
    if u in seen:
        continue
    seen.add(u)
    try:
        r = requests.head(u, allow_redirects=True, timeout=20)
        print(u, r.status_code, r.headers.get('Content-Type', ''))
    except Exception as e:
        print(u, 'ERROR', e)
