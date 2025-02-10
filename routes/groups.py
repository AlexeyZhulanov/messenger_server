from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, decode_token
from flask_socketio import emit, join_room, leave_room, disconnect
from models import db, Group, GroupMember, User, Log, increment_message_count, decrement_message_count, create_message_table
from .uploads import delete_file_from_disk, delete_avatar_file_if_exists
from app import socketio, logger, dramatiq, app
from jwt.exceptions import ExpiredSignatureError
from sqlalchemy import text
from datetime import timezone, timedelta


groups_bp = Blueprint('groups', __name__)


@groups_bp.route('/groups', methods=['POST'])
@jwt_required()
def create_group():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()

        # Создание новой группы
        new_group = Group(name=data['name'], created_by=user_id)
        db.session.add(new_group)
        db.session.flush()  # Используем flush для получения ID новой группы

        # Добавление создателя группы как её члена
        new_member = GroupMember(group_id=new_group.id, user_id=user_id)
        db.session.add(new_member)

        create_message_table(new_group.id, is_group=True)

        # Отправка сообщения о создании группы
        user = User.query.get(user_id)
        insert_message_query = f'INSERT INTO messages_group_{new_group.id} (id_sender, text) VALUES (:id_sender, :text)'
        db.session.execute(text(insert_message_query), {'id_sender': user_id, 'text': f'{user.username} has created a group'})
        db.session.commit()
        increment_message_count(group_id=new_group.id)
        log = Log(id_user=user_id, action="create_group", content=f"Group created")
        db.session.add(log)
        db.session.commit()

        return jsonify({'message': 'Group created and user added successfully'}), 201
    except Exception as e:
        db.session.rollback()  # Откат транзакции в случае ошибки
        log = Log(id_user=user_id, action="create_group", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/group/<int:group_id>/messages', methods=['POST'])
@jwt_required()
def send_group_message(group_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        text_content = data.get('text')
        images = data.get('images')
        voice = data.get('voice')
        file = data.get('file')
        reference_to_message_id = data.get('reference_to_message_id')
        is_forwarded = data.get('is_forwarded')
        username_author_original = data.get('username_author_original')

        # Проверка на участие пользователя в группе
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403

        if file:  
            log = Log(id_user=user_id, id_group=group_id, action="send_message", content=f"User sent a file: {file}")
            db.session.add(log)
            db.session.commit()

        # Вставка сообщения в партицированную таблицу
        table_name = f'messages_group_{group_id}'
        insert_message_query = text(f'''INSERT INTO {table_name} 
        (id_sender, text, images, voice, file, is_edited, is_forwarded, reference_to_message_id, username_author_original, is_read)
        VALUES (:id_sender, :text, :images, :voice, :file, :is_edited, :is_forwarded, :reference_to_message_id, :username_author_original, :is_read)
        RETURNING id, timestamp;''')

        result = db.session.execute(insert_message_query, {
            'id_sender': user_id,
            'text': text_content,
            'images': images,
            'voice': voice,
            'file': file,
            'is_edited': False,
            'is_forwarded': is_forwarded,
            'is_read': False,
            'reference_to_message_id': reference_to_message_id,
            'username_author_original': username_author_original
        })
        db.session.commit()

        increment_message_count(group_id=group.id)

        message_id, timestamp = result.fetchone()

        # Отправляем уведомление через WebSocket
        socketio.emit('new_message', {
            'id': message_id,
            'id_sender': user_id,
            'text': text_content,
            'images': images,
            'voice': voice,
            'file': file,
            'is_edited': False,
            'is_read': False,
            'is_forwarded': is_forwarded,
            'username_author_original': username_author_original,
            'reference_to_message_id': reference_to_message_id,
            'timestamp': int(timestamp.timestamp() * 1000)
        }, room=f'group_{group_id}')

        return jsonify({"message": "Message sent successfully"}), 201
    except Exception as e:
        db.session.rollback()  # Откат транзакции в случае ошибки
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/group/messages/<int:group_id>', methods=['GET'])
@jwt_required()
def get_group_messages(group_id):
    try:
        user_id = get_jwt_identity()

        # Проверка на участие пользователя в группе
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403

        # Пагинация
        page = request.args.get('page', type=int)
        size = request.args.get('size', type=int)

        if page is None or size is None:
            return jsonify({'error': 'group_id, Page, and size parameters are required'}), 400

        # Вычисляем границы выборки
        offset = page * size

        # Имя таблицы сообщений для группы
        table_name = f'messages_group_{group_id}'

        # Получение сообщений с пагинацией
        get_messages_query = text(f'SELECT * FROM {table_name} ORDER BY timestamp ASC LIMIT :limit OFFSET :offset;')
        messages = db.session.execute(get_messages_query, {'limit': size, 'offset': offset}).mappings().all()

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
                "is_edited": msg['is_edited'],
                "is_read": msg['is_read'],
                "is_forwarded": msg['is_forwarded'],
                "reference_to_message_id": msg['reference_to_message_id'],
                "username_author_original": msg['username_author_original'],
                "timestamp": msg['timestamp']
            }
            for msg in messages
        ]

        return jsonify(messages_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/group/message/<int:message_id>', methods=['GET'])
@jwt_required()
def get_message_by_id(message_id):
    try:
        user_id = get_jwt_identity()
        group_id = request.args.get('group_id')
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404

        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403

        # Имя таблицы сообщений для данной группы
        table_name = f'messages_group_{group_id}'

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
            "is_edited": message['is_edited'],
            "is_read": message['is_read'],
            "is_forwarded": message['is_forwarded'],
            "reference_to_message_id": message['reference_to_message_id'],
            "username_author_original": message['username_author_original'],
            "timestamp": message['timestamp'],
            "position": message_position
        }

        return jsonify(message_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/group/<int:group_id>/key', methods=['PUT'])
@jwt_required()
def add_key_to_group(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404

        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403
        
        data = request.get_json()
        key = data.get('key')
        if not key:
            return jsonify({"error": "No key provided"}), 400

        group.key = key
        db.session.commit()
        return jsonify({"message": "Key added to group"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/group/<int:group_id>/key', methods=['DELETE'])
@jwt_required()
def remove_key_from_group(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404

        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403

        group.key = None
        db.session.commit()
        return jsonify({"message": "Key removed from group"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/group_messages/<int:message_id>', methods=['PUT'])
@jwt_required()
def edit_group_message(message_id):
    try:
        id_user = get_jwt_identity()
        group_id = request.args.get('group_id')
        data = request.get_json()

        table_name = f'messages_group_{group_id}'
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
        
        # Обновляем поля
        updated = False

        if 'text' in data and message['text'] != data['text']:
            sql_update = text(f"UPDATE {table_name} SET text = :text, is_edited = TRUE WHERE id = :message_id")
            db.session.execute(sql_update, {'text': data['text'], 'message_id': message_id})
            updated = True

        if 'images' in data and message['images'] != data['images']:
            images_to_remove = [img for img in message['images'] if img not in data['images']]
            delete_files_for_message(group_id, images_to_remove, 'photos')  # Удаляем старые изображения
            sql_update = text(f"UPDATE {table_name} SET images = :images, is_edited = TRUE WHERE id = :message_id")
            db.session.execute(sql_update, {'images': data['images'], 'message_id': message_id})
            updated = True

        if 'file' in data and message['file'] != data['file']:
            if message['file']:
                delete_files_for_message(group_id, message['file'], 'files')  # Удаляем старый файл
            sql_update = text(f"UPDATE {table_name} SET file = :file, is_edited = TRUE WHERE id = :message_id")
            db.session.execute(sql_update, {'file': data['file'], 'message_id': message_id})
            updated = True

        if 'voice' in data and message['voice'] != data['voice']:
            if message['voice']:
                delete_files_for_message(group_id, message['voice'], 'audio')  # Удаляем старый голосовой файл
            sql_update = text(f"UPDATE {table_name} SET voice = :voice, is_edited = TRUE WHERE id = :message_id")
            db.session.execute(sql_update, {'voice': data['voice'], 'message_id': message_id})
            updated = True

        if updated:
            log = Log(id_user=id_user, id_group=group_id, action="edit_message", content=f"Message was edited, old message: text: {message.get('text', '')[:150] if message.get('text') else ''}, "
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
                'is_edited': True,
                'is_forwarded': data.get('is_forwarded', message['is_forwarded']),
                'username_author_original': data.get('username_author_original', message['username_author_original']),
                'reference_to_message_id': data.get('reference_to_message_id', message['reference_to_message_id']),
                'timestamp': int(message['timestamp'].timestamp() * 1000)
            }, room=f'group_{group_id}')

        return jsonify({"message": "Group message edited successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def delete_files_for_message(id_dialog, file_names, folder):
    if not file_names:
        return

    if isinstance(file_names, list):  # Для изображений (могут быть списком)
        for file_name in file_names:
            delete_file_from_disk(folder, str(id_dialog), file_name, is_group=True)
    else:  # Для одиночных файлов (например, file, voice)
        delete_file_from_disk(folder, str(id_dialog), file_names, is_group=True)


@groups_bp.route('/group/messages/<int:group_id>', methods=['DELETE'])
@jwt_required()
def delete_group_messages(group_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        message_ids = data.get('message_ids', [])

        if not message_ids:
            log = Log(id_user=user_id, id_group=group_id, action="delete_message", content="Bad attempt to delete message(message IDs provided)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "No message IDs provided"}), 400

        table_name = f'messages_group_{group_id}'
        
        # Запрос на получение сообщений для удаления
        select_messages_query = text(f'SELECT id, images, file, voice, text FROM {table_name} WHERE id IN :message_ids')
        messages = db.session.execute(select_messages_query, {'message_ids': tuple(message_ids)}).mappings().all()

        if not messages:
            log = Log(id_user=user_id, id_group=group_id, action="delete_message", content="Bad attempt to delete message(Some messages not found)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "Some messages not found"}), 404

        # Удаление файлов и сообщений
        for message in messages:
            content = ""
            if message['images']:
                delete_files_for_message(group_id, message['images'], 'photos')  # Удаляем изображения
                content += f"Deleted images: {message['images']}"
            elif message['file']:
                delete_files_for_message(group_id, message['file'], 'files')   # Удаляем файлы
                content += f"Deleted file: {message['file']}"
            elif message['voice']:
                delete_files_for_message(group_id, message['voice'], 'audio')  # Удаляем голосовые сообщения
                content += f"Deleted voice message: {message['voice']}"
            if message['text']:
                content += f" Deleted text message: {message['text']}"

            log_entry = Log(id_user=user_id, id_group=group_id, action="delete_message", content=content[:255])
            db.session.add(log_entry)
            sql_delete = text(f"DELETE FROM {table_name} WHERE id = :message_id")
            db.session.execute(sql_delete, {'message_id': message['id']})

        decrement_message_count(group_id=group_id, count=len(messages))

        db.session.commit()

        # Уведомляем участников через WebSocket
        socketio.emit('messages_deleted', {
            'deleted_message_ids': message_ids
        }, room=f'group_{group_id}')

        return jsonify({"message": "Messages deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()  # Откат транзакции в случае ошибки
        log_entry = Log(id_user=user_id, id_group=group_id, action="delete_message", content=str(e)[:200], is_successful=False)
        db.session.add(log_entry)
        db.session.commit()
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>', methods=['DELETE'])
@jwt_required()
def delete_group(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)

        if not group:
            return jsonify({"error": "Group not found"}), 404

        if group.created_by != user_id:
            return jsonify({"error": "Only the creator of the group can delete it"}), 403

        # Определяем имя таблицы с сообщениями для данной группы
        table_name = f'messages_group_{group_id}'
        
        # Получаем все сообщения для удаления
        select_messages_query = text(f'SELECT * FROM {table_name}')
        messages = db.session.execute(select_messages_query).mappings().all()

        # Удаляем файлы, прикрепленные к сообщениям
        for message in messages:
            if message['images']:
                delete_files_for_message(group_id, message['images'], 'photos')
            elif message['file']:
                delete_files_for_message(group_id, message['file'], 'audio')
            elif message['voice']:
                delete_files_for_message(group_id, message['voice'], 'files')

        # Удаляем сообщения из партицированной таблицы
        delete_messages_query = text(f'DELETE FROM {table_name}')
        db.session.execute(delete_messages_query)

        # Удаляем группу
        db.session.delete(group)
        db.session.commit()

        log = Log(id_user=user_id, id_group=group_id, action="delete_group", content="Group successfully deleted")
        db.session.add(log)
        db.session.commit()

        # Уведомляем участников через WebSocket
        socketio.emit('dialog_deleted', {}, room=f'group_{group_id}')

        return jsonify({"message": "Group deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        log = Log(id_user=user_id, id_group=group_id, action="delete_group", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>', methods=['PUT'])
@jwt_required()
def edit_group_name(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403
        data = request.get_json()
        new_name = data.get('name')
        if not new_name:
            return jsonify({"error": "No name provided"}), 400

        group.name = new_name
        db.session.commit()
        return jsonify({"message": "Group name updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/members', methods=['POST'])
@jwt_required()
def add_user_to_group(group_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        new_member_name = data['name']
        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403

        user = User.query.filter_by(name=new_member_name).first()
        # Проверка, что пользователя еще нет в группе
        if GroupMember.query.filter_by(group_id=group_id, user_id=user.id).first():
            return jsonify({'error': 'User is already a member of the group'}), 400

        new_member = GroupMember(group_id=group_id, user_id=user.id)
        db.session.add(new_member)
        db.session.commit()
        return jsonify({'message': 'User added to group successfully'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/members/<int:user_id>', methods=['DELETE'])
@jwt_required()
def remove_user_from_group(group_id, user_id):
    try:
        current_user_id = get_jwt_identity()

        # Проверка, что текущий пользователь является создателем группы
        group = Group.query.get(group_id)
        if group.created_by != current_user_id:
            return jsonify({'error': 'Only the creator can remove members'}), 403

        member = GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first()
        if not member:
            return jsonify({'error': 'User is not a member of the group'}), 404

        db.session.delete(member)
        db.session.commit()
        return jsonify({'message': 'User removed from group successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/available_users', methods=['GET'])
@jwt_required()
def get_available_users_for_group(group_id):
    try:
        user_id = get_jwt_identity()

        group_members = GroupMember.query.filter_by(group_id=group_id).all()
        member_ids = {member.user_id for member in group_members}

        available_users = User.query.filter(User.id.notin_(member_ids), User.id != user_id).all()
        user_list = [{'id': user.id, 'name': user.name} for user in available_users]

        return jsonify(user_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/members', methods=['GET'])
@jwt_required()
def get_group_members(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403

        group_members = GroupMember.query.filter_by(group_id=group_id).all()
        member_ids = [member.user_id for member in group_members]
        members = User.query.filter(User.id.in_(member_ids)).all()
        member_list = [{'id': member.id, 'name': member.name, 'username': member.username, 'avatar': member.avatar, 'last_session': int(member.last_session.timestamp() * 1000)} for member in members]

        return jsonify(member_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/avatar', methods=['PUT'])
@jwt_required()
def update_group_avatar(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404

        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403

        data = request.get_json()
        avatar = data.get('avatar')
        if not avatar:
            return jsonify({"error": "No avatar provided"}), 400
        if avatar == "delete":
            if group.avatar:
                delete_avatar_file_if_exists(group.avatar)
            group.avatar = None
        elif avatar:
            if group.avatar:
                delete_avatar_file_if_exists(group.avatar)
            group.avatar = avatar
            logger.info(f"User #{user_id} updated avatar in group: {group.name}")
        db.session.commit()
        return jsonify({"message": "Group avatar updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dramatiq.actor
def delete_messages_task(message_ids, group_id):
    with app.app_context():
        try:
            table_name = f'messages_group_{group_id}'
            for message_id in message_ids:
                content = ""
                get_files_query = text(f'''SELECT images, voice, file, text FROM {table_name} WHERE id = :message_id''')
                message = db.session.execute(get_files_query, {'message_id': message_id}).mappings().first()
                if message['images']:
                    delete_files_for_message(group_id, message['images'], 'photos')
                    content += f"Deleted images: {message['images']}"
                elif message['file']:
                    delete_files_for_message(group_id, message['file'], 'files')
                    content += f"Deleted file: {message['file']}"
                elif message['voice']:
                    delete_files_for_message(group_id, message['voice'], 'audio')
                    content += f"Deleted voice: {message['voice']}"
                if message['text']:
                    content += f" Deleted text message: {message['text']}"

                log_entry = Log(id_user=-1, id_group=group_id, action="delete_message", content=content[:255])
                db.session.add(log_entry) 

            # Удаление сообщений
            delete_messages_query = text(f'''DELETE FROM messages_group_{group_id} WHERE id IN :message_ids''')
            db.session.execute(delete_messages_query, {'message_ids': tuple(message_ids)})
            db.session.commit()

            logger.info(f"Sending WebSocket message to room group_{group_id} with deleted message ids: {message_ids}")
            # Уведомление через WebSocket
            socketio.emit('messages_deleted', {
                'deleted_message_ids': message_ids
            }, room=f'group_{group_id}')

        except Exception as e:
            db.session.rollback()
            log_entry = Log(id_user=-1, id_group=group_id, action="delete_message", content=str(e)[:200], is_successful=False)
            db.session.add(log_entry)
            db.session.commit()
            print(f"Error deleting messages: {str(e)}")


@groups_bp.route('/group_messages/<int:group_id>/read', methods=['PUT'])
@jwt_required()
def mark_group_messages_as_read(group_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        message_ids = data.get('message_ids')

        if not message_ids:
            return jsonify({"error": "No message IDs provided"}), 400

        group = Group.query.get(group_id)
        
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403
        
        ids_final = []
        table_name = f'messages_group_{group_id}'
        for message_id in message_ids:
            # Получаем сообщение из партицированной таблицы
            select_message_query = text(f'SELECT id, id_sender FROM {table_name} WHERE id = :message_id')
            message = db.session.execute(select_message_query, {'message_id': message_id}).mappings().first()
            if message and message['id_sender'] != user_id:
                ids_final.append(message_id)

        if not ids_final:
            return jsonify({"error": "Messages not found"}), 404

        # Обновляем статус "прочитано" для каждого сообщения
        for message_id in ids_final:
            update_read_status_query = text(f'UPDATE {table_name} SET is_read = True WHERE id = :message_id')
            db.session.execute(update_read_status_query, {'message_id': message_id})

        db.session.commit()

        # Проверяем, установлен ли интервал автоудаления сообщений
        if group.auto_delete_interval > 0:
            # Конвертируем интервал автоудаления в секунды
            delete_interval_seconds = group.auto_delete_interval

            # Логируем время, через которое будет выполнено удаление
            if delete_interval_seconds >= 60:
                logger.info(f"Удаление сообщений будет запланировано через {delete_interval_seconds // 60} минут.")
            else:
                logger.info(f"Удаление сообщений будет запланировано через {delete_interval_seconds} секунд.")

            # Запускаем задачу для автоудаления сообщений
            delete_messages_task.send_with_options(
                args=[ids_final, group.id],
                delay=delete_interval_seconds * 1000  # Интервал в миллисекундах
            )

        # Уведомляем участников через WebSocket
        socketio.emit('messages_read', {
            'messages_read_ids': ids_final
        }, room=f'group_{group_id}')

        return jsonify({"message": "Group messages marked as read"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/toggle_can_delete', methods=['PUT'])
@jwt_required()
def toggle_group_can_delete(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403
        group.can_delete = not group.can_delete
        db.session.commit()
        return jsonify({"message": "Group can_delete flag updated successfully", "can_delete": group.can_delete}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/update_auto_delete_interval', methods=['PUT'])
@jwt_required()
def update_group_auto_delete_interval(group_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        auto_delete_interval = data.get('auto_delete_interval')

        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403

        log = Log(id_user=user_id, id_group=group_id, action="update_group_auto_delete_interval", content=f"Successfully updated interval to {auto_delete_interval}")
        db.session.add(log)
        group.auto_delete_interval = auto_delete_interval
        db.session.commit()
        return jsonify({"message": "Group auto_delete_interval updated successfully", "auto_delete_interval": group.auto_delete_interval}), 200
    except Exception as e:
        db.session.rollback()
        log = Log(id_user=user_id, id_group=group_id, action="update_group_auto_delete_interval", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/delete_messages', methods=['DELETE'])
@jwt_required()
def delete_group_messages_all(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403

        message_query = text(f"SELECT id, images, file, voice FROM messages_group_{group_id}")
        messages = db.session.execute(message_query).mappings().all()
        # Удаление файлов для каждого сообщения
        for message in messages:
            if message['images']:
                delete_files_for_message(group_id, message['images'], 'photos')
            elif message['file']:
                delete_files_for_message(group_id, message['file'], 'files')
            elif message['voice']:
                delete_files_for_message(group_id, message['voice'], 'audio')

        delete_messages_query = text(f"DELETE FROM messages_group_{group_id}")
        db.session.execute(delete_messages_query)
        db.session.commit()

        log = Log(id_user=user_id, id_group=group_id, action="delete_group_messages", content="All messages successfully deleted")
        db.session.add(log)
        db.session.commit()

        # Уведомление участников через WebSocket
        socketio.emit('messages_all_deleted', {}, room=f'group_{group_id}')

        return jsonify({"message": "All messages in the group deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        log = Log(id_user=user_id, id_group=group_id, action="delete_group_messages", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/group/<int:group_id>/settings', methods=['GET'])
@jwt_required()
def get_group_settings(group_id):
    user_id = get_jwt_identity()
    try:
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
            return jsonify({"error": "You are not a member of this group"}), 403

        return jsonify({
            "can_delete": group.can_delete,
            "auto_delete_interval": group.auto_delete_interval
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/messages/search', methods=['GET'])
@jwt_required()
def search_messages_in_group(group_id):
    user_id = get_jwt_identity()
    search_text = request.args.get('q', '')

    if not search_text:
        return jsonify({"error": "Search text must be provided"}), 400

    group = Group.query.get(group_id)
    if not group:
        return jsonify({"error": "Group not found"}), 404

    if not GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first():
        return jsonify({"error": "You are not a member of this group"}), 403

    table_name = f'messages_group_{group_id}'

    # Полнотекстовый поиск по партицированной таблице сообщений
    search_text = ' & '.join([f'{word}:*' for word in search_text.split()])
    search_query = text(f"SELECT * FROM {table_name} WHERE to_tsvector('simple', text) @@ to_tsquery('simple', :search_text)")
    messages = db.session.execute(search_query, {'search_text': search_text}).mappings().all()

    message_list = [
        {
            "id": message['id'],
            "id_sender": message['id_sender'],
            "text": message['text'],
            "images": message['images'],
            "voice": message['voice'],
            "file": message['file'],
            "is_read": message['is_read'],
            "is_edited": message['is_edited'],
            "timestamp": message['timestamp'],
            "reference_to_message_id": message['reference_to_message_id'],
            "is_forwarded": message['is_forwarded'],
            "username_author_original": message['username_author_original']
        } for message in messages
    ]

    return jsonify(message_list), 200


@socketio.on('typing_group')
def handle_typing_event(data):
    """
    Обрабатывает событие начала набора текста.
    :param data: данные о группе и пользователе, который набирает текст.
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

        group_id = data.get('group_id')

        if group_id:
            emit('typing', {'user_id': user_id}, room=f'group_{group_id}', skip_sid=request.sid)
    except Exception as e:
        logger.info(f"Invalid token: {e}")
        disconnect()


@socketio.on('stop_typing_group')
def handle_stop_typing_event(data):
    """
    Обрабатывает событие завершения набора текста.
    :param data: данные о группе и пользователе, который прекратил набор текста.
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

        group_id = data.get('group_id')

        if group_id:
            emit('stop_typing', {'user_id': user_id}, room=f'group_{group_id}', skip_sid=request.sid)
    except Exception as e:
        logger.info(f"Invalid token: {e}")
        disconnect()


@socketio.on('join_group')
def handle_join_dialog(data):
    """
    Обрабатывает событие присоединения к группе.
    :param data: данные о группе.
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

        group_id = data.get('group_id')

        if group_id:
            # Присоединяем пользователя к комнате, соответствующей диалогу
            join_room(f'group_{group_id}')
            emit('user_joined', {'dialog_id': group_id, 'user_id': user_id}, room=f'group_{group_id}', skip_sid=request.sid)
            logger.info(f"Joined Group ID: {group_id}")
    except ExpiredSignatureError:
        logger.info("Token expired catched")
        emit('token_expired', {'message': 'Token has expired'})
        disconnect()  # Разрываем соединение
    except Exception as e:
        logger.info(f"Invalid token: {e}")
        disconnect()  # Разрываем соединение в случае невалидного токена


@socketio.on('leave_group')
def handle_leave_dialog(data):
    """
    Обрабатывает событие выхода из группы.
    :param data: данные о группе.
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

        group_id = data.get('group_id')
        logger.info(f"Left Group ID: {group_id}")

        if group_id:
            leave_room(f'group_{group_id}')
            emit('user_left', {'dialog_id': group_id, 'user_id': user_id}, room=f'group_{group_id}', skip_sid=request.sid)
    except Exception as e:
        logger.info(f"Invalid token: {e}")
        disconnect()
