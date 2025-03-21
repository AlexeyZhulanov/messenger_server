from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from sqlalchemy import text
from datetime import datetime

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


def create_message_table(conv_id, is_group=False):
    table_name = f"messages_group_{conv_id}" if is_group else f"messages_dialog_{conv_id}"
    
    # Проверка, существует ли таблица
    table_exists_query = text(f'''
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = :table_name
        );
    ''')
    table_exists = db.session.execute(table_exists_query, {'table_name': table_name}).scalar()

    # Если таблица не существует, создаем её
    if not table_exists:
        create_table_query = text(f'''
            CREATE TABLE {table_name} (
                id SERIAL PRIMARY KEY,
                id_sender INTEGER NOT NULL,
                text TEXT,
                images TEXT[],
                voice TEXT,
                file TEXT,
                is_edited BOOLEAN DEFAULT FALSE,
                is_forwarded BOOLEAN DEFAULT FALSE,
                is_read BOOLEAN DEFAULT FALSE,
                reference_to_message_id INTEGER,
                username_author_original TEXT,
                timestamp TIMESTAMPTZ DEFAULT NOW()
            );
        ''')
        db.session.execute(create_table_query)
        db.session.commit()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    avatar = db.Column(db.String(256))
    last_session = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())
    vacation_start = db.Column(db.Date, nullable=True)
    vacation_end = db.Column(db.Date, nullable=True)
    permission = db.Column(db.Integer, nullable=False, server_default="0") # User - 0, Moderator - 1
    fcm_token = db.Column(db.String(255), nullable=True)
    public_key = db.Column(db.Text)
    encrypted_private_key = db.Column(db.Text)

    dialogs_as_user1 = db.relationship('Dialog', foreign_keys='Dialog.id_user1', backref='user1', lazy=True)
    dialogs_as_user2 = db.relationship('Dialog', foreign_keys='Dialog.id_user2', backref='user2', lazy=True)
    groups_created = db.relationship('Group', backref='creator', lazy=True)


class Dialog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    id_user1 = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    id_user2 = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    key_user1 = db.Column(db.Text, nullable=False)
    key_user2 = db.Column(db.Text, nullable=False)
    count_msg = db.Column(db.Integer, default=0)
    can_delete = db.Column(db.Boolean, default=False)
    auto_delete_interval = db.Column(db.Integer, default=0)

    __table_args__ = (db.UniqueConstraint('id_user1', 'id_user2', name='unique_dialog_users'),)


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    avatar = db.Column(db.String(256))
    count_msg = db.Column(db.Integer, default=0)
    can_delete = db.Column(db.Boolean, default=False)
    auto_delete_interval = db.Column(db.Integer, default=0)


class GroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    key = db.Column(db.Text, nullable=False)


class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    written_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    header_text = db.Column(db.Text)
    text = db.Column(db.Text)
    images = db.Column(db.ARRAY(db.String))
    voices = db.Column(db.ARRAY(db.String))
    files = db.Column(db.ARRAY(db.String))
    is_edited = db.Column(db.Boolean, default=False)
    views_count = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, server_default=func.now())


class NewsKeys(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    key = db.Column(db.Text)


class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    id_user = db.Column(db.Integer, nullable=False)
    id_dialog = db.Column(db.Integer, nullable=True)
    id_group = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.String, default=lambda: datetime.now().strftime("%H:%M, %d %b %Y"), nullable=False)
    action = db.Column(db.String(255), nullable=False)
    content = db.Column(db.String(255), nullable=True)
    is_successful = db.Column(db.Boolean, default=True, nullable=False)
    
    def __init__(self, id_user, action, id_dialog=None, id_group=None, content=None, is_successful=True):
        self.id_user = id_user
        self.id_dialog = id_dialog
        self.id_group = id_group
        self.action = action
        self.content = content
        self.is_successful = is_successful
