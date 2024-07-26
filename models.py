from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func

db = SQLAlchemy()


def increment_message_count(dialog_id=None, group_id=None):
    if dialog_id:
        dialog = Dialog.query.get(dialog_id)
        if dialog:
            dialog.count_msg += 1
            db.session.commit()

    if group_id:
        group = Group.query.get(group_id)
        if group:
            group.count_msg += 1
            db.session.commit()


def decrement_message_count(dialog_id=None, group_id=None, count=1):
    if dialog_id:
        dialog = Dialog.query.get(dialog_id)
        if dialog and dialog.count_msg > 0:
            dialog.count_msg -= count
            db.session.commit()

    if group_id:
        group = Group.query.get(group_id)
        if group and group.count_msg > 0:
            group.count_msg -= count
            db.session.commit()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    avatar = db.Column(db.String(256))
    last_session = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    dialogs_as_user1 = db.relationship('Dialog', foreign_keys='Dialog.id_user1', backref='user1', lazy=True)
    dialogs_as_user2 = db.relationship('Dialog', foreign_keys='Dialog.id_user2', backref='user2', lazy=True)
    messages_sent = db.relationship('Message', backref='sender', lazy=True)
    group_messages_sent = db.relationship('GroupMessage', backref='sender', lazy=True)
    groups_created = db.relationship('Group', backref='creator', lazy=True)


class Dialog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    id_user1 = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    id_user2 = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    key = db.Column(db.String(256))
    count_msg = db.Column(db.Integer, default=0)
    can_delete = db.Column(db.Boolean, default=False)
    auto_delete_interval = db.Column(db.Integer, default=0)

    messages = db.relationship('Message', backref='dialog', lazy=True)

    __table_args__ = (db.UniqueConstraint('id_user1', 'id_user2', name='unique_dialog_users'),)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    id_dialog = db.Column(db.Integer, db.ForeignKey('dialog.id'), nullable=False)
    id_sender = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text)
    images = db.Column(db.ARRAY(db.String))
    voice = db.Column(db.String)
    file = db.Column(db.String)
    is_read = db.Column(db.Boolean, default=False)
    is_edited = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, server_default=func.now())


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    avatar = db.Column(db.String(256), default="default.png")
    count_msg = db.Column(db.Integer, default=0)
    can_delete = db.Column(db.Boolean, default=False)
    auto_delete_interval = db.Column(db.Integer, default=0)

    members = db.relationship('GroupMember', backref='group', lazy=True)
    messages = db.relationship('GroupMessage', backref='group', lazy=True)


class GroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class GroupMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    id_sender = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text)
    images = db.Column(db.ARRAY(db.String))
    voice = db.Column(db.String)
    file = db.Column(db.String)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, server_default=func.now())