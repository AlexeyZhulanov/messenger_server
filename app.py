from flask import Flask
from flask_jwt_extended import JWTManager
from config import Config
from models import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    jwt = JWTManager(app)

    with app.app_context():
        db.create_all()

    from routes.auth import auth_bp
    from routes.messages import messages_bp
    from routes.groups import groups_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(groups_bp)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
