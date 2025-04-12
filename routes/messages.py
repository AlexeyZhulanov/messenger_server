from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, decode_token
from flask_socketio import emit, join_room, leave_room, disconnect
from models import (db, Dialog, User, Group, GroupMember, Log, increment_message_count,
                    decrement_message_count, create_message_table, get_unread_group_messages_count, do_zero_message_count)
from .uploads import delete_file_from_disk
from app import socketio, logger, dramatiq, app
from fcm import send_push_wakeup
from jwt.exceptions import ExpiredSignatureError
from sqlalchemy import text
from datetime import timezone, timedelta, datetime


messages_bp = Blueprint('messages', __name__)

active_dialogs = {}  # словарь: { user_id: dialog_id }


@messages_bp.route('/dialogs', methods=['POST'])
@jwt_required()
def create_dialog():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        name = data.get('name')
        dialog_key1 = data.get('key_user1')
        dialog_key2 = data.get('key_user2')
        other_user = User.query.filter_by(name=name).first()

        if not other_user:
            log = Log(id_user=user_id, action="create_dialog", content=f"Failed: User '{name}' not found", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({'error': 'User not found'}), 404
        
        if not dialog_key1 or not dialog_key2:
            log = Log(id_user=user_id, action="create_dialog", content=f"Failed: User sent empty key", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({'error': 'Invalid key'}), 400

        # Проверка на существование диалога
        existing_dialog = Dialog.query.filter(
            ((Dialog.id_user1 == user_id) & (Dialog.id_user2 == other_user.id)) |
            ((Dialog.id_user1 == other_user.id) & (Dialog.id_user2 == user_id))
        ).first()

        if existing_dialog:
            log = Log(id_user=user_id, action="create_dialog", content="Failed: Dialog already exists", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({'error': 'Dialog already exists'}), 409

        # Создание нового диалога
        new_dialog = Dialog(id_user1=user_id, id_user2=other_user.id, key_user1=dialog_key1, key_user2 = dialog_key2)
        db.session.add(new_dialog)
        db.session.flush() # Используем flush для получения ID диалога

        create_message_table(new_dialog.id)

        log = Log(id_user=user_id, action="create_dialog", content=f"Dialog created with {other_user.name}")
        db.session.add(log)
        db.session.commit()

        return jsonify({"id_dialog": new_dialog.id}), 200
    except Exception as e:
        db.session.rollback()
        log = Log(id_user=user_id, action="create_dialog", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/messages/<int:id_dialog>', methods=['POST'])
@jwt_required()
def send_message(id_dialog):
    try:
        data = request.get_json()
        id_sender = get_jwt_identity()
        text_content = data.get('text')
        is_url = data.get('is_url')
        images = data.get('images')
        voice = data.get('voice')
        file = data.get('file')
        code = data.get('code')
        code_lang = data.get('code_language')
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

        if file:  
            log = Log(id_user=id_sender, id_dialog=id_dialog, action="send_message", content=f"User sent a file: {file}")
            db.session.add(log)
            db.session.commit()

        # Вставка сообщения в партицированную таблицу
        table_name = f'messages_dialog_{id_dialog}'
        insert_message_query = text(f'''INSERT INTO {table_name} 
        (id_sender, text, images, voice, file, code, code_language, is_edited, is_forwarded, is_url, reference_to_message_id, username_author_original, is_read)
        VALUES (:id_sender, :text, :images, :voice, :file, :code, :code_language, :is_edited, :is_forwarded, :is_url, :reference_to_message_id, :username_author_original, :is_read)
        RETURNING id, timestamp;''')

        result = db.session.execute(insert_message_query, {
            'id_sender': id_sender,
            'text': text_content,
            'images': images,
            'voice': voice,
            'file': file,
            'code': code,
            'code_language': code_lang,
            'is_edited': False,
            'is_forwarded': is_forwarded,
            'is_url' : is_url,
            'is_read': False,
            'reference_to_message_id': reference_to_message_id,
            'username_author_original': username_author_original
        })
        db.session.commit()

        increment_message_count(dialog_id=id_dialog)

        message_id, timestamp = result.fetchone()

        socketio.emit('new_message', {
            'id': message_id,
            'id_sender': id_sender,
            'text': text_content,
            'images': images,
            'voice': voice,
            'file': file,
            'code': code,
            'code_language': code_lang,
            'is_edited': False,
            'is_read': False,
            'is_forwarded': is_forwarded,
            'is_url': is_url,
            'username_author_original': username_author_original,
            'reference_to_message_id': reference_to_message_id,
            'timestamp': int(timestamp.timestamp() * 1000)
        }, room=f'dialog_{id_dialog}')

        user = User.query.get(id_sender)
        other_user_id = dialog.id_user1 if dialog.id_user1 != id_sender else dialog.id_user2

        # Для push-уведомлений
        if active_dialogs.get(other_user_id) != id_dialog:
            socketio.emit('new_message_notification', {
                'chat_id': id_dialog,
                'message_id': message_id,
                'text': text_content,
                'images': images,
                'voice': voice,
                'file': file,
                'code_language': code_lang,
                'id_sender': id_sender,
                'sender_name': user.username,
                'avatar': user.avatar,
                'is_group': False,
                'group_name': None
            }, room=f'user_{other_user_id}')

            # FCM-уведомление, если пользователь оффлайн
            room_name = f"user_{other_user_id}"
            is_online = room_name in socketio.server.manager.rooms.get("/", {})

            if not is_online:
                other_user = User.query.get(other_user_id)
                send_push_wakeup(other_user.fcm_token)

        return jsonify({"message": "Message sent successfully"}), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Необработанная ошибка: {e}")
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/messages/<int:id_dialog>', methods=['GET'])
@jwt_required()
def get_messages(id_dialog):
    try:
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
            return jsonify({'error': 'id_dialog, Page, and size parameters are required'}), 400

        # Вычисляем границы выборки
        offset = page * size

        # Имя таблицы сообщений для диалога
        table_name = f'messages_dialog_{id_dialog}'

        # Получение сообщений с пагинацией
        get_messages_query = text(f'SELECT * FROM {table_name} ORDER BY timestamp DESC LIMIT :limit OFFSET :offset;')
        messages = db.session.execute(get_messages_query, {'limit': size, 'offset': offset}).mappings().all()
        messages.reverse()

        if not messages:
            return jsonify([]), 200

        messages_data = [
            {
                "id": msg['id'],
                "id_sender": msg['id_sender'],
                "text": msg['text'],
                "images": msg['images'],
                "voice": msg['voice'],
                "file": msg['file'],
                "code": msg['code'],
                "code_language": msg['code_language'],
                "is_edited": msg['is_edited'],
                "is_read": msg['is_read'],
                "is_forwarded": msg['is_forwarded'],
                "is_url": msg['is_url'],
                "reference_to_message_id": msg['reference_to_message_id'],
                "username_author_original": msg['username_author_original'],
                "timestamp": msg['timestamp']
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
        id_dialog = request.args.get('id_dialog')
        dialog = Dialog.query.get(id_dialog)
        if not dialog:
            return jsonify({"error": "Dialog not found"}), 404

        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
            return jsonify({"error": "You are not a participant in this dialog"}), 403
        
        # Имя таблицы сообщений для данного диалога
        table_name = f'messages_dialog_{id_dialog}'

        # Получение сообщения по ID
        get_message_query = text(f'SELECT * FROM {table_name} WHERE id = :message_id')
        message = db.session.execute(get_message_query, {'message_id': message_id}).mappings().first()

        if not message:
            return jsonify({"error": "Message not found"}), 404

        get_position_query = text(f'''
        SELECT row_number FROM (
        SELECT id, ROW_NUMBER() OVER (ORDER BY timestamp ASC) AS row_number
        FROM {table_name}) AS numbered_messages WHERE id = :message_id;''')

        message_position = db.session.execute(get_position_query, {'message_id': message['id']}).scalar()

        message_data = {
            "id": message['id'],
            "id_sender": message['id_sender'],
            "text": message['text'],
            "images": message['images'],
            "voice": message['voice'],
            "file": message['file'],
            "code": message['code'],
            "code_language": message['code_language'],
            "is_edited": message['is_edited'],
            "is_read": message['is_read'],
            "is_forwarded": message['is_forwarded'],
            "is_url": message['is_url'],
            "reference_to_message_id": message['reference_to_message_id'],
            "username_author_original": message['username_author_original'],
            "timestamp": message['timestamp'],
            "position": message_position
        }

        return jsonify(message_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@messages_bp.route('/messages/<int:message_id>', methods=['PUT'])
@jwt_required()
def edit_message(message_id):
    try:
        id_user = get_jwt_identity()
        id_dialog = request.args.get('id_dialog')
    
        table_name = f'messages_dialog_{id_dialog}'
        # Проверка существования сообщения
        select_message_query = text(f'SELECT * FROM {table_name} WHERE id = :message_id')
        message = db.session.execute(select_message_query, {'message_id': message_id}).mappings().first()

        if not message:
            log = Log(id_user=id_user, action="edit_message", content=f"Message {message_id} not found", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({'error': 'Message not found'}), 404
        if message['id_sender'] != id_user:
            log = Log(id_user=id_user, action="edit_message", content="Attempted unauthorized edit", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({'error': 'You can only edit your own messages'}), 403
        
        data = request.get_json()
        # Обновляем поля
        updated = False

        if 'text' in data and message['text'] != data['text']:
            sql_update = text(f"UPDATE {table_name} SET text = :text, is_edited = TRUE, is_url = :is_url WHERE id = :message_id")
            db.session.execute(sql_update, {'text': data['text'], 'is_url': data['is_url'], 'message_id': message_id})
            updated = True

        if 'images' in data and message['images'] != data['images']:
            images_to_remove = [img for img in message['images'] if img not in data['images']]
            delete_files_for_message(id_dialog, images_to_remove, 'photos')  # Удаляем старые изображения
            sql_update = text(f"UPDATE {table_name} SET images = :images, is_edited = TRUE WHERE id = :message_id")
            db.session.execute(sql_update, {'images': data['images'], 'message_id': message_id})
            updated = True

        if 'file' in data and message['file'] != data['file']:
            if message['file']:
                delete_files_for_message(id_dialog, message['file'], 'files')  # Удаляем старый файл
            sql_update = text(f"UPDATE {table_name} SET file = :file, is_edited = TRUE WHERE id = :message_id")
            db.session.execute(sql_update, {'file': data['file'], 'message_id': message_id})
            updated = True

        if 'voice' in data and message['voice'] != data['voice']:
            if message['voice']:
                delete_files_for_message(id_dialog, message['voice'], 'audio')  # Удаляем старый голосовой файл
            sql_update = text(f"UPDATE {table_name} SET voice = :voice, is_edited = TRUE WHERE id = :message_id")
            db.session.execute(sql_update, {'voice': data['voice'], 'message_id': message_id})
            updated = True

        if 'code' in data and message['code'] != data['code']:
            sql_update = text(f"UPDATE {table_name} SET code = :code, code_language = :code_language, is_edited = TRUE WHERE id = :message_id")
            db.session.execute(sql_update, {'code': data['code'], 'code_language': data.get('code_language', message['code_language']), 'message_id': message_id})
            updated = True

        if updated:
            log = Log(id_user=id_user, id_dialog=id_dialog, action="edit_message", content=f"Message was edited, old message: text: {message.get('text', '')[:150] if message.get('text') else ''}, "
            f"file: {message.get('file', '')[:50] if message.get('file') else ''}")
            db.session.add(log)
            db.session.commit()

            # Уведомляем через WebSocket
            socketio.emit('message_edited', {
                'id': message_id,
                'id_sender': id_user,
                'text': data.get('text', message['text']),
                'images': data.get('images', message['images']),
                'voice': data.get('voice', message['voice']),
                'file': data.get('file', message['file']),
                'code': data.get('code', message['code']),
                'code_language': data.get('code_language', message['code_language']),
                'is_edited': True,
                'is_forwarded': data.get('is_forwarded', message['is_forwarded']),
                'username_author_original': data.get('username_author_original', message['username_author_original']),
                'reference_to_message_id': data.get('reference_to_message_id', message['reference_to_message_id']),
                'timestamp': int(message['timestamp'].timestamp() * 1000)
            }, room=f'dialog_{id_dialog}')

            return jsonify({'message': 'Message updated successfully'}), 200
        else:
            return jsonify({'error': 'No changes made'}), 400

    except Exception as e:
        db.session.rollback()
        log = Log(id_user=id_user, action="edit_message", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({'error': str(e)}), 500


def delete_files_for_message(id_dialog, file_names, folder):
    if not file_names:
        return

    if isinstance(file_names, list):  # Для изображений (могут быть списком)
        for file_name in file_names:
            delete_file_from_disk(folder, str(id_dialog), file_name)
    else:  # Для одиночных файлов (например, file, voice)
        delete_file_from_disk(folder, str(id_dialog), file_names)
        

@messages_bp.route('/messages/<int:id_dialog>', methods=['DELETE'])
@jwt_required()
def delete_messages(id_dialog):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        message_ids = data.get('message_ids', [])

        if not message_ids:
            log = Log(id_user=user_id, id_dialog=id_dialog, action="delete_message", content="Bad attempt to delete message(message IDs provided)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "No message IDs provided"}), 400

        table_name = f'messages_dialog_{id_dialog}'
        
        # Запрос на получение сообщений для удаления
        select_messages_query = text(f'SELECT id, images, file, voice, text FROM {table_name} WHERE id IN :message_ids')
        messages = db.session.execute(select_messages_query, {'message_ids': tuple(message_ids)}).mappings().all()

        if not messages:
            log = Log(id_user=user_id, id_dialog=id_dialog, action="delete_message", content="Bad attempt to delete message(Some messages not found)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "Some messages not found"}), 404

        # Удаление файлов и сообщений
        for message in messages:
            content = ""
            if message['images']:
                delete_files_for_message(id_dialog, message['images'], 'photos')  # Удаляем изображения
                content += f"Deleted images: {message['images']}"
            elif message['file']:
                delete_files_for_message(id_dialog, message['file'], 'files')   # Удаляем файлы
                content += f"Deleted file: {message['file']}"
            elif message['voice']:
                delete_files_for_message(id_dialog, message['voice'], 'audio')  # Удаляем голосовые сообщения
                content += f"Deleted voice message: {message['voice']}"
            if message['text']:
                content += f" Deleted text message: {message['text']}"

            log_entry = Log(id_user=user_id, id_dialog=id_dialog, action="delete_message", content=content[:255])
            db.session.add(log_entry)
            sql_delete = text(f"DELETE FROM {table_name} WHERE id = :message_id")
            db.session.execute(sql_delete, {'message_id': message['id']})

        decrement_message_count(dialog_id=id_dialog, count=len(messages))

        db.session.commit()

        # Уведомляем участников через WebSocket
        socketio.emit('messages_deleted', {
            'deleted_message_ids': message_ids
        }, room=f'dialog_{id_dialog}')

        return jsonify({"message": "Messages deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        log_entry = Log(id_user=user_id, id_dialog=id_dialog, action="delete_message", content=str(e)[:200], is_successful=False)
        db.session.add(log_entry)
        db.session.commit()
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>', methods=['DELETE'])
@jwt_required()
def delete_dialog(dialog_id):
    try:
        user_id = get_jwt_identity()
        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            log = Log(id_user=user_id, id_dialog=dialog_id, action="delete_dialog", content="Bad attempt to delete dialog(dialog not found)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "Dialog not found"}), 404

        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
            log = Log(id_user=user_id, id_dialog=dialog_id, action="delete_dialog", content="Bad attempt to delete dialog(user is not a participant in dialog)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "You are not a participant in this dialog"}), 403

        # Определяем имя таблицы с сообщениями для данного диалога
        table_name = f'messages_dialog_{dialog_id}'
        
        # Получаем все сообщения для удаления
        select_messages_query = text(f'SELECT * FROM {table_name}')
        messages = db.session.execute(select_messages_query).mappings().all()

        # Удаляем файлы, прикрепленные к сообщениям
        for message in messages:
            if message['images']:
                delete_files_for_message(dialog_id, message['images'], 'photos')
            elif message['file']:
                delete_files_for_message(dialog_id, message['file'], 'audio')
            elif message['voice']:
                delete_files_for_message(dialog_id, message['voice'], 'files')

        # Удаляем сообщения из партицированной таблицы
        delete_messages_query = text(f'DELETE FROM {table_name}')
        db.session.execute(delete_messages_query)

        # Удаляем диалог
        db.session.delete(dialog)
        db.session.commit()

        log = Log(id_user=user_id, id_dialog=dialog_id, action="delete_dialog", content="Dialog successfully deleted")
        db.session.add(log)
        db.session.commit()

        # Уведомляем участников через WebSocket
        socketio.emit('dialog_deleted', {}, room=f'dialog_{dialog_id}')

        return jsonify({"message": "Dialog deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        log = Log(id_user=user_id, id_dialog=dialog_id, action="delete_dialog", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
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
    with app.app_context():
        try:
            table_name = f'messages_dialog_{dialog_id}'
            for message_id in message_ids:
                content = ""
                get_files_query = text(f'''SELECT images, voice, file, text FROM {table_name} WHERE id = :message_id''')
                message = db.session.execute(get_files_query, {'message_id': message_id}).mappings().first()
                if message['images']:
                    delete_files_for_message(dialog_id, message['images'], 'photos')
                    content += f"Deleted images: {message['images']}"
                elif message['file']:
                    delete_files_for_message(dialog_id, message['file'], 'files')
                    content += f"Deleted file: {message['file']}"
                elif message['voice']:
                    delete_files_for_message(dialog_id, message['voice'], 'audio')
                    content += f"Deleted voice: {message['voice']}"
                if message['text']:
                    content += f" Deleted text message: {message['text']}"

                log_entry = Log(id_user=-1, id_dialog=dialog_id, action="delete_message", content=content[:255])
                db.session.add(log_entry) 

            # Удаление сообщений
            delete_messages_query = text(f'''DELETE FROM messages_dialog_{dialog_id} WHERE id IN :message_ids''')
            db.session.execute(delete_messages_query, {'message_ids': tuple(message_ids)})
            db.session.commit()

            logger.info(f"Sending WebSocket message to room dialog_{dialog_id} with deleted message ids: {message_ids}")
            
            decrement_message_count(dialog_id=dialog_id, count=len(message_ids))

            # Уведомление через WebSocket
            socketio.emit('messages_deleted', {
                'deleted_message_ids': message_ids
            }, room=f'dialog_{dialog_id}')

        except Exception as e:
            db.session.rollback()
            log_entry = Log(id_user=-1, id_dialog=dialog_id, action="delete_message", content=str(e)[:200], is_successful=False)
            db.session.add(log_entry)
            db.session.commit()
            print(f"Error deleting messages: {str(e)}")


@messages_bp.route('/messages/<int:id_dialog>/read', methods=['PUT'])
@jwt_required()
def mark_messages_as_read(id_dialog):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        message_ids = data.get('message_ids')

        if not message_ids:
            return jsonify({"error": "No message IDs provided"}), 400

        dialog = Dialog.query.get(id_dialog)
        if not dialog or (dialog.id_user1 != user_id and dialog.id_user2 != user_id):
            return jsonify({"error": "Unauthorized to mark these messages as read"}), 403

        table_name = f'messages_dialog_{id_dialog}'
        max_message_id = max(message_ids)

        select_unread_messages_query = text(f"""
            SELECT id FROM {table_name}
            WHERE id <= :max_message_id AND is_read = FALSE;
        """)
        unread_messages = db.session.execute(select_unread_messages_query, {'max_message_id': max_message_id}).scalars().all()
        
        if not unread_messages:
            return jsonify({"error": "Messages not found"}), 404

        # Обновляем статус "прочитано" для каждого сообщения
        for message_id in unread_messages:
            update_read_status_query = text(f'UPDATE {table_name} SET is_read = True WHERE id = :message_id')
            db.session.execute(update_read_status_query, {'message_id': message_id})

        db.session.commit()

        # Проверяем, установлен ли интервал автоудаления сообщений
        if dialog.auto_delete_interval > 0:
            # Конвертируем интервал автоудаления в секунды
            delete_interval_seconds = dialog.auto_delete_interval

            # Логируем время, через которое будет выполнено удаление
            if delete_interval_seconds >= 60:
                logger.info(f"Удаление сообщений будет запланировано через {delete_interval_seconds // 60} минут.")
            else:
                logger.info(f"Удаление сообщений будет запланировано через {delete_interval_seconds} секунд.")

            # Запускаем задачу для автоудаления сообщений
            delete_messages_task.send_with_options(
                args=[unread_messages, id_dialog],
                delay=delete_interval_seconds * 1000  # Интервал в миллисекундах
            )

        # Уведомляем участников через WebSocket
        socketio.emit('messages_read', {
            'messages_read_ids': unread_messages
        }, room=f'dialog_{id_dialog}')

        return jsonify({"message": "Messages marked as read successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>/messages/search', methods=['GET'])
@jwt_required()
def search_messages_in_dialog(dialog_id):
    user_id = get_jwt_identity()

    dialog = Dialog.query.get(dialog_id)
    if not dialog:
        return jsonify({"error": "Dialog not found"}), 404

    if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
        return jsonify({"error": "You are not a participant of this dialog"}), 403

    # Определяем имя таблицы с сообщениями для данного диалога
    table_name = f'messages_dialog_{dialog_id}'

    # Получаем все сообщения из таблицы, кроме тех, где text == None
    query = text(f"SELECT * FROM {table_name} WHERE text IS NOT NULL")
    messages = db.session.execute(query).mappings().all()

    message_list = [
        {
            "id": message['id'],
            "id_sender": message['id_sender'],
            "text": message['text'],
            "images": message['images'],
            "voice": message['voice'],
            "file": message['file'],
            "code": message['code'],
            "code_language": message['code_language'],
            "is_read": message['is_read'],
            "is_edited": message['is_edited'],
            "is_url": message['is_url'],
            "timestamp": message['timestamp'],
            "reference_to_message_id": message['reference_to_message_id'],
            "is_forwarded": message['is_forwarded'],
            "username_author_original": message['username_author_original']
        } for message in messages
    ]

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
            key_dialog = dialog.key_user1 if dialog.id_user1 == user_id else dialog.key_user2
            is_owner = True if dialog.id_user1 == user_id else False
            other_user = User.query.get(other_user_id)
            query = text(f"SELECT text, timestamp, is_read FROM messages_dialog_{dialog.id} ORDER BY timestamp DESC LIMIT 1")
            last_message = db.session.execute(query).mappings().first()
            query_unread_count = text(f"SELECT COUNT(*) FROM messages_dialog_{dialog.id} WHERE is_read = FALSE AND id_sender != :user_id")
            unread_count = db.session.execute(query_unread_count, {'user_id': user_id}).scalar()

            dialog_data = {
                "type": "dialog",
                "id": dialog.id,
                "key": key_dialog,
                "other_user": {
                    "id": other_user.id,
                    "name": other_user.name,
                    "username": other_user.username,
                    "avatar": other_user.avatar
                },
                "last_message": {
                    "text": last_message['text'] if last_message else None,
                    "timestamp": last_message['timestamp'] if last_message else None,
                    "is_read": last_message['is_read'] if last_message else None
                },
                "count_msg": dialog.count_msg,
                "unread_count": unread_count,
                "is_owner": is_owner,
                "can_delete": dialog.can_delete,
                "auto_delete_interval": dialog.auto_delete_interval
            }
            dialog_list.append(dialog_data)

        # Получение групп
        group_memberships = GroupMember.query.filter_by(user_id=user_id).all()
        group_ids = [membership.group_id for membership in group_memberships]
        key_dict = {membership.group_id: membership.key for membership in group_memberships}
        groups = Group.query.filter(Group.id.in_(group_ids)).all()

        group_list = []
        for group in groups:
            query = text(f"SELECT text, timestamp, is_read FROM messages_group_{group.id} ORDER BY timestamp DESC LIMIT 1")
            last_message = db.session.execute(query).mappings().first()
            is_owner = True if group.created_by == user_id else False
            unread_count = get_unread_group_messages_count(group.id, user_id)

            group_data = {
                "type": "group",
                "id": group.id,
                "key": key_dict.get(group.id),
                "name": group.name,
                "created_by": group.created_by,
                "avatar": group.avatar,
                "last_message": {
                    "text": last_message['text'] if last_message else None,
                    "timestamp": last_message['timestamp'] if last_message else None,
                    "is_read": last_message['is_read'] if last_message else None
                },
                "count_msg": group.count_msg,
                "unread_count": unread_count,
                "is_owner": is_owner,
                "can_delete": group.can_delete,
                "auto_delete_interval": group.auto_delete_interval
            }
            group_list.append(group_data)

        # Объединение и сортировка диалогов и групп по времени последнего сообщения
        conversations = dialog_list + group_list
        sorted_conversations = sorted(conversations, key=lambda x: x['last_message']['timestamp'].astimezone(timezone(timedelta(hours=3))) if x['last_message']['timestamp'] else datetime.max.replace(tzinfo=timezone(timedelta(hours=3))), reverse=True)

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
            log = Log(id_user=user_id, id_dialog=dialog_id, action="update_dialog_auto_delete_interval", content="Failed to change auto delete interval(Dialog not found)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "Dialog not found"}), 404

        # Проверка, что пользователь является участником диалога
        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
            log = Log(id_user=user_id, id_dialog=dialog_id, action="update_dialog_auto_delete_interval", content="Failed to change auto delete interval(User is not a participant in dialog)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "You are not a participant in this dialog"}), 403
        
        log = Log(id_user=user_id, id_dialog=dialog_id, action="update_dialog_auto_delete_interval", content=f"Successfully updated interval to {auto_delete_interval}")
        db.session.add(log)
        dialog.auto_delete_interval = auto_delete_interval
        db.session.commit()
        return jsonify({"message": "Dialog auto_delete_interval updated successfully",
                        "auto_delete_interval": dialog.auto_delete_interval}), 200
    except Exception as e:
        db.session.rollback()
        log = Log(id_user=user_id, id_dialog=dialog_id, action="update_dialog_auto_delete_interval", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({"error": str(e)}), 500


@messages_bp.route('/dialogs/<int:dialog_id>/delete_messages', methods=['DELETE'])
@jwt_required()
def delete_dialog_messages(dialog_id):
    try:
        user_id = get_jwt_identity()
        dialog = Dialog.query.get(dialog_id)
        if not dialog:
            log = Log(id_user=user_id, id_dialog=dialog_id, action="delete_dialog_messages", content="Failed to delete messages(Dialog not found)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "Dialog not found"}), 404

        # Проверка, что пользователь является участником диалога
        if dialog.id_user1 != user_id and dialog.id_user2 != user_id:
            log = Log(id_user=user_id, id_dialog=dialog_id, action="delete_dialog_messages", content="Failed to delete messages(User is not a participant in dialog)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "You are not a participant in this dialog"}), 403

        message_query = text(f"SELECT id, images, file, voice FROM messages_dialog_{dialog_id}")
        messages = db.session.execute(message_query).mappings().all()
        # Удаление файлов для каждого сообщения
        for message in messages:
            if message['images']:
                delete_files_for_message(dialog_id, message['images'], 'photos')
            elif message['file']:
                delete_files_for_message(dialog_id, message['file'], 'files')
            elif message['voice']:
                delete_files_for_message(dialog_id, message['voice'], 'audio')

        delete_messages_query = text(f"DELETE FROM messages_dialog_{dialog_id}")
        db.session.execute(delete_messages_query)
        db.session.commit()

        log = Log(id_user=user_id, id_dialog=dialog_id, action="delete_dialog_messages", content="All messages successfully deleted")
        db.session.add(log)
        db.session.commit()

        do_zero_message_count(dialog_id=dialog_id)

        # Уведомление участников через WebSocket
        socketio.emit('messages_all_deleted', {}, room=f'dialog_{dialog_id}')

        return jsonify({"message": "All messages in the dialog deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        log = Log(id_user=user_id, id_dialog=dialog_id, action="delete_dialog_messages", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
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
            emit('typing', {'user_id': user_id}, room=f'dialog_{dialog_id}', skip_sid=request.sid)
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
            emit('stop_typing', {'user_id': user_id}, room=f'dialog_{dialog_id}', skip_sid=request.sid)
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
            active_dialogs[user_id] = dialog_id
            emit('user_joined', {'dialog_id': dialog_id, 'user_id': user_id}, room=f'dialog_{dialog_id}', skip_sid=request.sid)
            logger.info(f"Joined Dialog ID: {dialog_id}")
    except ExpiredSignatureError:
        logger.info("Token expired catched")
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
            if active_dialogs.get(user_id) == dialog_id:
                active_dialogs.pop(user_id)
            emit('user_left', {'dialog_id': dialog_id, 'user_id': user_id}, room=f'dialog_{dialog_id}', skip_sid=request.sid)
    except Exception as e:
        logger.info(f"Invalid token: {e}")
        disconnect()
