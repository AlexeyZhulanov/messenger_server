from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import (db, Message, Dialog, User, Group, GroupMessage, GroupMember, increment_message_count,
                    decrement_message_count)

messages_bp = Blueprint('messages', __name__)


@messages_bp.route('/dialogs', methods=['POST'])
@jwt_required()
def create_dialog():
    user_id = get_jwt_identity()
    data = request.get_json()
    other_user = User.query.filter_by(name=data['name']).first()

    if not other_user:
        return jsonify({'message': 'User not found'}), 404

    # Проверка на существование диалога
    existing_dialog = Dialog.query.filter(
        ((Dialog.id_user1 == user_id) & (Dialog.id_user2 == other_user.id)) |
        ((Dialog.id_user1 == other_user.id) & (Dialog.id_user2 == user_id))
    ).first()

    if existing_dialog:
        return jsonify({'message': 'Dialog already exists'}), 409

    # Создание нового диалога
    new_dialog = Dialog(id_user1=user_id, id_user2=other_user.id)
    db.session.add(new_dialog)
    db.session.commit()

    # Отправка сообщения о создании диалога
    user = User.query.get(user_id)
    creation_message = Message(
        id_dialog=new_dialog.id,
        id_sender=user_id,
        text=f"{user.username} has created a dialog"
    )
    db.session.add(creation_message)
    db.session.commit()
    increment_message_count(dialog_id=new_dialog.id)

    return jsonify({'message': 'Dialog created successfully'}), 201


