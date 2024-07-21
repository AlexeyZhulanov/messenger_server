from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    avatar = db.Column(db.String(256))

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