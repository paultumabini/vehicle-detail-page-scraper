"""
Ad-hoc FTP upload smoke test for VDP CSV files.

Uses the same environment variables as ``VdpUrlFtpExportPipeline`` in ``pipelines.py``;
do not commit real credentials. Example::

    export AIM_FTP_HOST=ftp.example.com
    export AIM_FTP_USER=...
    export AIM_FTP_PASS=...
    python -m scrapebucket.ftp_test
"""

from __future__ import annotations

import csv
import io
import os
import sys
from ftplib import FTP, error_perm


def _sample_rows() -> list[dict[str, str]]:
    """Placeholder rows for integration testing only."""
    return [
        {
            'VIN': '3C6UR5TL2KG517011',
            'VDP URLS': 'https://example.com/inventory/used-vehicle-3c6ur5tl2kg517011/',
        },
        {
            'VIN': '1GTUUCED3NZ581385',
            'VDP URLS': 'https://example.com/inventory/new-vehicle-1gtuuced3nz581385/',
        },
    ]


def main() -> int:
    host = os.environ.get('AIM_FTP_HOST')
    user = os.environ.get('AIM_FTP_USER')
    password = os.environ.get('AIM_FTP_PASS')
    if not all((host, user, password)):
        print(
            'Missing AIM_FTP_HOST / AIM_FTP_USER / AIM_FTP_PASS '
            '(see pipelines.VdpUrlFtpExportPipeline).',
            file=sys.stderr,
        )
        return 1

    remote_name = os.environ.get('AIM_FTP_TEST_FILENAME', 'TEST_VDP_URLS.csv')

    buffer = io.StringIO()
    fieldnames = ['VIN', 'VDP URLS']
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in _sample_rows():
        writer.writerow(row)

    payload = io.BytesIO(buffer.getvalue().encode('utf-8'))

    ftp = FTP()
    try:
        ftp.connect(host, int(os.environ.get('AIM_FTP_PORT', '21')))
        ftp.login(user, password)
        ftp.storbinary(f'STOR {remote_name}', payload)
    except (OSError, error_perm) as exc:
        print(f'FTP failed: {exc}', file=sys.stderr)
        return 1
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()

    print(f'Uploaded {remote_name!r} to {host!r}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
