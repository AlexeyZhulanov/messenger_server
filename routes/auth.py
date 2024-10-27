from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Log
from .uploads import delete_avatar_file_if_exists
from datetime import datetime, timezone
from app import socketio, logger

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        existing_user = User.query.filter_by(name=data['name']).first()

        if existing_user:
            return jsonify({'error': 'User with this name already exists'}), 400
        
        hashed_password = generate_password_hash(data['password'], method='pbkdf2:sha256')
        new_user = User(name=data['name'], password=hashed_password, username=data['username'])
        db.session.add(new_user)
        db.session.commit()
        logger.info(f"New user registered, his name: {new_user.name}")
        return jsonify({'message': 'Registered successfully'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        user = User.query.filter_by(name=data['name']).first()
        if user and check_password_hash(user.password, data['password']):
            access_token = create_access_token(identity=user.id)
            return jsonify(access_token=access_token)
        return jsonify({'message': 'Invalid credentials'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/update_profile', methods=['PUT'])
@jwt_required()
def update_profile():
    try:
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        data = request.get_json()
        user.username = data.get('username', user.username)
        avatar = data.get('avatar', user.avatar)
        if avatar == "delete":
            if user.avatar:
                delete_avatar_file_if_exists(user.avatar)
            user.avatar = None
        elif avatar:
            if user.avatar:
                delete_avatar_file_if_exists(user.avatar)
            user.avatar = avatar
            logger.info(f"User {user.name} updated his avatar: {avatar}")
        db.session.commit()
        return jsonify({'message': 'Profile updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/update_password', methods=['PUT'])
@jwt_required()
def update_password():
    try:
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            log = Log(id_user=user_id, action="update_password", content="Failed to change password(User not found)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "User not found"}), 404

        data = request.get_json()
        new_password = data.get('password')
        if not new_password:
            log = Log(id_user=user_id, action="update_password", content="Failed to change password(No new password provided)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "No new password provided"}), 400

        user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
        log = Log(id_user=user_id, action="update_password", content="Password successfully updated")
        db.session.add(log)
        db.session.commit()
        return jsonify({"message": "Password updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        log = Log(id_user=user_id, action="update_password", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/update_last_session/<int:id_dialog>', methods=['PUT'])
@jwt_required()
def update_last_session(id_dialog):
    user_id = get_jwt_identity()
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        user.last_session = datetime.now(timezone.utc)
        db.session.commit()

        # Уведомление через WebSocket
        socketio.emit('user_session_updated', {
            'user_id': user_id,
            'last_session': int(user.last_session.timestamp() * 1000 + 10800000)
        }, room=f'dialog_{id_dialog}')

        return jsonify({"message": "Last session time updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/last_session/<int:user_id>', methods=['GET'])
@jwt_required()
def get_last_session(user_id):
    try:
        # Поиск пользователя по id или username
        user = User.query.filter(User.id == user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        return jsonify({"last_session": user.last_session}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/user/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user(user_id):
    try:
        # Если передано 0, получаем текущего пользователя по токену
        if user_id == 0:
            current_user_id = get_jwt_identity()
            user = User.query.get(current_user_id)
        else:
            user = User.query.get(user_id)

        if not user:
            return jsonify({"error": "User with given ID not found"}), 404

        user_data = {
            "id": user.id,
            "name": user.name,
            "username": user.username,
            "avatar": user.avatar
        }

        return jsonify(user_data), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
