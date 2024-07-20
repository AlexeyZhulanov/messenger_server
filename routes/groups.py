from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Group, GroupMessage, GroupMember, User

groups_bp = Blueprint('groups', __name__)


@groups_bp.route('/groups', methods=['POST'])
@jwt_required()
def create_group():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        new_group = Group(name=data['name'], creator_id=user_id)
        db.session.add(new_group)
        db.session.commit()
        return jsonify({'message': 'Group created successfully'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/messages', methods=['POST'])
@jwt_required()
def send_group_message(group_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        new_message = GroupMessage(group_id=group_id, sender_id=user_id, text=data['text'])
        db.session.add(new_message)
        db.session.commit()
        return jsonify({'message': 'Message sent successfully'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/groups/<int:group_id>/messages', methods=['GET'])
@jwt_required()
def get_group_messages(group_id):
    try:
        messages = GroupMessage.query.filter_by(group_id=group_id).order_by(GroupMessage.timestamp.asc()).all()
        message_list = [{'text': msg.text, 'timestamp': msg.timestamp, 'sender_id': msg.sender_id} for msg in messages]
        return jsonify(message_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@groups_bp.route('/group_messages/<int:group_message_id>', methods=['PUT'])
@jwt_required()
def edit_group_message(group_message_id):
    try:
        group_message = GroupMessage.query.get(group_message_id)
        if not group_message:
            return jsonify({"error": "Group message not found"}), 404

        data = request.get_json()
        new_text = data.get('text')
        if not new_text:
            return jsonify({"error": "No text provided"}), 400

        group_message.text = new_text
        db.session.commit()
        return jsonify({"message": "Group message edited successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/group_messages/<int:group_message_id>', methods=['DELETE'])
@jwt_required()
def delete_group_message(group_message_id):
    try:
        group_message = GroupMessage.query.get(group_message_id)
        if not group_message:
            return jsonify({"error": "Group message not found"}), 404

        db.session.delete(group_message)
        db.session.commit()
        return jsonify({"message": "Group message deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>', methods=['DELETE'])
@jwt_required()
def delete_group(group_id):
    try:
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404

        db.session.delete(group)
        db.session.commit()
        return jsonify({"message": "Group deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@groups_bp.route('/groups/<int:group_id>', methods=['PUT'])
@jwt_required()
def edit_group_name(group_id):
    try:
        group = Group.query.get(group_id)
        if not group:
            return jsonify({"error": "Group not found"}), 404

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

        # Проверка, что текущий пользователь является создателем группы
        group = Group.query.get(group_id)
        if group.creator_id != user_id:
            return jsonify({'message': 'Only the creator can add members'}), 403

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
        if group.creator_id != current_user_id:
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
        group_members = GroupMember.query.filter_by(group_id=group_id).all()
        member_ids = {member.user_id for member in group_members}

        available_users = User.query.filter(User.id.notin_(member_ids)).all()
        user_list = [{'id': user.id, 'name': user.name} for user in available_users]

        return jsonify(user_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
