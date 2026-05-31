#!/usr/bin/env python3
"""
replace_with_serpapi.py

Usage:
  python replace_with_serpapi.py --api-key YOUR_KEY [--index index.html] [--backup] [--dry-run]

This script finds the `FALLBACK_DATA` array inside the provided index.html,
queries SerpAPI (Google Images) for each entry's `name`, and replaces
Wikipedia `Special:FilePath` image URLs with the first image result.

It writes a backup to `index.html.bak` by default if `--backup` is provided.

Note: provide your SerpAPI key via `--api-key` or the SERPAPI_KEY env var.
"""

import re
import json
import time
import argparse
import os
import sys
from urllib.parse import quote_plus

try:
    import requests
except ImportError:
    print('Missing dependency: requests. Install with `pip install requests`')
    sys.exit(2)

SERPAPI_ENDPOINT = 'https://serpapi.com/search.json'

WIKI_FILEPATH_RE = re.compile(r'^https?://(?:[a-z]+\.)?wikipedia\.org/wiki/Special:FilePath/', re.I)
FALLBACK_BLOCK_RE = re.compile(r'(const\s+FALLBACK_DATA\s*=\s*\[)(.*?)(\];)', re.DOTALL)


def sanitize_js_array_text(text):
    # Remove trailing commas before closing braces/brackets to make JSON parseable
    text = re.sub(r',\s*(\}|\])', r"\1", text)
    return text


def extract_fallback_data(html_text):
    # First try the simple regex approach
    m = FALLBACK_BLOCK_RE.search(html_text)
    if m:
        array_text = m.group(2)
        array_text = sanitize_js_array_text(array_text)
        json_text = '[' + array_text + ']'
        try:
            data = json.loads(json_text)
            return data, m
        except Exception:
            # fall through to robust parser
            pass

    # Robust extraction: locate the 'const FALLBACK_DATA' and parse bracket balance
    idx = html_text.find('FALLBACK_DATA')
    if idx == -1:
        raise RuntimeError('Could not locate FALLBACK_DATA block in the HTML file')
    # find the first '[' after the identifier
    start = html_text.find('[', idx)
    if start == -1:
        raise RuntimeError('Could not locate opening [ for FALLBACK_DATA')

    depth = 0
    end = -1
    for i in range(start, len(html_text)):
        ch = html_text[i]
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        raise RuntimeError('Could not find matching closing ] for FALLBACK_DATA')

    array_text = html_text[start+1:end]
    array_text = sanitize_js_array_text(array_text)
    json_text = '[' + array_text + ']'
    try:
        data = json.loads(json_text)
    except Exception as exc:
        raise RuntimeError('Failed to parse FALLBACK_DATA as JSON: ' + str(exc))

    # create a fake match object-like tuple for injection (prefix, content, suffix)
    class M:
        def __init__(self, prefix, suffix, sidx, eidx):
            self._g1 = prefix
            self._g3 = suffix
            self._start = sidx
            self._end = eidx
        def group(self, n):
            return {1: self._g1, 3: self._g3}[n]
        def start(self):
            return self._start
        def end(self):
            return self._end

    prefix = html_text[:start]
    suffix = html_text[end+1:]
    # But for injection we need the exact original 'const FALLBACK_DATA = [' header
    header_start = html_text.rfind('\n', 0, idx) + 1
    header = html_text[header_start:start]
    fake_m = M(header, '];', header_start, end+1)
    return data, fake_m


def fetch_serpapi_image(query, api_key, session=None, delay=1.0):
    params = {
        'q': query,
        'tbm': 'isch',
        'api_key': api_key,
        'ijn': '0'
    }
    s = session or requests.session()
    try:
        r = s.get(SERPAPI_ENDPOINT, params=params, timeout=30)
        r.raise_for_status()
        j = r.json()
        images = j.get('images_results') or j.get('inline_images') or []
        if not images:
            return None
        first = images[0]
        # common keys: 'original', 'thumbnail', 'source'
        return first.get('original') or first.get('thumbnail') or first.get('source')
    except Exception as exc:
        print(f'Error fetching SerpAPI for "{query}": {exc}')
        return None
    finally:
        time.sleep(delay)


def replace_images(data, api_key, dry_run=False, delay=1.0):
    session = requests.Session()
    replaced = []
    for i, entry in enumerate(data):
        name = entry.get('name')
        img = entry.get('image')
        if not img or not isinstance(img, str):
            continue
        if not WIKI_FILEPATH_RE.match(img):
            # skip non-wikipedia entries
            continue
        query = name
        # Add category to query to improve image relevance
        if entry.get('category'):
            query = f"{name} {entry.get('category')}"
        new_img = fetch_serpapi_image(query, api_key, session=session, delay=delay)
        if new_img:
            replaced.append((i, name, img, new_img))
            if not dry_run:
                entry['image'] = new_img
        else:
            print(f'No image found for {name} (index {i})')
    return replaced


def inject_new_array(html_text, match_obj, new_data):
    # Pretty-print new_data as compact JS objects (one per line)
    dumped = json.dumps(new_data, ensure_ascii=False, indent=2)
    # Remove the surrounding [ ] and add proper indentation
    inner = dumped
    new_block = match_obj.group(1) + '\n' + inner + '\n' + match_obj.group(3)
    new_html = html_text[:match_obj.start()] + new_block + html_text[match_obj.end():]
    return new_html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--api-key', help='SerpAPI key (or set SERPAPI_KEY env var)')
    ap.add_argument('--index', default='index.html', help='Path to index.html containing FALLBACK_DATA')
    ap.add_argument('--backup', action='store_true', help='Write a backup of the original file to index.html.bak')
    ap.add_argument('--dry-run', action='store_true', help='Do not write changes; just report replacements')
    ap.add_argument('--delay', type=float, default=1.0, help='Seconds to wait between API requests')
    args = ap.parse_args()

    api_key = args.api_key or os.environ.get('SERPAPI_KEY')
    if not api_key:
        print('ERROR: SerpAPI key is required. Provide --api-key or set SERPAPI_KEY env var')
        sys.exit(2)

    idx_path = args.index
    if not os.path.isfile(idx_path):
        print('ERROR: index file not found:', idx_path)
        sys.exit(2)

    html_text = open(idx_path, 'r', encoding='utf-8').read()
    data, m = extract_fallback_data(html_text)
    print(f'Loaded {len(data)} fallback entries; scanning for wikipedia Special:FilePath images...')

    replaced = replace_images(data, api_key, dry_run=args.dry_run, delay=args.delay)
    print('\nReplacements found:', len(replaced))
    for idx, name, old, new in replaced:
        print(f'- [{idx}] {name}\n  from: {old}\n  to:   {new}\n')

    if args.dry_run:
        print('Dry run complete; no files written.')
        return

    if not replaced:
        print('No replacements to apply.')
        return

    # Backup
    if args.backup:
        bak = idx_path + '.bak'
        open(bak, 'w', encoding='utf-8').write(html_text)
        print('Backup written to', bak)

    new_html = inject_new_array(html_text, m, data)
    open(idx_path, 'w', encoding='utf-8').write(new_html)
    print('index.html updated with new image URLs.')

if __name__ == '__main__':
    main()
