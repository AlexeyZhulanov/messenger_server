from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Group, GroupMessage

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
