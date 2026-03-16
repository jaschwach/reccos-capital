"""
Generate static HTML files for production deployment.
Run from the workspace root: python build_static.py

Renders every Flask page to dist/public/ and rewrites
the api-base meta tag from /rpc to /api so that JS fetch
calls go through the api-server proxy in production.
"""

import os
import sys
import shutil

# Make sure we can import main_app from this directory
os.chdir(os.path.dirname(os.path.abspath(__file__)) or '.')

from main_app import app, make_token, init_db

OUT = os.path.join('artifacts', 'reccos-capital', 'dist', 'public')


def render(client, path, token=None):
    """Render a Flask route and return the HTML string."""
    if token:
        client.set_cookie('rc_token', token, domain='localhost')
    resp = client.get(path)
    html = resp.data.decode('utf-8')
    # Switch API prefix: production uses /api/ (proxied to Flask /rpc/)
    html = html.replace('content="/rpc"', 'content="/api"')
    print(f'  [{resp.status_code}] {path}')
    return html


def save(html, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    print('Initialising DB...')
    with app.app_context():
        init_db()

    print(f'Writing static files to {OUT}...')
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    # Generate admin JWT for rendering protected pages
    admin_token = make_token(1, 'admin')

    with app.test_client() as client:
        # --- Public pages (no auth needed) ---
        save(render(client, '/'),      os.path.join(OUT, 'index.html'))
        save(render(client, '/login'), os.path.join(OUT, 'login', 'index.html'))

        # --- Protected subscriber pages ---
        for route, slug in [
            ('/subscriber/',           'subscriber/index.html'),
            ('/subscriber/strategies', 'subscriber/strategies/index.html'),
            ('/subscriber/market',     'subscriber/market/index.html'),
            ('/subscriber/broker',     'subscriber/broker/index.html'),
            ('/subscriber/settings',   'subscriber/settings/index.html'),
        ]:
            save(render(client, route, token=admin_token), os.path.join(OUT, slug))

        # --- Admin panel ---
        save(render(client, '/admin', token=admin_token), os.path.join(OUT, 'admin', 'index.html'))

    print('Done.')


if __name__ == '__main__':
    main()
