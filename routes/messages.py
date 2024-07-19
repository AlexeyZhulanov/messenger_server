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
    other_user = User.query.filter_by(username=data['username']).first()
    if not other_user:
        return jsonify({'message': 'User not found'}), 404

    new_dialog = Dialog(user1_id=user_id, user2_id=other_user.id)
    db.session.add(new_dialog)
    db.session.commit()
    return jsonify({'message': 'Dialog created successfully'}), 201


@messages_bp.route('/dialogs', methods=['GET'])
@jwt_required()
def get_dialogs():
    user_id = get_jwt_identity()
    try:
        # Проверяем наличие атрибутов в модели
        if not hasattr(Dialog, 'user1_id') or not hasattr(Dialog, 'user2_id'):
            return jsonify(
                {"error": "The 'Dialog' model does not have required attributes 'user1_id' and 'user2_id'"}), 400

        dialogs = Dialog.query.filter((Dialog.user1_id == user_id) | (Dialog.user2_id == user_id)).all()

        dialog_list = []
        for dialog in dialogs:
            other_user_id = dialog.user1_id if dialog.user1_id != user_id else dialog.user2_id
            other_user = User.query.get(other_user_id)
            last_message = Message.query.filter_by(dialog_id=dialog.id).order_by(Message.timestamp.desc()).first()
            dialog_list.append({
                "dialog_id": dialog.id,
                "other_user": {
                    "id": other_user.id,
                    "name": other_user.name
                },
                "last_message": {
                    "text": last_message.text,
                    "timestamp": last_message.timestamp
                }
            })
        return jsonify(dialog_list), 200
    except NoSuchColumnError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "An error occurred while processing your request"}), 500
