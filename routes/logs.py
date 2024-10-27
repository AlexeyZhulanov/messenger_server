from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Log
from sqlalchemy import text
import re

logs_bp = Blueprint('logs', __name__)


@logs_bp.route('/logs/query', methods=['POST'])
@jwt_required()
def execute_log_query():
    try:
        user_id = get_jwt_identity()

        # Проверяем, что пользователь является администратором
        #if not user_is_admin(user_id):
            #return jsonify({"error": "Access denied"}), 403

        # Получаем SQL-запрос из тела запроса
        data = request.get_json()
        sql_query = data.get('query')

        if not sql_query:
            log = Log(id_user=user_id, action="get_logs", content="Failed to get logs(No SQL query provided)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "No SQL query provided"}), 400

        # Проверка на наличие разрешенных таблиц
        allowed_tables = ['Log']  # Добавьте сюда разрешенные таблицы
        if not any(table in sql_query for table in allowed_tables):
            log = Log(id_user=user_id, action="get_logs", content="Failed to get logs(Unauthorized table access)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "Unauthorized table access"}), 403

        # Простой паттерн для разрешенных запросов
        pattern = r'^(SELECT|SELECT DISTINCT) .* FROM \w+(\s+WHERE .*)?(\s+ORDER BY \w+ (ASC|DESC))?;?$'
        if not re.match(pattern, sql_query.strip(), re.IGNORECASE):
            log = Log(id_user=user_id, action="get_logs", content="Failed to get logs(Invalid SQL query format)", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({"error": "Invalid SQL query format"}), 400

        # Выполняем запрос
        result = db.session.execute(text(sql_query))
        rows = result.mappings().all()

        # Преобразуем результат в список словарей
        logs_list = [dict(row) for row in rows]

        # Логируем выполненный запрос
        log = Log(id_user=user_id, action="get_logs", content=f"Query successfully completed: {sql_query}"[:255])
        db.session.add(log)
        db.session.commit()

        return jsonify(logs_list), 200

    except Exception as e:
        log = Log(id_user=user_id, action="get_logs", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({"error": str(e)}), 500