import os
import io
import base64
import json
import sqlite3
import secrets
import string
import datetime
from functools import wraps

import bcrypt
import jwt
import pyotp
import qrcode
from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, make_response, g
)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'reccos-capital-dev-secret-key-2026!!')
app.config['JWT_EXPIRY_HOURS'] = 8
DB_PATH = 'reccos.db'


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode=WAL')
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'subscriber',
            is_active INTEGER NOT NULL DEFAULT 1,
            totp_secret TEXT,
            totp_enabled INTEGER NOT NULL DEFAULT 0,
            backup_codes TEXT,
            reset_token TEXT,
            reset_token_expires TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_login TEXT
        );

        CREATE TABLE IF NOT EXISTS waitlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            strategy TEXT,
            executed_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS broker_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            broker TEXT,
            api_key_last4 TEXT,
            connected_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    ''')

    # Seed default admin
    admin_email = 'jory@andium.com'
    admin_pw = 'ReccosCap2026!'
    existing = db.execute('SELECT id FROM users WHERE email = ?', (admin_email,)).fetchone()
    if not existing:
        pw_hash = bcrypt.hashpw(admin_pw.encode(), bcrypt.gensalt()).decode()
        db.execute(
            'INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)',
            (admin_email, pw_hash, 'admin')
        )

    # Seed some demo trade history for admin (id=1)
    count = db.execute('SELECT COUNT(*) FROM trade_history').fetchone()[0]
    if count == 0:
        trades = [
            (1, 'AAPL', 'buy', 100, 182.50, 'Dip Recovery'),
            (1, 'TSLA', 'sell', 50, 248.30, 'Rally Fade'),
            (1, 'NVDA', 'buy', 30, 875.20, 'High Beta Momentum'),
            (1, 'SPY', 'buy', 200, 510.40, 'Dip Recovery'),
            (1, 'QQQ', 'sell', 75, 432.10, 'Rally Fade'),
            (1, 'AMD', 'buy', 120, 168.75, 'High Beta Momentum'),
        ]
        db.executemany(
            'INSERT INTO trade_history (user_id, symbol, side, qty, price, strategy) VALUES (?,?,?,?,?,?)',
            trades
        )

    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def make_token(user_id, role):
    exp = datetime.datetime.utcnow() + datetime.timedelta(hours=app.config['JWT_EXPIRY_HOURS'])
    payload = {'sub': user_id, 'role': role, 'exp': exp}
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


def decode_token(token):
    try:
        return jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_current_user():
    token = request.cookies.get('rc_token')
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    db = get_db()
    row = db.execute('SELECT * FROM users WHERE id = ? AND is_active = 1', (payload['sub'],)).fetchone()
    return row


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.path.startswith('/rpc/'):
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect(url_for('login_page'))
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user['role'] != 'admin':
            if request.path.startswith('/rpc/'):
                return jsonify({'error': 'Forbidden'}), 403
            return redirect(url_for('login_page'))
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


def generate_backup_codes(n=8):
    return [secrets.token_hex(4).upper() for _ in range(n)]


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@app.route('/')
def landing():
    return render_template('landing.html')


@app.route('/login')
def login_page():
    user = get_current_user()
    if user:
        return redirect(url_for('subscriber_dashboard'))
    return render_template('login.html')


# ---------------------------------------------------------------------------
# Subscriber portal
# ---------------------------------------------------------------------------

@app.route('/subscriber/')
@app.route('/subscriber')
@login_required
def subscriber_dashboard():
    return render_template('subscriber/portfolio.html', user=g.current_user)


@app.route('/subscriber/strategies')
@login_required
def subscriber_strategies():
    return render_template('subscriber/strategies.html', user=g.current_user)


@app.route('/subscriber/market')
@login_required
def subscriber_market():
    return render_template('subscriber/market.html', user=g.current_user)


@app.route('/subscriber/broker')
@login_required
def subscriber_broker():
    db = get_db()
    conn = db.execute('SELECT * FROM broker_connections WHERE user_id = ?', (g.current_user['id'],)).fetchone()
    return render_template('subscriber/broker.html', user=g.current_user, connection=conn)


@app.route('/subscriber/settings')
@login_required
def subscriber_settings():
    return render_template('subscriber/settings.html', user=g.current_user)


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------

@app.route('/admin')
@app.route('/admin/')
@admin_required
def admin_index():
    db = get_db()
    users = db.execute('SELECT id, email, role, is_active, totp_enabled, created_at, last_login FROM users ORDER BY created_at DESC').fetchall()
    waitlist = db.execute('SELECT * FROM waitlist ORDER BY created_at DESC').fetchall()
    stats = {
        'total_users': db.execute('SELECT COUNT(*) FROM users').fetchone()[0],
        'active_users': db.execute('SELECT COUNT(*) FROM users WHERE is_active=1').fetchone()[0],
        'waitlist_count': db.execute('SELECT COUNT(*) FROM waitlist').fetchone()[0],
        'trades_today': db.execute("SELECT COUNT(*) FROM trade_history WHERE date(executed_at)=date('now')").fetchone()[0],
    }
    return render_template('admin/index.html', user=g.current_user, users=users, waitlist=waitlist, stats=stats)


# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------

@app.route('/rpc/auth/login', methods=['POST'])
def api_login():
    data = request.get_json(force=True)
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    totp_code = data.get('totp_code') or ''

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

    if not user or not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
        return jsonify({'error': 'Invalid email or password'}), 401

    if not user['is_active']:
        return jsonify({'error': 'Account is disabled'}), 403

    if user['totp_enabled']:
        if not totp_code:
            return jsonify({'requires_2fa': True}), 200
        totp = pyotp.TOTP(user['totp_secret'])
        backup_codes = json.loads(user['backup_codes'] or '[]')
        if not totp.verify(totp_code, valid_window=1) and totp_code.upper() not in backup_codes:
            return jsonify({'error': 'Invalid 2FA code'}), 401
        if totp_code.upper() in backup_codes:
            backup_codes.remove(totp_code.upper())
            db.execute('UPDATE users SET backup_codes=? WHERE id=?', (json.dumps(backup_codes), user['id']))

    db.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (user['id'],))
    db.commit()

    token = make_token(user['id'], user['role'])
    resp = make_response(jsonify({'ok': True, 'role': user['role']}))
    resp.set_cookie('rc_token', token, httponly=True, samesite='Lax', max_age=3600 * 8)
    return resp


@app.route('/rpc/auth/logout', methods=['POST'])
def api_logout():
    resp = make_response(jsonify({'ok': True}))
    resp.delete_cookie('rc_token')
    return resp


@app.route('/rpc/auth/me')
@login_required
def api_me():
    u = g.current_user
    return jsonify({
        'id': u['id'],
        'email': u['email'],
        'role': u['role'],
        'totp_enabled': bool(u['totp_enabled']),
    })


@app.route('/rpc/auth/2fa/enroll', methods=['POST'])
@login_required
def api_2fa_enroll():
    u = g.current_user
    if u['totp_enabled']:
        return jsonify({'error': 'Already enrolled'}), 400
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=u['email'], issuer_name='Reccos Capital')

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    db = get_db()
    db.execute('UPDATE users SET totp_secret=? WHERE id=?', (secret, u['id']))
    db.commit()

    return jsonify({'secret': secret, 'qr': qr_b64})


@app.route('/rpc/auth/2fa/verify', methods=['POST'])
@login_required
def api_2fa_verify():
    data = request.get_json(force=True)
    code = data.get('code') or ''
    u = g.current_user
    db = get_db()
    row = db.execute('SELECT totp_secret FROM users WHERE id=?', (u['id'],)).fetchone()
    if not row or not row['totp_secret']:
        return jsonify({'error': 'No TOTP secret'}), 400

    totp = pyotp.TOTP(row['totp_secret'])
    if not totp.verify(code, valid_window=1):
        return jsonify({'error': 'Invalid code'}), 400

    backup_codes = generate_backup_codes()
    db.execute(
        'UPDATE users SET totp_enabled=1, backup_codes=? WHERE id=?',
        (json.dumps(backup_codes), u['id'])
    )
    db.commit()
    return jsonify({'ok': True, 'backup_codes': backup_codes})


@app.route('/rpc/auth/2fa/disable', methods=['POST'])
@login_required
def api_2fa_disable():
    data = request.get_json(force=True)
    password = data.get('password') or ''
    u = g.current_user
    db = get_db()
    row = db.execute('SELECT password_hash FROM users WHERE id=?', (u['id'],)).fetchone()
    if not bcrypt.checkpw(password.encode(), row['password_hash'].encode()):
        return jsonify({'error': 'Incorrect password'}), 401
    db.execute('UPDATE users SET totp_enabled=0, totp_secret=NULL, backup_codes=NULL WHERE id=?', (u['id'],))
    db.commit()
    return jsonify({'ok': True})


@app.route('/rpc/auth/password-reset', methods=['POST'])
def api_password_reset():
    data = request.get_json(force=True)
    action = data.get('action')
    db = get_db()

    if action == 'request':
        email = (data.get('email') or '').strip().lower()
        user = db.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        if user:
            token = secrets.token_urlsafe(32)
            expires = (datetime.datetime.utcnow() + datetime.timedelta(hours=1)).isoformat()
            db.execute('UPDATE users SET reset_token=?, reset_token_expires=? WHERE id=?',
                       (token, expires, user['id']))
            db.commit()
        return jsonify({'ok': True, 'message': 'If that email exists, a reset link has been sent.'})

    if action == 'reset':
        token = data.get('token') or ''
        new_pw = data.get('password') or ''
        if len(new_pw) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400
        user = db.execute(
            'SELECT id, reset_token_expires FROM users WHERE reset_token=?', (token,)
        ).fetchone()
        if not user:
            return jsonify({'error': 'Invalid or expired token'}), 400
        expires = datetime.datetime.fromisoformat(user['reset_token_expires'])
        if datetime.datetime.utcnow() > expires:
            return jsonify({'error': 'Token expired'}), 400
        pw_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
        db.execute(
            'UPDATE users SET password_hash=?, reset_token=NULL, reset_token_expires=NULL WHERE id=?',
            (pw_hash, user['id'])
        )
        db.commit()
        return jsonify({'ok': True})

    return jsonify({'error': 'Unknown action'}), 400


@app.route('/rpc/auth/change-password', methods=['POST'])
@login_required
def api_change_password():
    data = request.get_json(force=True)
    current = data.get('current') or ''
    new_pw = data.get('new_password') or ''
    if len(new_pw) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    db = get_db()
    row = db.execute('SELECT password_hash FROM users WHERE id=?', (g.current_user['id'],)).fetchone()
    if not bcrypt.checkpw(current.encode(), row['password_hash'].encode()):
        return jsonify({'error': 'Current password is incorrect'}), 401
    pw_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
    db.execute('UPDATE users SET password_hash=? WHERE id=?', (pw_hash, g.current_user['id']))
    db.commit()
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Waitlist API
# ---------------------------------------------------------------------------

@app.route('/rpc/waitlist', methods=['POST'])
def api_waitlist():
    data = request.get_json(force=True)
    email = (data.get('email') or '').strip().lower()
    if not email or '@' not in email:
        return jsonify({'error': 'Invalid email'}), 400
    db = get_db()
    try:
        db.execute('INSERT INTO waitlist (email) VALUES (?)', (email,))
        db.commit()
    except sqlite3.IntegrityError:
        pass
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------

@app.route('/rpc/admin/users', methods=['GET'])
@admin_required
def api_admin_users():
    db = get_db()
    rows = db.execute(
        'SELECT id, email, role, is_active, totp_enabled, created_at, last_login FROM users ORDER BY created_at DESC'
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/rpc/admin/users', methods=['POST'])
@admin_required
def api_admin_create_user():
    data = request.get_json(force=True)
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or secrets.token_urlsafe(12)
    role = data.get('role', 'subscriber')
    if not email:
        return jsonify({'error': 'Email required'}), 400
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    db = get_db()
    try:
        db.execute('INSERT INTO users (email, password_hash, role) VALUES (?,?,?)', (email, pw_hash, role))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Email already exists'}), 409
    return jsonify({'ok': True, 'email': email, 'temp_password': password})


@app.route('/rpc/admin/users/<int:uid>/toggle', methods=['POST'])
@admin_required
def api_admin_toggle_user(uid):
    db = get_db()
    row = db.execute('SELECT is_active FROM users WHERE id=?', (uid,)).fetchone()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    db.execute('UPDATE users SET is_active=? WHERE id=?', (0 if row['is_active'] else 1, uid))
    db.commit()
    return jsonify({'ok': True})


@app.route('/rpc/admin/stats')
@admin_required
def api_admin_stats():
    db = get_db()
    return jsonify({
        'total_users': db.execute('SELECT COUNT(*) FROM users').fetchone()[0],
        'active_users': db.execute('SELECT COUNT(*) FROM users WHERE is_active=1').fetchone()[0],
        'waitlist_count': db.execute('SELECT COUNT(*) FROM waitlist').fetchone()[0],
        'total_trades': db.execute('SELECT COUNT(*) FROM trade_history').fetchone()[0],
    })


# ---------------------------------------------------------------------------
# Portfolio data API
# ---------------------------------------------------------------------------

@app.route('/rpc/portfolio/trades')
@login_required
def api_portfolio_trades():
    db = get_db()
    rows = db.execute(
        'SELECT * FROM trade_history WHERE user_id=? ORDER BY executed_at DESC LIMIT 50',
        (g.current_user['id'],)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/rpc/portfolio/pnl')
@login_required
def api_portfolio_pnl():
    import random
    random.seed(g.current_user['id'])
    today = datetime.date.today()
    data = []
    value = 100000
    for i in range(30, -1, -1):
        d = today - datetime.timedelta(days=i)
        value += random.uniform(-2000, 3000)
        data.append({'date': d.isoformat(), 'value': round(value, 2)})
    return jsonify(data)


# ---------------------------------------------------------------------------
# Broker API
# ---------------------------------------------------------------------------

@app.route('/rpc/broker/connect', methods=['POST'])
@login_required
def api_broker_connect():
    data = request.get_json(force=True)
    broker = data.get('broker')
    api_key = data.get('api_key') or ''
    if not broker or not api_key:
        return jsonify({'error': 'Broker and API key required'}), 400
    last4 = api_key[-4:] if len(api_key) >= 4 else api_key
    db = get_db()
    db.execute(
        '''INSERT INTO broker_connections (user_id, broker, api_key_last4, connected_at)
           VALUES (?,?,?,datetime('now'))
           ON CONFLICT(user_id) DO UPDATE SET broker=excluded.broker,
           api_key_last4=excluded.api_key_last4, connected_at=excluded.connected_at''',
        (g.current_user['id'], broker, last4)
    )
    db.commit()
    return jsonify({'ok': True})


@app.route('/rpc/broker/disconnect', methods=['POST'])
@login_required
def api_broker_disconnect():
    db = get_db()
    db.execute('DELETE FROM broker_connections WHERE user_id=?', (g.current_user['id'],))
    db.commit()
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# App startup
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
