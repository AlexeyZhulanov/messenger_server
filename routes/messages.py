from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.exc import NoSuchColumnError

from models import db, Message, Dialog, User

messages_bp = Blueprint('messages', __name__)


@messages_bp.route('/dialogs', methods=['POST'])
@jwt_required()
def create_dialog():
    user_id = get_jwt_identity()
    data = request.get_json()
    other_user = User.query.filter_by(name=data['name']).first()
    if not other_user:
        return jsonify({'message': 'User not found'}), 404

    new_dialog = Dialog(id_user1=user_id, id_user2=other_user.id)
    db.session.add(new_dialog)
    db.session.commit()
    return jsonify({'message': 'Dialog created successfully'}), 201


@messages_bp.route('/dialogs', methods=['GET'])
@jwt_required()
def get_dialogs():
    user_id = get_jwt_identity()
    try:
        # Проверяем наличие атрибутов в модели
        if not hasattr(Dialog, 'id_user1') or not hasattr(Dialog, 'id_user2'):
            return jsonify(
                {"error": "The 'Dialog' model does not have required attributes 'id_user1' and 'id_user2'"}), 400

        dialogs = Dialog.query.filter((Dialog.id_user1 == user_id) | (Dialog.id_user2 == user_id)).all()

        dialog_list = []
        for dialog in dialogs:
            other_user_id = dialog.id_user1 if dialog.id_user1 != user_id else dialog.id_user2
            other_user = User.query.get(other_user_id)
            last_message = Message.query.filter_by(id_dialog=dialog.id).order_by(Message.timestamp.desc()).first()

            dialog_data = {
                "dialog_id": dialog.id,
                "other_user": {
                    "id": other_user.id,
                    "name": other_user.name
                },
                "last_message": {
                    "text": last_message.text if last_message else None,
                    "timestamp": last_message.timestamp if last_message else None
                }
            }
            dialog_list.append(dialog_data)

        return jsonify(dialog_list), 200
    except NoSuchColumnError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # Логирование сообщения об ошибке
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/messages', methods=['POST'])
@jwt_required()
def send_message():
    try:
        data = request.get_json()
        id_dialog = data.get('id_dialog')
        id_sender = get_jwt_identity()
        text = data.get('text')
        images = data.get('images')
        voice = data.get('voice')
        file = data.get('file')

        message = Message(
            id_dialog=id_dialog,
            id_sender=id_sender,
            text=text,
            images=images,
            voice=voice,
            file=file,
            is_edited=False
        )
        db.session.add(message)
        db.session.commit()
        return jsonify({"message": "Message sent successfully"}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/messages', methods=['GET'])
@jwt_required()
def get_messages():
    try:
        id_dialog = request.args.get('id_dialog')
        messages = Message.query.filter_by(id_dialog=id_dialog).all()
        messages_data = [{"id": msg.id, "id_sender": msg.id_sender, "text": msg.text, "images": msg.images, "voice": msg.voice, "file": msg.file,
                          "is_read": msg.is_read, "is_edited": msg.is_edited, "timestamp": msg.timestamp} for msg in messages]
        return jsonify(messages_data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>/key', methods=['PUT'])
@jwt_required()
def add_key_to_dialog(dialog_id):
    try:
        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        data = request.get_json()
        key = data.get('key')
        if not key:
            return jsonify({"error": "No key provided"}), 400

        dialog.key = key
        db.session.commit()
        return jsonify({"message": "Key added to dialog"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>/key', methods=['DELETE'])
@jwt_required()
def remove_key_from_dialog(dialog_id):
    try:
        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        dialog.key = None
        db.session.commit()
        return jsonify({"message": "Key removed from dialog"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/messages/<int:message_id>', methods=['PUT'])
@jwt_required()
def edit_message(message_id):
    try:
        data = request.get_json()
        message = Message.query.get(message_id)
        if not message:
            return jsonify({'message': 'Message not found'}), 404

        if 'text' in data:
            message.text = data['text']
            message.is_edited = True
        if 'images' in data:
            message.images = data['images']
        if 'voice' in data:
            message.voice = data['voice']
        if 'file' in data:
            message.file = data['file']

        db.session.commit()
        return jsonify({'message': 'Message updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/messages/<int:message_id>', methods=['DELETE'])
@jwt_required()
def delete_message(message_id):
    try:
        message = Message.query.get(message_id)
        if not message:
            return jsonify({"error": "Message not found"}), 404

        db.session.delete(message)
        db.session.commit()
        return jsonify({"message": "Message deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>', methods=['DELETE'])
@jwt_required()
def delete_dialog(dialog_id):
    try:
        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        db.session.delete(dialog)
        db.session.commit()
        return jsonify({"message": "Dialog deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/users', methods=['GET'])
@jwt_required()
def get_users():
    try:
        user_id = get_jwt_identity()

        # Получить список пользователей, с которыми есть диалоги
        dialogs = Dialog.query.filter((Dialog.id_user1 == user_id) | (Dialog.id_user2 == user_id)).all()
        dialog_user_ids = {d.id_user1 if d.id_user1 != user_id else d.id_user2 for d in dialogs}

        # Получить всех пользователей, кроме текущего пользователя и пользователей, с которыми есть диалоги
        users = User.query.filter(User.id != user_id, User.id.notin_(dialog_user_ids)).all()
        user_list = [{'id': user.id, 'name': user.name} for user in users]

        return jsonify(user_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500