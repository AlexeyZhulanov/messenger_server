from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Group, GroupMessage

groups_bp = Blueprint('groups', __name__)


@groups_bp.route('/groups', methods=['POST'])
@jwt_required()
def create_group():
    user_id = get_jwt_identity()
    data = request.get_json()
    new_group = Group(name=data['name'], creator_id=user_id)
    db.session.add(new_group)
    db.session.commit()
    return jsonify({'message': 'Group created successfully'}), 201


@groups_bp.route('/groups/<int:group_id>/messages', methods=['POST'])
@jwt_required()
def send_group_message(group_id):
    user_id = get_jwt_identity()
    data = request.get_json()
    new_message = GroupMessage(group_id=group_id, sender_id=user_id, text=data['text'])
    db.session.add(new_message)
    db.session.commit()
    return jsonify({'message': 'Message sent successfully'}), 201


@groups_bp.route('/groups/<int:group_id>/messages', methods=['GET'])
@jwt_required()
def get_group_messages(group_id):
    messages = GroupMessage.query.filter_by(group_id=group_id).order_by(GroupMessage.timestamp.asc()).all()
    message_list = [{'text': msg.text, 'timestamp': msg.timestamp, 'sender_id': msg.sender_id} for msg in messages]
    return jsonify(message_list)
