import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.secret_key = "commercial_utility_secret_key"

    # Absolute path to instance/utilities.db in project root
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    instance_dir = os.path.join(base_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    
    db_path = os.path.join(instance_dir, 'utilities.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Bind SQLAlchemy to this Flask app instance
    db.init_app(app)

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
        db.create_all()

    return app