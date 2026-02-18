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


def do_zero_message_count(dialog_id=None, group_id=None):
    if dialog_id:
        dialog = Dialog.query.get(dialog_id)
        if dialog and dialog.count_msg > 0:
            dialog.count_msg = 0
            db.session.commit()

    if group_id:
        group = Group.query.get(group_id)
        if group and group.count_msg > 0:
            group.count_msg = 0
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
                code TEXT,
                code_language TEXT,
                is_edited BOOLEAN DEFAULT FALSE,
                is_forwarded BOOLEAN DEFAULT FALSE,
                is_read BOOLEAN DEFAULT FALSE,
                is_url BOOLEAN DEFAULT FALSE,
                reference_to_message_id INTEGER,
                username_author_original TEXT,
                waveform INTEGER[],
                timestamp TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX {table_name}_idx_is_read ON {table_name} (is_read);
            CREATE INDEX {table_name}_idx_msg_timestamp ON {table_name} (timestamp DESC);
        ''')
        db.session.execute(create_table_query)
        db.session.commit()

    # Если это группа, создаем таблицу для статусов прочтения
    if is_group:
        status_table_name = f"message_read_status_group_{conv_id}"
        status_table_exists_query = text(f'''
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = :table_name
            );
        ''')
        status_table_exists = db.session.execute(status_table_exists_query, {'table_name': status_table_name}).scalar()

        if not status_table_exists:
            create_status_table_query = text(f'''
                CREATE TABLE {status_table_name} (
                    id SERIAL PRIMARY KEY,
                    message_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    FOREIGN KEY (message_id) REFERENCES {table_name}(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES public.user(id),
                    UNIQUE (message_id, user_id)
                );

                CREATE INDEX {status_table_name}_idx_user_id ON {status_table_name} (user_id);
                CREATE INDEX {status_table_name}_idx_message_id ON {status_table_name} (message_id);
            ''')
            db.session.execute(create_status_table_query)
            db.session.commit()


def get_unread_group_messages_count(group_id, user_id):
    try:
        # Имя таблицы для статусов прочтения
        status_table_name = f"message_read_status_group_{group_id}"
        
        # Запрос для подсчета непрочитанных сообщений
        query = text(f"""
            SELECT COUNT(*) 
            FROM {status_table_name} 
            WHERE user_id = :user_id;
        """)
        unread_count = db.session.execute(query, {'user_id': user_id}).scalar()
        
        return unread_count or 0
    except Exception as e:
        return 0


def add_unread_message_for_all_members(group_id, message_id, sender_id):
    """
    Добавляет запись о непрочитанном сообщении для всех участников группы, кроме отправителя.
    """
    try:
        status_table_name = f"message_read_status_group_{group_id}"
        
        # Получаем всех участников группы, кроме отправителя
        members = GroupMember.query.filter_by(group_id=group_id).filter(GroupMember.user_id != sender_id).all()
        
        if not members:
            return
        
        # Формируем список значений для вставки
        values = [(message_id, member.user_id) for member in members]
        
        # Создаем SQL-запрос для вставки всех записей за один раз
        query = text(f"""
            INSERT INTO {status_table_name} (message_id, user_id)
            VALUES {', '.join(['(:message_id_' + str(i) + ', :user_id_' + str(i) + ')' for i in range(len(values))])};
        """)

        # Подготавливаем параметры для запроса
        params = {}
        for i, (msg_id, user_id) in enumerate(values):
            params[f'message_id_{i}'] = msg_id
            params[f'user_id_{i}'] = user_id
        
        db.session.execute(query, params)
        db.session.commit()
    except Exception as e:
        print(f"Ошибка при добавлении непрочитанных сообщений: {e}")
        db.session.rollback()


def delete_unread_status_for_messages(group_id, message_ids):
    """
    Удаляет записи о непрочитанных сообщениях для указанных ID сообщений.
    """
    try:
        status_table_name = f"message_read_status_group_{group_id}"
        
        # Формируем SQL-запрос для удаления записей
        query = text(f"""
            DELETE FROM {status_table_name}
            WHERE message_id IN :message_ids;
        """)
        
        db.session.execute(query, {'message_ids': tuple(message_ids)})
        db.session.commit()
    except Exception as e:
        print(f"Ошибка при удалении записей о непрочитанных сообщениях: {e}")
        db.session.rollback()


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
    news_key = db.Column(db.Text)


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


class GitlabSubs(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, nullable=False)
    hook_push = db.Column(db.Boolean, default=False)
    hook_merge = db.Column(db.Boolean, default=False)
    hook_tag = db.Column(db.Boolean, default=False)
    hook_issue = db.Column(db.Boolean, default=False)
    hook_note = db.Column(db.Boolean, default=False)
    hook_release = db.Column(db.Boolean, default=False)

    user = db.relationship("User", backref="gitlab_subs")


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