@messages_bp.route('/messages', methods=['POST'])
@jwt_required()
def send_message():
    try:
        id_dialog = request.args.get('id_dialog')
        data = request.get_json()
        id_sender = get_jwt_identity()
        text = data.get('text')
        images = data.get('images')
        voice = data.get('voice')
        file = data.get('file')

        # Проверка на существование диалога
        dialog = Dialog.query.get(id_dialog)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        # Проверка на участие отправителя в диалоге
        if dialog.id_user1 != id_sender and dialog.id_user2 != id_sender:
            return jsonify({"error": "You are not a participant in this dialog"}), 403

        # Создание и сохранение нового сообщения
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

        increment_message_count(dialog_id=id_dialog)

        return jsonify({"message": "Message sent successfully"}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/messages', methods=['GET'])
@jwt_required()
def get_messages():
    try:
        id_dialog = request.args.get('id_dialog')
        user_id = get_jwt_identity()

        # Проверка на участие пользователя в диалоге
        dialog = Dialog.query.get(id_dialog)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404
        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
            return jsonify({"error": "You are not a participant in this dialog"}), 403

        # Пагинация
        start = request.args.get('start', type=int)
        end = request.args.get('end', type=int)

        if start is None or end is None:
            return jsonify({'error': 'id_dialog, start, and end parameters are required'}), 400

        if start < 0 or end <= start:
            return jsonify({'error': 'Invalid start or end values'}), 400

        messages = Message.query.filter_by(id_dialog=id_dialog).order_by(Message.timestamp.desc()).slice(start,
                                                                                                         end).all()

        messages_data = [
            {
                "id": msg.id,
                "id_sender": msg.id_sender,
                "id_dialog": msg.id_dialog,
                "text": msg.text,
                "images": msg.images,
                "voice": msg.voice,
                "file": msg.file,
                "is_read": msg.is_read,
                "is_edited": msg.is_edited,
                "timestamp": msg.timestamp
            }
            for msg in messages
        ]

        return jsonify(messages_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>/key', methods=['PUT'])
@jwt_required()
def add_key_to_dialog(dialog_id):
    try:
        user_id = get_jwt_identity()
        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
            return jsonify({"error": "You are not a participant in this dialog"}), 403

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
        user_id = get_jwt_identity()
        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
            return jsonify({"error": "You are not a participant in this dialog"}), 403

        dialog.key = None
        db.session.commit()
        return jsonify({"message": "Key removed from dialog"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/messages/<int:message_id>', methods=['PUT'])
@jwt_required()
def edit_message(message_id):
    try:
        user_id = get_jwt_identity()
        message = Message.query.get(message_id)
        if not message:
            return jsonify({'message': 'Message not found'}), 404
        if message.id_sender != user_id:
            return jsonify({'message': 'You can only edit your own messages'}), 403

        data = request.get_json()
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


@messages_bp.route('/messages', methods=['DELETE'])
@jwt_required()
def delete_messages():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        message_ids = data.get('message_ids', [])

        if not message_ids:
            return jsonify({"error": "No message IDs provided"}), 400

        messages = Message.query.filter(Message.id.in_(message_ids)).all()
        if not messages:
            return jsonify({"error": "Some messages not found"}), 404

        # Проверка на участие пользователя в диалоге
        for message in messages:
            dialog = Dialog.query.get(message.id_dialog)
            if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
                return jsonify({"error": "You are not a participant in the dialog of one of the messages"}), 403

        for message in messages:
            db.session.delete(message)

        decrement_message_count(dialog_id=messages[0].id_dialog, count=len(messages))

        db.session.commit()
        return jsonify({"message": "Messages deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()  # Откат транзакции в случае ошибки
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>', methods=['DELETE'])
@jwt_required()
def delete_dialog(dialog_id):
    try:
        user_id = get_jwt_identity()
        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
            return jsonify({"error": "You are not a participant in this dialog"}), 403

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


@messages_bp.route('/messages/read', methods=['PUT'])
@jwt_required()
def mark_messages_as_read():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        message_ids = data.get('message_ids')

        if not message_ids:
            return jsonify({"error": "No message IDs provided"}), 400

        messages = Message.query.filter(Message.id.in_(message_ids)).all()

        if not messages:
            return jsonify({"error": "Messages not found"}), 404

        for message in messages:
            # Проверяем, что текущий пользователь не является отправителем сообщения
            if message.id_sender == user_id:
                return jsonify({"error": "Sender cannot mark their own message as read"}), 400

            # Проверяем, что сообщение относится к диалогу, в котором участвует текущий пользователь
            dialog = Dialog.query.get(message.id_dialog)
            if not dialog or (dialog.id_user1 != user_id and dialog.id_user2 != user_id):
                return jsonify({"error": "Unauthorized to mark this message as read"}), 403

            message.is_read = True

        db.session.commit()
        return jsonify({"message": "Messages marked as read successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>/messages/search', methods=['GET'])
@jwt_required()
def search_messages_in_dialog(dialog_id):
    user_id = get_jwt_identity()
    search_text = request.args.get('q', '')

    if not search_text:
        return jsonify({"error": "Search text must be provided"}), 400

    dialog = Dialog.query.get(dialog_id)
    if not dialog:
        return jsonify({"error": "Dialog not found"}), 404

    if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
        return jsonify({"error": "You are not a participant of this dialog"}), 403

    messages = Message.query.filter(Message.id_dialog == dialog_id, Message.text.ilike(f'%{search_text}%')).all()

    message_list = [{'id': message.id, 'id_sender': message.id_sender, 'text': message.text, 'timestamp': message.timestamp} for message in messages]

    return jsonify(message_list), 200


@messages_bp.route('/conversations', methods=['GET'])
@jwt_required()
def get_conversations():
    user_id = get_jwt_identity()
    try:
        # Получение диалогов
        dialogs = Dialog.query.filter((Dialog.id_user1 == user_id) | (Dialog.id_user2 == user_id)).all()

        dialog_list = []
        for dialog in dialogs:
            other_user_id = dialog.id_user1 if dialog.id_user1 != user_id else dialog.id_user2
            other_user = User.query.get(other_user_id)
            last_message = Message.query.filter_by(id_dialog=dialog.id).order_by(Message.timestamp.desc()).first()

            dialog_data = {
                "type": "dialog",
                "id": dialog.id,
                "key": dialog.key,
                "other_user": {
                    "id": other_user.id,
                    "name": other_user.name,
                    "username": other_user.username,
                    "avatar": other_user.avatar
                },
                "last_message": {
                    "text": last_message.text if last_message else None,
                    "timestamp": last_message.timestamp if last_message else None,
                    "is_read": last_message.is_read if last_message else None
                },
                "count_msg": dialog.count_msg
            }
            dialog_list.append(dialog_data)

        # Получение групп
        group_memberships = GroupMember.query.filter_by(user_id=user_id).all()
        group_ids = [membership.group_id for membership in group_memberships]

        groups = Group.query.filter(Group.id.in_(group_ids)).all()

        group_list = []
        for group in groups:
            last_message = GroupMessage.query.filter_by(group_id=group.id).order_by(
                GroupMessage.timestamp.desc()).first()
            group_data = {
                "type": "group",
                "id": group.id,
                "name": group.name,
                "created_by": group.created_by,
                "avatar": group.avatar,
                "last_message": {
                    "text": last_message.text if last_message else None,
                    "timestamp": last_message.timestamp if last_message else None,
                    "is_read": last_message.is_read if last_message else None
                },
                "count_msg": group.count_msg
            }
            group_list.append(group_data)

        # Объединение и сортировка диалогов и групп по времени последнего сообщения
        conversations = dialog_list + group_list
        sorted_conversations = sorted(conversations, key=lambda x: x['last_message']['timestamp'] if x['last_message'][
            'timestamp'] else 0, reverse=True)

        return jsonify(sorted_conversations), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>/toggle_can_delete', methods=['PUT'])
@jwt_required()
def toggle_dialog_can_delete(dialog_id):
    try:
        user_id = get_jwt_identity()
        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        # Проверка, что пользователь является участником диалога
        if user_id not in dialog.participants:
            return jsonify({"error": "You are not a participant in this dialog"}), 403

        dialog.can_delete = not dialog.can_delete
        db.session.commit()
        return jsonify({"message": "Dialog can_delete flag updated successfully", "can_delete": dialog.can_delete}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>/update_auto_delete_interval', methods=['PUT'])
@jwt_required()
def update_dialog_auto_delete_interval(dialog_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        auto_delete_interval = data.get('auto_delete_interval')

        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        # Проверка, что пользователь является участником диалога
        if user_id not in dialog.participants:
            return jsonify({"error": "You are not a participant in this dialog"}), 403

        dialog.auto_delete_interval = auto_delete_interval
        db.session.commit()
        return jsonify({"message": "Dialog auto_delete_interval updated successfully",
                        "auto_delete_interval": dialog.auto_delete_interval}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>/delete_messages', methods=['DELETE'])
@jwt_required()
def delete_dialog_messages(dialog_id):
    try:
        user_id = get_jwt_identity()
        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        # Проверка, что пользователь является участником диалога
        if user_id not in dialog.participants:
            return jsonify({"error": "You are not a participant in this dialog"}), 403

        Message.query.filter_by(id_dialog=dialog_id).delete()
        db.session.commit()
        return jsonify({"message": "All messages in the dialog deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialog/<int:dialog_id>/settings', methods=['GET'])
@jwt_required()
def get_dialog_settings(dialog_id):
    user_id = get_jwt_identity()
    try:
        dialog = Dialog.query.filter(
            ((Dialog.id_user1 == user_id) | (Dialog.id_user2 == user_id)) &
            (Dialog.id == dialog_id)
        ).first()

        if not dialog:
            return jsonify({"error": "Dialog not found or user not a participant"}), 404

        return jsonify({
            "can_delete": dialog.can_delete,
            "auto_delete_interval": dialog.auto_delete_interval
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
