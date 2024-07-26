from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Group, GroupMessage, GroupMember, User, increment_message_count, decrement_message_count


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

        # Отправка сообщения о создании группы
        user = User.query.get(user_id)
        creation_message = GroupMessage(
            group_id=new_group.id,
            id_sender=user_id,
            text=f"{user.username} has created a group",
        )
        db.session.add(creation_message)
        db.session.commit()
        increment_message_count(group_id=new_group.id)

        return jsonify({'message': 'Group created and user added successfully'}), 201
    except Exception as e:
        db.session.rollback()  # Откат транзакции в случае ошибки
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/group/<int:group_id>/messages', methods=['POST'])
@jwt_required()
def send_group_message(group_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        text = data.get('text')
        images = data.get('images')
        voice = data.get('voice')
        file = data.get('file')

        # Проверка на участие пользователя в группе
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if user_id not in group.members:
            return jsonify({"error": "You are not a member of this group"}), 403

        message = GroupMessage(
            sender_id=user_id,
            group_id=group_id,
            text=text,
            images=images,
            voice=voice,
            file=file
        )
        db.session.add(message)
        db.session.commit()
        increment_message_count(group_id=group.id)

        return jsonify({"message": "Message added successfully"}), 201
    except Exception as e:
        db.session.rollback()  # Откат транзакции в случае ошибки
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/group/messages', methods=['GET'])
@jwt_required()
def get_group_messages():
    try:
        group_id = request.headers.get('group_id')
        user_id = get_jwt_identity()

        # Проверка на участие пользователя в группе
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if user_id not in group.members:
            return jsonify({"error": "You are not a member of this group"}), 403

        # Пагинация
        start = request.args.get('start', type=int)
        end = request.args.get('end', type=int)

        if start is None or end is None:
            return jsonify({'error': 'group_id, start, and end parameters are required'}), 400

        if start < 0 or end <= start:
            return jsonify({'error': 'Invalid start or end values'}), 400

        messages = GroupMessage.query.filter_by(group_id=group_id).order_by(GroupMessage.timestamp.desc()).slice(start, end).all()

        messages_data = [
            {
                "id": msg.id,
                "sender_id": msg.sender_id,
                "group_id": msg.group_id,
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


@groups_bp.route('/group_messages/<int:group_message_id>', methods=['PUT'])
@jwt_required()
def edit_group_message(group_message_id):
    try:
        user_id = get_jwt_identity()
        group_message = GroupMessage.query.get(group_message_id)
        if not group_message:
            return jsonify({"error": "Group message not found"}), 404
        if group_message.id_sender != user_id:
            return jsonify({'message': 'You can only edit your own messages'}), 403

        data = request.get_json()

        # Получение новых значений из запроса
        new_text = data.get('text')
        new_images = data.get('images')
        new_voice = data.get('voice')
        new_file = data.get('file')

        # Проверка наличия хотя бы одного поля для обновления
        if not any([new_text, new_images, new_voice, new_file]):
            return jsonify({"error": "No content provided for update"}), 400

        # Обновление полей сообщения
        if new_text is not None:
            group_message.text = new_text
        if new_images is not None:
            group_message.images = new_images
        if new_voice is not None:
            group_message.voice = new_voice
        if new_file is not None:
            group_message.file = new_file

        group_message.is_edited = True  # Устанавливаем флаг редактирования
        db.session.commit()

        return jsonify({"message": "Group message edited successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/group/messages', methods=['DELETE'])
@jwt_required()
def delete_group_messages():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        message_ids = data.get('message_ids')

        if not message_ids:
            return jsonify({"error": "No message IDs provided"}), 400

        messages = GroupMessage.query.filter(GroupMessage.id.in_(message_ids)).all()
        if not messages:
            return jsonify({"error": "Some messages not found"}), 404

        # Проверка на участие пользователя в группе
        group_id = messages[0].group_id
        group = Group.query.get(group_id)
        if user_id not in group.members:
            return jsonify({"error": "You are not a member of this group"}), 403

        for message in messages:
            db.session.delete(message)

        db.session.commit()
        decrement_message_count(group_id=group_id, count=len(messages))
        return jsonify({"message": "Messages deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()  # Откат транзакции в случае ошибки
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

        db.session.delete(group)
        db.session.commit()
        return jsonify({"message": "Group deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>', methods=['PUT'])
@jwt_required()
def edit_group_name(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if user_id not in group.members:
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
        new_member_id = data['user_id']

        group = Group.query.get(group_id)
        if user_id not in group.members:
            return jsonify({"error": "You are not a member of this group"}), 403

        # Проверка, что пользователя еще нет в группе
        if GroupMember.query.filter_by(group_id=group_id, user_id=new_member_id).first():
            return jsonify({'message': 'User is already a member of the group'}), 400

        new_member = GroupMember(group_id=group_id, user_id=new_member_id)
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
            return jsonify({'message': 'Only the creator can remove members'}), 403

        member = GroupMember.query.filter_by(group_id=group_id, user_id=user_id).first()
        if not member:
            return jsonify({'message': 'User is not a member of the group'}), 404

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
        if user_id not in group.members:
            return jsonify({"error": "You are not a member of this group"}), 403

        group_members = GroupMember.query.filter_by(group_id=group_id).all()
        member_ids = [member.user_id for member in group_members]

        members = User.query.filter(User.id.in_(member_ids)).all()
        member_list = [{'id': member.id, 'name': member.name, 'username': member.username, 'avatar': member.avatar} for member in members]

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

        if user_id not in group.members:
            return jsonify({"error": "You are not a member of this group"}), 403

        data = request.get_json()
        new_avatar = data.get('avatar')
        if not new_avatar:
            return jsonify({"error": "No avatar provided"}), 400

        group.avatar = new_avatar
        db.session.commit()
        return jsonify({"message": "Group avatar updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/group_messages/read', methods=['PUT'])
@jwt_required()
def mark_group_messages_as_read():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        message_ids = data.get('message_ids')

        if not message_ids:
            return jsonify({"error": "No message IDs provided"}), 400

        messages = GroupMessage.query.filter(GroupMessage.id.in_(message_ids)).all()

        if not messages:
            return jsonify({"error": "Messages not found"}), 404

        for message in messages:
            # Проверяем, что текущий пользователь не является отправителем сообщения
            if message.id_sender == user_id:
                return jsonify({"error": "Sender cannot mark their own message as read"}), 400

            # Проверяем, что сообщение относится к группе, в которой состоит текущий пользователь
            group = Group.query.get(message.group_id)
            if not group:
                return jsonify({"error": "Group not found"}), 404

            if user_id not in group.members:
                return jsonify({"error": "Unauthorized to mark this message as read"}), 403

            message.is_read = True

        db.session.commit()
        return jsonify({"message": "Group messages marked as read"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/toggle_can_delete', methods=['PUT'])
@jwt_required()
def toggle_group_can_delete(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if user_id not in group.members:
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
        if user_id not in group.members:
            return jsonify({"error": "You are not a member of this group"}), 403

        group.auto_delete_interval = auto_delete_interval
        db.session.commit()
        return jsonify({"message": "Group auto_delete_interval updated successfully", "auto_delete_interval": group.auto_delete_interval}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/delete_messages', methods=['DELETE'])
@jwt_required()
def delete_group_messages(group_id):
    try:
        user_id = get_jwt_identity()
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404
        if user_id not in group.members:
            return jsonify({"error": "You are not a member of this group"}), 403

        GroupMessage.query.filter_by(group_id=group_id).delete()
        db.session.commit()
        return jsonify({"message": "All messages in the group deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
