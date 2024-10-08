import os
import uuid
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from flask_jwt_extended import jwt_required

uploads_bp = Blueprint('uploads', __name__)

ALLOWED_PHOTO_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'mp4', 'avi', 'mpeg'}
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'ogg', 'pcm'}
ALLOWED_FILE_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}


def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def create_partitioned_path(dialog_id, folder):
    """
    Создает путь с партицированием: тип_файла/dialog_id/имя_файла
    """
    base_folder = current_app.config['UPLOAD_FOLDER_BASE']
    # Определяем соответствующую папку для хранения (photos, audio, files)
    subfolder = {
        'PHOTOS': current_app.config['UPLOAD_FOLDER_PHOTOS'],
        'AUDIO': current_app.config['UPLOAD_FOLDER_AUDIO'],
        'FILES': current_app.config['UPLOAD_FOLDER_FILES']
    }.get(folder.upper())

    # Формируем полный путь
    partitioned_path = os.path.join(base_folder, subfolder, str(dialog_id))

    # Создаем необходимые папки, если они не существуют
    os.makedirs(partitioned_path, exist_ok=True)
    
    return partitioned_path


def save_file(file, dialog_id, folder, allowed_extensions):
    if file and allowed_file(file.filename, allowed_extensions):
        # Генерируем уникальное имя файла
        filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower()

        # Создаем путь с учетом партицирования
        partitioned_path = create_partitioned_path(dialog_id, folder)
        file_path = os.path.join(partitioned_path, filename)

        # Сохраняем файл
        file.save(file_path)

        return filename
    return None


def save_avatar(file, allowed_extensions):
    if file and allowed_file(file.filename, allowed_extensions):
        # Генерируем уникальное имя файла
        filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower()

        # Путь для аватарок
        avatars_folder = os.path.join(current_app.config['UPLOAD_FOLDER_BASE'], 'avatars')
        os.makedirs(avatars_folder, exist_ok=True)

        file_path = os.path.join(avatars_folder, filename)

        # Сохраняем файл
        file.save(file_path)

        return filename
    return None


@uploads_bp.route('/upload/photo/<int:dialog_id>', methods=['POST'])
@jwt_required()
def upload_photo(dialog_id):
    file = request.files.get('file')

    if not file or not dialog_id:
        return jsonify({'error': 'No file or dialog_id provided'}), 400

    filename = save_file(file, dialog_id, 'PHOTOS', ALLOWED_PHOTO_EXTENSIONS)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    return jsonify({'filename': filename}), 201


@uploads_bp.route('/upload/audio/<int:dialog_id>', methods=['POST'])
@jwt_required()
def upload_audio(dialog_id):
    file = request.files.get('file')

    if not file or not dialog_id:
        return jsonify({'error': 'No file or dialog_id provided'}), 400

    filename = save_file(file, dialog_id, 'AUDIO', ALLOWED_AUDIO_EXTENSIONS)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    return jsonify({'filename': filename}), 201


@uploads_bp.route('/upload/file/<int:dialog_id>', methods=['POST'])
@jwt_required()
def upload_file(dialog_id):
    file = request.files.get('file')

    if not file or not dialog_id:
        return jsonify({'error': 'No file or dialog_id provided'}), 400

    filename = save_file(file, dialog_id, 'FILES', ALLOWED_FILE_EXTENSIONS)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    return jsonify({'filename': filename}), 201


@uploads_bp.route('/upload/avatar', methods=['POST'])
@jwt_required()
def upload_avatar():
    file = request.files.get('file')

    if not file:
        return jsonify({'error': 'No file provided'}), 400

    filename = save_avatar(file, ALLOWED_PHOTO_EXTENSIONS)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    return jsonify({'filename': filename}), 201


@uploads_bp.route('/files/<folder>/<dialog_id>/<filename>', methods=['GET'])
@jwt_required()
def get_file(folder, dialog_id, filename):
    folder_mapping = {
        'photos': current_app.config['UPLOAD_FOLDER_PHOTOS'],
        'audio': current_app.config['UPLOAD_FOLDER_AUDIO'],
        'files': current_app.config['UPLOAD_FOLDER_FILES']
    }
    if folder not in folder_mapping:
        return jsonify({'error': 'Invalid folder'}), 400

    # Строим путь с партицированием
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER_BASE'], folder_mapping[folder], dialog_id, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404

    return send_from_directory(os.path.dirname(file_path), filename)


@uploads_bp.route('/avatars/<filename>', methods=['GET'])
@jwt_required()
def get_avatar(filename):
    avatars_folder = os.path.join(current_app.config['UPLOAD_FOLDER_BASE'], 'avatars')
    
    file_path = os.path.join(avatars_folder, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404

    return send_from_directory(avatars_folder, filename)


@uploads_bp.route('/files/<folder>/<dialog_id>/<filename>', methods=['DELETE'])
@jwt_required()
def delete_file(folder, dialog_id, filename):
    result, msg = delete_file_from_disk(folder, dialog_id, filename)
    if result:
        return jsonify({'message': 'File deleted successfully'}), 200
    else:
        return jsonify({'error': msg}), 400


def delete_file_from_disk(folder, dialog_id, filename):
    folder_mapping = {
        'photos': current_app.config['UPLOAD_FOLDER_PHOTOS'],
        'audio': current_app.config['UPLOAD_FOLDER_AUDIO'],
        'files': current_app.config['UPLOAD_FOLDER_FILES']
    }
    
    if folder not in folder_mapping:
        return False, 'Invalid folder'

    # Строим путь с партицированием
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER_BASE'], folder_mapping[folder], dialog_id, filename)
    
    if not os.path.exists(file_path):
        return False, 'File not found'

    try:
        os.remove(file_path)
        return True, 'File deleted successfully'
    except Exception as e:
        return False, str(e)


def delete_avatar_file_if_exists(filename):
    if not filename:
        return

    avatars_folder = os.path.join(current_app.config['UPLOAD_FOLDER_BASE'], 'avatars')
    file_path = os.path.join(avatars_folder, filename)

    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            print(f'Avatar {filename} deleted successfully')
        except Exception as e:
            print(f'Error deleting avatar {filename}: {str(e)}')
