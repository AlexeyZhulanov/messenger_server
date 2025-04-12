from flask import Flask
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from config import Config
from models import db
from flask_socketio import SocketIO
import dramatiq
from dramatiq.brokers.redis import RedisBroker
import os
import logging

app = Flask(__name__)
logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
logger = logging.getLogger(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", message_queue='redis://localhost:6379')  # Поддержка CORS для клиента
redis_broker = RedisBroker(host="localhost", port=6379)
dramatiq.set_broker(redis_broker)
jwt = JWTManager(app)
#migrate = Migrate()


def create_app():
    app.config.from_object(Config)

    db.init_app(app)
    #migrate.init_app(app, db)

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
    from routes.logs import logs_bp
    from routes.news import news_bp
    from routes.gitlab import gitlab_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(gitlab_bp)

    return app


app = create_app()

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, use_reloader=False)
