from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, Log, News
from .uploads import delete_news_file_if_exists
from app import socketio
from fcm import send_push_wakeup

news_bp = Blueprint('news', __name__)

@news_bp.route('/news', methods=['POST'])
@jwt_required()
def send_news():
    try:
        data = request.get_json()
        id_sender = get_jwt_identity()
        user = User.query.get(id_sender)
        if user.permission != 1:
            log = Log(id_user=id_sender, action="send_news", content="Failed: User tried to send the news without permission", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({'error': 'You are not a moderator of the news section'}), 403
        
        header_text = data.get('header_text')
        text_content = data.get('text')
        images = data.get('images')
        voices = data.get('voices')
        files = data.get('files')
        if files:  
            log = Log(id_user=id_sender, action="send_news", content=f"Moderator sent a file: {files}")
            db.session.add(log)
            db.session.commit()

        news = News(
            written_by=id_sender,
            header_text = header_text,
            text=text_content,
            images=images,
            voices=voices,
            files=files,
            is_edited=False
        )
        db.session.add(news)
        log = Log(id_user=id_sender, action="send_news", content="News was sent successfully")
        db.session.add(log)
        db.session.commit()

        # Для push-уведомлений
        socketio.emit('news_notification', {
            'header_text': header_text,
            'text': text_content,
            'images': images,
            'voices': voices,
            'files': files
        }, room=None)

        # FCM
        offline_users = User.query.filter(User.fcm_token.isnot(None)).all()
        offline_tokens = [user.fcm_token for user in offline_users if f"user_{user.id}" not in socketio.server.manager.rooms["/"]]
        for offline_token in offline_tokens:
            if offline_token:
                send_push_wakeup(offline_token)

        return jsonify({"message": "News post sent successfully"}), 201
    
    except Exception as e:
        db.session.rollback()
        log = Log(id_user=id_sender, action="send_news", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({'error': str(e)}), 500
    

@news_bp.route('/news', methods=['GET'])
@jwt_required()
def get_news():
    try:
        # Пагинация
        page = request.args.get('page', default=1, type=int)
        size = request.args.get('size', default=10, type=int)
        if page < 1 or size < 1:
            return jsonify({'error': 'Page and size must be positive integers'}), 400
            
        # Запрос с пагинацией, сортируем по дате (от новых к старым)
        news_paginated = News.query.order_by(News.timestamp.desc()).paginate(page=page, per_page=size, error_out=False)

        # Список ID новостей, которые отправляются клиенту
        news_ids = [news.id for news in news_paginated.items]

        if news_ids:
            # Увеличиваем views_count для выбранных новостей
            News.query.filter(News.id.in_(news_ids)).update({News.views_count: News.views_count + 1}, synchronize_session=False)
            db.session.commit()

        news_list = [
            {
                'id': news.id,
                'written_by': news.written_by,
                'header_text': news.header_text,
                'text': news.text,
                'images': news.images,
                'voices': news.voices,
                'files': news.files,
                'is_edited': news.is_edited,
                'views_count': news.views_count + 1,
                'timestamp': int(news.timestamp.timestamp() * 1000)
            }
            for news in news_paginated.items
        ]

        return jsonify(news_list), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    

@news_bp.route('/news/<int:news_id>', methods=['PUT'])
@jwt_required()
def edit_news(news_id):
    try:
        id_user = get_jwt_identity()
        user = User.query.get(id_user)
        if user.permission != 1:
            log = Log(id_user=id_user, action="edit_news", content=f"Failed: User tried to edit the news#{news_id} without permission", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({'error': 'You are not a moderator of the news section'}), 403
        
        news = News.query.get(news_id)
        if not news:
            log = Log(id_user=id_user, action="edit_news", content=f"News#{news_id} not found", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({'error': 'News post not found'}), 404
        
        data = request.get_json()
        # Обновляем поля
        updated = False
        text_content = news.text
        files_content = news.files

        if 'text' in data and news.text != data['text']:
            news.text = data['text']
            updated = True

        if 'header_text' in data and news.header_text != data['header_text']:
            news.header_text = data['header_text']
            updated = True

        if 'images' in data and news.images != data['images']:
            images_to_remove = [img for img in news.images if img not in data['images']]
            for img in images_to_remove:
                delete_news_file_if_exists(img)
            news.images = data['images']
            updated = True

        if 'files' in data and news.files != data['files']:
            files_to_remove = [fl for fl in news.files if fl not in data['files']]
            for fl in files_to_remove:
                delete_news_file_if_exists(fl)
            news.files = data['files']
            updated = True

        if 'voices' in data and news.voices != data['voices']:
            voices_to_remove = [vc for vc in news.voices if vc not in data['voices']]
            for vc in voices_to_remove:
                delete_news_file_if_exists(vc)
            news.voices = data['voices']
            updated = True

        if updated:
            news.is_edited = True
            db.session.commit()
            log = Log(id_user=id_user, action="edit_news", content=f"News was edited, old post: text: {text_content[:150] if text_content else ''}, "
            f"file: {files_content[:50] if files_content else ''}")
            db.session.add(log)
            db.session.commit()
            return jsonify({'message': 'News post updated successfully'}), 200
        else:
            return jsonify({'error': 'No changes made'}), 400

    except Exception as e:
        db.session.rollback()
        log = Log(id_user=id_user, action="edit_news", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({'error': str(e)}), 500


@news_bp.route('/news/<int:news_id>', methods=['DELETE'])
@jwt_required()
def delete_news(news_id):
    try:
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if user.permission != 1:
            log = Log(id_user=user_id, action="delete_news", content=f"Failed: User tried to delete the news#{news_id} without permission", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({'error': 'You are not a moderator of the news section'}), 403
        
        news = News.query.get(news_id)
        if not news:
            log = Log(id_user=user_id, action="edit_news", content=f"News#{news_id} not found", is_successful=False)
            db.session.add(log)
            db.session.commit()
            return jsonify({'error': 'News post not found'}), 404
        
        content = ""
        if news.images:
            for img in news.images:
                delete_news_file_if_exists(img) # Удаляем изображения 
            content += f"Deleted images: {news.images}"
        if news.files:
            for fl in news.files:
                delete_news_file_if_exists(fl) # Удаляем файлы  
            content += f"Deleted files: {news.files}"
        if news.voices:
            for vc in news.voices:
                delete_news_file_if_exists(vc) # Удаляем голосовые сообщения 
            content += f"Deleted voice messages: {news.voices}"
        if news.text:
            content += f" Deleted text message: {news.text}"

        db.session.delete(news)
        log_entry = Log(id_user=user_id, action="delete_news", content=content[:255])
        db.session.add(log_entry)
        db.session.commit()
        return jsonify({"message": "News post deleted successfully"}), 200

    except Exception as e:
        db.session.rollback()
        log = Log(id_user=user_id, action="delete_news", content=str(e)[:200], is_successful=False)
        db.session.add(log)
        db.session.commit()
        return jsonify({'error': str(e)}), 500


@news_bp.route('/news/key', methods=['GET'])
@jwt_required()
def get_news_key():
    try:
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user.news_key:
            return jsonify({"error": "Key not found"}), 404
        
        return jsonify({'news_key': user.news_key}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
