import os
import secrets
from flask import Flask, flash, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.exceptions import RequestEntityTooLarge

db = SQLAlchemy()
csrf = CSRFProtect()

# Largest upload accepted (a year of daily readings is well under 1 MB)
MAX_UPLOAD_MB = 5

def load_secret_key(instance_dir: str) -> str:
    """
    The key that signs session cookies (flash messages, CSRF tokens). Taken from
    the SECRET_KEY environment variable if set; otherwise a random key is
    generated once and kept in instance/secret_key, outside version control.
    """
    if os.environ.get('SECRET_KEY'):
        return os.environ['SECRET_KEY']
    key_path = os.path.join(instance_dir, 'secret_key')
    if not os.path.exists(key_path):
        with open(key_path, 'w') as f:
            f.write(secrets.token_hex(32))
    with open(key_path) as f:
        return f.read().strip()

def create_app():
    app = Flask(__name__)

    # Absolute path to instance/utilities.db in project root
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    instance_dir = os.path.join(base_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)

    app.secret_key = load_secret_key(instance_dir)
    app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    # CSRF tokens last as long as the browser session, so a form left open
    # for a while can still be submitted
    app.config['WTF_CSRF_TIME_LIMIT'] = None

    db_path = os.path.join(instance_dir, 'utilities.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Bind SQLAlchemy to this Flask app instance
    db.init_app(app)
    # Every POST form must carry the session's CSRF token
    csrf.init_app(app)

    # Both error handlers redirect within the app only, never to the Referer,
    # so a forged request can't bounce the user to another site
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        flash("The form expired or didn't come from this app. Please try again.", "danger")
        return redirect(url_for('entry.index'))

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(e):
        flash(f"That file is too large; uploads are limited to {MAX_UPLOAD_MB} MB.", "danger")
        return redirect(url_for('entry.index'))

    # Register Blueprints
    from utility_app.blueprints.dashboard.routes import dashboard_bp
    from utility_app.blueprints.entry.routes import entry_bp
    from utility_app.blueprints.reports.routes import reports_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(entry_bp, url_prefix='/entry')
    app.register_blueprint(reports_bp, url_prefix='/reports')

    with app.app_context():
        # Ensure database tables exist without wiping existing records
        from utility_app import models
        # The old weather cache (temperature and degree-days only, for the
        # previous location) was replaced by daily_weather; it held nothing
        # that can't be downloaded again
        db.session.execute(text('DROP TABLE IF EXISTS daily_weather_cache'))
        db.session.commit()
        db.create_all()

    return app
