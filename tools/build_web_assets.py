"""Build the public dashboard shell on the PC, never on the ESP32 heap."""
import gzip
import hashlib
import io
from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parents[1]


def build_assets(root=ROOT):
    root = Path(root).resolve()
    modules = str(root / 'modules')
    previous_path = sys.path[:]
    try:
        sys.path.insert(0, modules)
        config = runpy.run_path(str(root / 'modules/config_store.py'))['DEFAULT_CONFIG']
        forms = runpy.run_path(str(root / 'modules/dashboard_forms.py'))
        dashboard = runpy.run_path(str(root / 'modules/dashboard.py'))
        dashboard['iter_render'].__globals__['_open_template'] = lambda: (root / 'dashboard.html').open('rb')
        body = dashboard['render'](config, forms['configuration_form'](config), forms['_escape']).encode('utf-8')
    finally:
        sys.path[:] = previous_path
    output = root / '.pio/web'
    output.mkdir(parents=True, exist_ok=True)
    compressed = io.BytesIO()
    with gzip.GzipFile(filename='', fileobj=compressed, mode='wb', compresslevel=9, mtime=0) as stream:
        stream.write(body)
    values = {
        'dashboard.static.html': body,
        'dashboard.html.gz': compressed.getvalue(),
        'dashboard.etag': hashlib.sha256(body).hexdigest().encode('ascii'),
    }
    for name, data in values.items():
        (output / name).write_bytes(data)
    return [output / name for name in values]


if __name__ == '__main__':
    for asset in build_assets():
        print('%s: %d bytes' % (asset.name, asset.stat().st_size))
