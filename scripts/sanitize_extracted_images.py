#!/usr/bin/env python3
"""
Sanitize extracted images directory by detecting SVGs saved with wrong extensions
and converting them to PNG (requires cairosvg). Also detects files PIL can't open.

Usage: python3 scripts/sanitize_extracted_images.py [--fix]
When run without --fix, it prints a report. With --fix it will convert SVGs.
"""
import sys
from pathlib import Path
from PIL import Image
import io

root = Path('data/extracted_images')
if not root.exists():
    print('No extracted_images dir found')
    sys.exit(0)

files = list(root.glob('web_*'))
bad = []
for f in files:
    try:
        with open(f,'rb') as fh:
            head = fh.read(1024)
        if b'<svg' in head.lower() or head.lstrip().startswith(b'<?xml'):
            bad.append((f, 'svg'))
            continue
        try:
            Image.open(f).verify()
        except Exception:
            bad.append((f, 'invalid'))
    except Exception as e:
        bad.append((f, f'err:{e}'))

if not bad:
    print('All files look OK')
    sys.exit(0)

print('Found potentially problematic files:')
for p,t in bad:
    print(f' - {p}: {t}')

if '--fix' not in sys.argv:
    print('\nRun with --fix to attempt SVG conversion (requires cairosvg)')
    sys.exit(0)

try:
    import cairosvg
except Exception:
    print('cairosvg not installed. Install it to enable conversion: pip install cairosvg')
    sys.exit(2)

for p,t in bad:
    if t == 'svg':
        try:
            with open(p,'rb') as fh:
                svg = fh.read()
            png = cairosvg.svg2png(bytestring=svg)
            newp = p.with_suffix('.png')
            with open(newp,'wb') as out:
                out.write(png)
            print(f'Converted {p} -> {newp}')
            try:
                p.unlink()
            except Exception:
                pass
        except Exception as e:
            print(f'Failed to convert {p}: {e}')
    else:
        print(f'Skipping {p} (type={t})')
