from flask import Flask
from flask_jwt_extended import JWTManager
from config import Config
from models import db
import os

app = Flask(__name__)


def create_app():
    app.config.from_object(Config)

    db.init_app(app)
    jwt = JWTManager(app)

    with app.app_context():
        for folder in [app.config['UPLOAD_FOLDER_PHOTOS'], app.config['UPLOAD_FOLDER_AUDIO'], app.config['UPLOAD_FOLDER_FILES']]:
            if not os.path.exists(folder):
                os.makedirs(folder)

        # Create database tables
        db.create_all()

    from routes.auth import auth_bp
    from routes.messages import messages_bp
    from routes.groups import groups_bp
    from routes.uploads import uploads_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(uploads_bp)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
