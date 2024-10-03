from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, decode_token
from flask_socketio import emit, join_room, leave_room, disconnect
from models import (db, Message, Dialog, User, Group, GroupMessage, GroupMember, increment_message_count,
                    decrement_message_count)
from .uploads import delete_file_from_disk
from app import socketio, logger, dramatiq
from jwt.exceptions import ExpiredSignatureError


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

    # Уведомление участников через WebSocket
    socketio.emit('dialog_created', {
        'dialog_id': new_dialog.id,
        'message': f"Dialog created between {user.username} and {other_user.username}"
    }, room=f'dialog_{new_dialog.id}')

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
        reference_to_message_id = data.get('reference_to_message_id')
        is_forwarded = data.get('is_forwarded')
        username_author_original = data.get('username_author_original')

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
            is_edited=False,
            is_forwarded=is_forwarded,
            username_author_original=username_author_original,
            reference_to_message_id=reference_to_message_id
        )
        db.session.add(message)
        db.session.commit()

        increment_message_count(dialog_id=id_dialog)

        # Уведомление участников через WebSocket
        socketio.emit('new_message', {
            'id': message.id,
            'id_dialog': message.id_dialog,
            'id_sender': message.id_sender,
            'text': message.text,
            'images': message.images,
            'voice': message.voice,
            'file': message.file,
            'is_edited': message.is_edited,
            'is_forwarded': message.is_forwarded,
            'username_author_original': message.username_author_original,
            'reference_to_message_id': message.reference_to_message_id,
            'timestamp': int(message.timestamp.timestamp() * 1000 + 10800000)
        }, room=f'dialog_{message.id_dialog}')

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
        page = request.args.get('page', type=int)
        size = request.args.get('size', type=int)

        if page is None or size is None:
            return jsonify({'error': 'id_dialog, page, and size parameters are required'}), 400

        query = Message.query.filter_by(id_dialog=id_dialog).order_by(Message.timestamp.asc())
        total_count = query.count()
        end = min(total_count, total_count - page * size)
        start = max(0, total_count - (page + 1) * size)
        messages = query.slice(start, end).all()

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
                "timestamp": msg.timestamp,
                "reference_to_message_id": msg.reference_to_message_id,
                "is_forwarded": msg.is_forwarded,
                "username_author_original": msg.username_author_original
            }
            for msg in messages
        ]

        return jsonify(messages_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/message/<int:message_id>', methods=['GET'])
@jwt_required()
def get_message_by_id(message_id):
    try:
        user_id = get_jwt_identity()

        message = Message.query.get(message_id)
        if not message:
            return jsonify({"error": "Message not found"}), 404

        dialog = Dialog.query.get(message.id_dialog)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404
        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
            return jsonify({"error": "You are not a participant in this dialog"}), 403

        all_messages = Message.query.filter_by(id_dialog=message.id_dialog).order_by(Message.timestamp.asc()).all()

        # Определяем порядковый номер сообщения, отсчитывая с конца списка
        message_position = None
        total_messages = len(all_messages)
        for index, msg in enumerate(all_messages):
            if msg.id == message.id:
                message_position = total_messages - index - 1  # Индексация с конца, начиная с нуля
                break

        if message_position is None:
            return jsonify({"error": "Message not found in the dialog"}), 404

        message_data = {
            "id": message.id,
            "id_sender": message.id_sender,
            "id_dialog": message.id_dialog,
            "text": message.text,
            "images": message.images,
            "voice": message.voice,
            "file": message.file,
            "is_read": message.is_read,
            "is_edited": message.is_edited,
            "timestamp": message.timestamp,
            "reference_to_message_id": message.reference_to_message_id,
            "is_forwarded": message.is_forwarded,
            "username_author_original": message.username_author_original,
            "position": message_position
        }

        return jsonify(message_data), 200

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
        if 'text' in data and message.text != data['text']:
            message.text = data['text']
            message.is_edited = True

        if 'images' in data and message.images != data['images']:
            # Удаляем старые изображения
            if message.images:
                for image in message.images:
                    delete_file_from_disk('photos', image)
            message.images = data['images']
            message.is_edited = True

        elif 'file' in data and message.file != data['file']:
            # Удаляем старый файл
            if message.file:
                delete_file_from_disk('files', message.file)
            message.file = data['file']
            message.is_edited = True
        
        elif 'voice' in data and message.voice != data['voice']:
            # Удаляем старый голосовой файл
            if message.voice:
                delete_file_from_disk('audio', message.voice)
            message.voice = data['voice']
            message.is_edited = True

        db.session.commit()

        # Уведомление участников через WebSocket
        socketio.emit('message_edited', {
            'id': message.id,
            'id_dialog': message.id_dialog,
            'id_sender': message.id_sender,
            'text': message.text,
            'images': message.images,
            'voice': message.voice,
            'file': message.file,
            'is_edited': message.is_edited,
            'is_forwarded': message.is_forwarded,
            'username_author_original': message.username_author_original,
            'reference_to_message_id': message.reference_to_message_id,
            'timestamp': int(message.timestamp.timestamp() * 1000 + 10800000)
        }, room=f'dialog_{message.id_dialog}')

        return jsonify({'message': 'Message updated successfully'}), 200
    except Exception as e:
        db.session.rollback() # Откат транзакции в случае ошибки
        return jsonify({'error': str(e)}), 500


def delete_files_for_message(message):
    # Удаление изображений, если они есть
    if message.images:
        for image in message.images:
            delete_file_from_disk('photos', image)

    # Удаление обычного файла, если он есть
    elif message.file:
        delete_file_from_disk('files', message.file)

    # Удаление голосового файла, если он есть
    elif message.voice:
        delete_file_from_disk('audio', message.voice)


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
            delete_files_for_message(message)
            db.session.delete(message)

        decrement_message_count(dialog_id=messages[0].id_dialog, count=len(messages))

        db.session.commit()

        # Уведомление участников через WebSocket
        socketio.emit('messages_deleted', {
            'dialog_id': messages[0].id_dialog,
            'deleted_message_ids': message_ids
        }, room=f'dialog_{messages[0].id_dialog}')

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

        messages = Message.query.filter_by(id_dialog=dialog_id).all()
        # Удаляем файлы, прикрепленные к сообщениям
        for message in messages:
            delete_files_for_message(message)

        Message.query.filter_by(id_dialog=dialog_id).delete()
        db.session.delete(dialog)
        db.session.commit()

        # Уведомление участников через WebSocket
        socketio.emit('dialog_deleted', {
            'dialog_id': dialog_id
        }, room=f'dialog_{dialog_id}')

        return jsonify({"message": "Dialog deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()  # Откат транзакции в случае ошибки
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


@dramatiq.actor
def delete_messages_task(message_ids, dialog_id):
    try:
        # Удаление сообщений
        Message.query.filter(Message.id.in_(message_ids)).delete(synchronize_session=False)
        db.session.commit()

        # Уведомление через WebSocket
        socketio.emit('messages_deleted', {
            'dialog_id': dialog_id,
            'deleted_message_ids': message_ids
        }, room=f'dialog_{dialog_id}')

    except Exception as e:
        db.session.rollback()
        print(f"Error deleting messages: {str(e)}")


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

        # Если в диалоге установлен интервал автоудаления сообщений
        if dialog.auto_delete_interval > 0:
            # Определяем время автоудаления в секундах (если требуется учитывать секунды)
            delete_interval_seconds = dialog.auto_delete_interval

            # Убедимся, что автоудаление происходит корректно
            if delete_interval_seconds >= 60:
                logger.info(f"Удаление сообщений будет запланировано через {delete_interval_seconds // 60} минут.")
            else:
                logger.info(f"Удаление сообщений будет запланировано через {delete_interval_seconds} секунд.")

            # Запуск задачи для удаления сообщений через указанный интервал времени
            delete_messages_task.send_with_options(
            args=[message_ids, dialog.id],
            delay=delete_interval_seconds * 1000
            )

        # Уведомление участников через WebSocket
        socketio.emit('messages_read', {
            'dialog_id': messages[0].id_dialog,
            'messages_read_ids': message_ids
        }, room=f'dialog_{messages[0].id_dialog}')

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

    message_list = [
    {
        "id": message.id,
        "id_sender": message.id_sender,
        "id_dialog": message.id_dialog,
        "text": message.text,
        "images": message.images,
        "voice": message.voice,
        "file": message.file,
        "is_read": message.is_read,
        "is_edited": message.is_edited,
        "timestamp": message.timestamp,
        "reference_to_message_id": message.reference_to_message_id,
        "is_forwarded": message.is_forwarded,
        "username_author_original": message.username_author_original
    } for message in messages]

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
                "count_msg": dialog.count_msg,
                "can_delete": dialog.can_delete,
                "auto_delete_interval": dialog.auto_delete_interval
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
                "count_msg": group.count_msg,
                "can_delete": group.can_delete,
                "auto_delete_interval": group.auto_delete_interval
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
        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
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
        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
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
        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
            return jsonify({"error": "You are not a participant in this dialog"}), 403

        messages = Message.query.filter_by(id_dialog=dialog_id).all()
        # Удаление файлов для каждого сообщения
        for message in messages:
            delete_files_for_message(message)

        Message.query.filter_by(id_dialog=dialog_id).delete()
        db.session.commit()

        # Уведомление участников через WebSocket
        socketio.emit('dialog_messages_all_deleted', {
            'dialog_id': dialog_id
        }, room=f'dialog_{dialog_id}')

        return jsonify({"message": "All messages in the dialog deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()  # Откат транзакции в случае ошибки
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


@socketio.on('typing')
def handle_typing_event(data):
    """
    Обрабатывает событие начала набора текста.
    :param data: данные о диалоге и пользователе, который набирает текст.
    """
    token = request.headers.get('Authorization')
    if token and token.startswith("Bearer "):
        token = token.split("Bearer ")[1]
    else:
        logger.info("Missing or invalid Authorization header")
        disconnect()
        return

    try:
        # Декодируем токен и получаем информацию о пользователе
        decoded_token = decode_token(token)
        user_id = decoded_token['sub']

        dialog_id = data.get('dialog_id')

        if dialog_id:
            emit('typing', {'dialog_id': dialog_id, 'user_id': user_id}, room=f'dialog_{dialog_id}')
    except Exception as e:
        logger.info(f"Invalid token: {e}")
        disconnect()


@socketio.on('stop_typing')
def handle_stop_typing_event(data):
    """
    Обрабатывает событие завершения набора текста.
    :param data: данные о диалоге и пользователе, который прекратил набор текста.
    """
    token = request.headers.get('Authorization')
    if token and token.startswith("Bearer "):
        token = token.split("Bearer ")[1]
    else:
        logger.info("Missing or invalid Authorization header")
        disconnect()
        return

    try:
        # Декодируем токен и получаем информацию о пользователе
        decoded_token = decode_token(token)
        user_id = decoded_token['sub']

        dialog_id = data.get('dialog_id')

        if dialog_id:
            emit('stop_typing', {'dialog_id': dialog_id, 'user_id': user_id}, room=f'dialog_{dialog_id}')
    except Exception as e:
        logger.info(f"Invalid token: {e}")
        disconnect()


@socketio.on('join_dialog')
def handle_join_dialog(data):
    """
    Обрабатывает событие присоединения к диалогу.
    :param data: данные о диалоге.
    """
    token = request.headers.get('Authorization')
    if token and token.startswith("Bearer "):
        token = token.split("Bearer ")[1]
    else:
        logger.info("Missing or invalid Authorization header")
        disconnect()
        return

    try:
        # Декодируем токен и получаем информацию о пользователе
        decoded_token = decode_token(token)
        user_id = decoded_token['sub']  # Извлекаем user_id из токена

        dialog_id = data.get('dialog_id')

        if dialog_id:
            # Присоединяем пользователя к комнате, соответствующей диалогу
            join_room(f'dialog_{dialog_id}')
            emit('user_joined', {'dialog_id': dialog_id, 'user_id': user_id}, room=f'dialog_{dialog_id}')
            logger.info(f"Joined Dialog ID: {dialog_id}")
    except ExpiredSignatureError:
        logger.info("Token expired")
        emit('token_expired', {'message': 'Token has expired'})
        disconnect()  # Разрываем соединение
    except Exception as e:
        logger.info(f"Invalid token: {e}")
        disconnect()  # Разрываем соединение в случае невалидного токена


@socketio.on('leave_dialog')
def handle_leave_dialog(data):
    """
    Обрабатывает событие выхода из диалога.
    :param data: данные о диалоге.
    """
    token = request.headers.get('Authorization')
    if token and token.startswith("Bearer "):
        token = token.split("Bearer ")[1]
    else:
        logger.info("Missing or invalid Authorization header")
        disconnect()
        return

    try:
        # Декодируем токен и получаем информацию о пользователе
        decoded_token = decode_token(token)
        user_id = decoded_token['sub']

        dialog_id = data.get('dialog_id')
        logger.info(f"Left Dialog ID: {dialog_id}")

        if dialog_id:
            leave_room(f'dialog_{dialog_id}')
            emit('user_left', {'dialog_id': dialog_id, 'user_id': user_id}, room=f'dialog_{dialog_id}')
    except Exception as e:
        logger.info(f"Invalid token: {e}")
        disconnect()
