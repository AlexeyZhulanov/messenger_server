from PIL import Image
import ffmpeg
import os
import uuid
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from flask_jwt_extended import jwt_required
from app import logger

uploads_bp = Blueprint('uploads', __name__)

ALLOWED_ONLY_PHOTO_EXTENSIONS = {'jpg', 'jpeg', 'png'}
ALLOWED_PHOTO_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'mp4', 'avi', 'mpeg', 'mov', 'mkv'} # photo+video
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'ogg', 'pcm'}
ALLOWED_FILE_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'mpeg'}
all_extensions = ALLOWED_PHOTO_EXTENSIONS | ALLOWED_FILE_EXTENSIONS | ALLOWED_AUDIO_EXTENSIONS



def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def generate_unique_filename(directory, filename):
    """
    Генерирует уникальное имя файла, добавляя суффикс (1), (2), если файл уже существует.
    """
    name, extension = os.path.splitext(filename)
    counter = 1
    unique_filename = filename
    
    # Пока файл с таким именем существует, генерируем новое имя
    while os.path.exists(os.path.join(directory, unique_filename)):
        unique_filename = f"{name}({counter}){extension}"
        counter += 1
        
    return unique_filename


def create_partitioned_path(dialog_id, folder, subfolder_type='original', is_group=False):
    """
    Создает путь с партицированием: тип_файла/dialog_id/имя_файла
    """
    base_folder = current_app.config['UPLOAD_FOLDER_BASE']
    addition = current_app.config['UPLOAD_FOLDER_DIALOGS'] if not is_group else current_app.config['UPLOAD_FOLDER_GROUPS']
    base_folder = os.path.join(base_folder, addition)
    subfolder = {
        'PHOTOS': current_app.config['UPLOAD_FOLDER_PHOTOS'],
        'AUDIO': current_app.config['UPLOAD_FOLDER_AUDIO'],
        'FILES': current_app.config['UPLOAD_FOLDER_FILES']
    }.get(folder.upper())

    # Полный путь с учетом subfolder_type (если он не пустой)
    partitioned_path = os.path.join(base_folder, subfolder, str(dialog_id))
    if subfolder_type:
        partitioned_path = os.path.join(partitioned_path, subfolder_type)

    # Создаем директорию только если есть указание на подкаталог
    os.makedirs(partitioned_path, exist_ok=True)

    return partitioned_path


def save_file(file, dialog_id, folder, allowed_extensions, is_group=0):
    if file and allowed_file(file.filename, allowed_extensions):
        # Создаем путь с учетом партицирования
        is_image_or_video = folder.upper() in ['PHOTOS']
        subfolder_type = 'original' if is_image_or_video else ''
        f = is_group == 1
        partitioned_path = create_partitioned_path(dialog_id, folder, subfolder_type, f)
        
        # Проверяем и создаем уникальное имя файла
        unique_filename = generate_unique_filename(partitioned_path, file.filename)

        # Путь для сохранения файла
        file_path = os.path.join(partitioned_path, unique_filename)

        # Сохраняем файл
        file.save(file_path)

        return unique_filename
    return None


def save_file_with_preview(file, dialog_id, folder, allowed_extensions, is_video, is_group=0):
    if file and allowed_file(file.filename, allowed_extensions):
        f = is_group == 1
        partitioned_original_path = create_partitioned_path(dialog_id, folder, 'original', f)
        unique_filename = generate_unique_filename(partitioned_original_path, file.filename)
        partitioned_preview_path = create_partitioned_path(dialog_id, folder, 'preview', f)

        # Путь для оригинального файла
        original_file_path = os.path.join(partitioned_original_path, unique_filename)

        # Сохраняем оригинальный файл
        file.save(original_file_path)

        # Генерация превью
        if is_video:
            create_video_preview(original_file_path, partitioned_preview_path, unique_filename)
        else:
            create_image_preview(original_file_path, partitioned_preview_path, unique_filename)

        return unique_filename
    return None


def create_image_preview(original_file_path, preview_path, filename):
    try:
        # Открываем изображение и уменьшаем его размер для превью
        with Image.open(original_file_path) as img:
            img.thumbnail((300, 300))  # Пример уменьшения до 300x300
            preview_file_path = os.path.join(preview_path, filename)
            img.save(preview_file_path, "JPEG")
        return filename
    except Exception as e:
        print(f"Error creating image preview: {e}")
        return None


def create_video_preview(original_file_path, preview_path, filename):
    try:
        duration = get_video_duration(original_file_path)
        if duration is None:
            logger.info("Could not retrieve duration")
            return None

        # Получаем расширение видео
        video_extension = os.path.splitext(filename)[1][1:]  # например, "mp4" без точки

        # Формируем название превью с продолжительностью и форматом
        preview_filename = f"{filename.rsplit('.', 1)[0]}_{duration}s:{video_extension}.jpg"
        preview_file_path = os.path.join(preview_path, preview_filename)
        (
            ffmpeg
            .input(original_file_path, ss=0)  # Кадр на 0 секунде
            .output(preview_file_path, vframes=1, format='image2', vcodec='mjpeg', qscale=5)  # Уменьшаем качество
            .run(capture_stdout=True, capture_stderr=True)
        )
        
        return preview_filename
    except Exception as e:
        logger.info(f"Error creating video preview: {e}")
        return None


def get_video_duration(file_path):
    try:
        # Используем ffmpeg.probe для получения метаданных видео
        probe = ffmpeg.probe(file_path)
        # Длительность хранится в секундах в формате float
        duration = float(probe['format']['duration'])
        return int(duration)
    except Exception as e:
        logger.info(f"Error getting video duration: {e}")
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


def save_news_file(file):
    # Так как новостей будет немного, не напрягаем сервер и скидываем файлы всех видов в общую директорию
    if file and allowed_file(file.filename, all_extensions):
        news_folder = os.path.join(current_app.config['UPLOAD_FOLDER_BASE'], 'news')
        os.makedirs(news_folder, exist_ok=True)

        unique_filename = generate_unique_filename(news_folder, file.filename)
        file_path = os.path.join(news_folder, unique_filename)
        file.save(file_path)

        return unique_filename
    
    return None


@uploads_bp.route('/upload/photo/<int:dialog_id>/<int:is_group>', methods=['POST'])
@jwt_required()
def upload_photo(dialog_id, is_group=0):
    file = request.files.get('file')

    if not file or not dialog_id:
        return jsonify({'error': 'No file or dialog_id provided'}), 400

    # Определяем тип файла (фото или видео)
    file_extension = file.filename.rsplit('.', 1)[-1].lower()
    is_video = file_extension in ALLOWED_VIDEO_EXTENSIONS
    
    filename = save_file_with_preview(file, dialog_id, 'PHOTOS', ALLOWED_PHOTO_EXTENSIONS, is_video, is_group)
    
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    return jsonify({'filename': filename}), 201


@uploads_bp.route('/upload/audio/<int:dialog_id>/<int:is_group>', methods=['POST'])
@jwt_required()
def upload_audio(dialog_id, is_group=0):
    file = request.files.get('file')

    if not file or not dialog_id:
        return jsonify({'error': 'No file or dialog_id provided'}), 400

    filename = save_file(file, dialog_id, 'AUDIO', ALLOWED_AUDIO_EXTENSIONS, is_group)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    return jsonify({'filename': filename}), 201


@uploads_bp.route('/upload/file/<int:dialog_id>/<int:is_group>', methods=['POST'])
@jwt_required()
def upload_file(dialog_id, is_group=0):
    file = request.files.get('file')

    if not file or not dialog_id:
        return jsonify({'error': 'No file or dialog_id provided'}), 400

    filename = save_file(file, dialog_id, 'FILES', ALLOWED_FILE_EXTENSIONS, is_group)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400
    logger.info(f"Uploaded new file: {file} in dialog: {dialog_id}")

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


@uploads_bp.route('/upload/news', methods=['POST'])
@jwt_required()
def upload_news():
    file = request.files.get('file')

    if not file:
        return jsonify({'error': 'No file provided'}), 400
    
    filename = save_news_file(file)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    return jsonify({'filename': filename}), 201


@uploads_bp.route('/files/<folder>/<int:dialog_id>/<filename>/<int:is_group>', methods=['GET'])
@jwt_required()
def get_file(folder, dialog_id, filename, is_group=0):
    folder_mapping = {
        'photos': current_app.config['UPLOAD_FOLDER_PHOTOS'],
        'audio': current_app.config['UPLOAD_FOLDER_AUDIO'],
        'files': current_app.config['UPLOAD_FOLDER_FILES']
    }
    if folder not in folder_mapping:
        return jsonify({'error': 'Invalid folder'}), 400
    
    addition = current_app.config['UPLOAD_FOLDER_DIALOGS'] if is_group == 0 else current_app.config['UPLOAD_FOLDER_GROUPS']

    # Проверяем, если это фото, добавляем /original к пути
    if folder == 'photos':
        file_path = os.path.join(
            current_app.config['UPLOAD_FOLDER_BASE'], 
            addition, 
            folder_mapping[folder], 
            str(dialog_id), 
            'original',  # Добавляем 'original' только для фотографий
            filename
        )
    else:
        # Для файлов и аудио оставляем без изменений
        file_path = os.path.join(
            current_app.config['UPLOAD_FOLDER_BASE'], 
            addition, 
            folder_mapping[folder], 
            str(dialog_id), 
            filename
        )

    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404

    return send_from_directory(os.path.dirname(file_path), filename)


@uploads_bp.route('/media/preview/<int:dialog_id>/<filename>/<int:is_group>', methods=['GET'])
@jwt_required()
def get_media_preview(dialog_id, filename, is_group=0):
    # Построение партицированного пути для превью
    f = is_group == 1
    partitioned_folder = create_partitioned_path(dialog_id, 'PHOTOS', 'preview', f)
    file_path = os.path.join(partitioned_folder, filename)

    # Проверка существования файла
    if not os.path.exists(file_path):
        return jsonify({'error': 'Preview file not found'}), 404

    # Возвращаем превью файл
    return send_from_directory(os.path.dirname(file_path), filename)


@uploads_bp.route('/avatars/<filename>', methods=['GET'])
@jwt_required()
def get_avatar(filename):
    avatars_folder = os.path.join(current_app.config['UPLOAD_FOLDER_BASE'], 'avatars')
    
    file_path = os.path.join(avatars_folder, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404

    return send_from_directory(avatars_folder, filename)

    
@uploads_bp.route('/news/<filename>', methods=['GET'])
@jwt_required()
def get_news(filename):
    news_folder = os.path.join(current_app.config['UPLOAD_FOLDER_BASE'], 'news')
    
    file_path = os.path.join(news_folder, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404

    return send_from_directory(news_folder, filename)


def get_preview_path(base_folder_path, filename):
    file_extension = filename.lower().rsplit('.', 1)[-1]

    if file_extension in ALLOWED_ONLY_PHOTO_EXTENSIONS:
        return os.path.join(base_folder_path, 'preview', filename)
    
    preview_folder = os.path.join(base_folder_path, 'preview')

    if os.path.exists(preview_folder):
        preview_filename_prefix = os.path.splitext(filename)[0]
        preview_file = next((f for f in os.listdir(preview_folder) if f.startswith(preview_filename_prefix)), None)
        if preview_file:
            return os.path.join(preview_folder, preview_file)
    
    return None


def delete_file_from_disk(folder, dialog_id, filename, is_group=False):
    folder_mapping = {
        'photos': current_app.config['UPLOAD_FOLDER_PHOTOS'],
        'audio': current_app.config['UPLOAD_FOLDER_AUDIO'],
        'files': current_app.config['UPLOAD_FOLDER_FILES']
    }
    
    if folder not in folder_mapping:
        return False, 'Invalid folder'

    addition = current_app.config['UPLOAD_FOLDER_DIALOGS'] if not is_group else current_app.config['UPLOAD_FOLDER_GROUPS']
    # Базовый путь с партицированием
    base_folder_path = os.path.join(current_app.config['UPLOAD_FOLDER_BASE'], addition, folder_mapping[folder], str(dialog_id))

    # Фото и видео
    if folder == 'photos':
        original_path = os.path.join(base_folder_path, 'original', filename)
        preview_path = get_preview_path(base_folder_path, filename)

        errors = []

        for path in [original_path, preview_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    errors.append(f"Error deleting {path}: {str(e)}")
            else:
                errors.append(f"File not found: {path}")
        
        if errors:
            return False, 'Some files could not be deleted: ' + '; '.join(errors)
        return True, 'Original and preview photos deleted successfully'

    # Файлы и аудио
    file_path = os.path.join(base_folder_path, filename)
    
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
            logger.info(f'Avatar {filename} deleted successfully')
        except Exception as e:
            logger.info(f'Error deleting avatar {filename}: {str(e)}')


def delete_news_file_if_exists(filename):
    if not filename:
        return
    
    news_folder = os.path.join(current_app.config['UPLOAD_FOLDER_BASE'], 'news')
    file_path = os.path.join(news_folder, filename)

    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.info(f'News {filename} deleted successfully')
        except Exception as e:
            logger.info(f'Error deleting news {filename}: {str(e)}')


def get_dialog_medias(dialog_id, is_group=0, page=0, page_size=12):
    f = is_group == 1
    preview_folder = create_partitioned_path(dialog_id, 'PHOTOS', 'preview', f)
    all_files = []
    
    # Собираем все файлы с разрешенными расширениями
    for filename in sorted(os.listdir(preview_folder), reverse=True):  # сортировка от новых к старым
        if allowed_file(filename, ALLOWED_PHOTO_EXTENSIONS):
            all_files.append(filename)
    
    # Пагинация
    start = page * page_size
    end = start + page_size
    paginated_files = all_files[start:end]
    
    return jsonify({'filename': paginated_files})



def get_dialog_files(dialog_id, is_group=0, page=0, page_size=10):
    f = is_group == 1
    files_folder = create_partitioned_path(dialog_id, 'FILES', '', f)
    all_files = []
    
    # Собираем все файлы с разрешенными расширениями
    for filename in sorted(os.listdir(files_folder), reverse=True):
        if allowed_file(filename, ALLOWED_FILE_EXTENSIONS):
            all_files.append(filename)
    
    # Пагинация
    start = page * page_size
    end = start + page_size
    paginated_files = all_files[start:end]
    
    return jsonify({'filename': paginated_files})


def get_dialog_audios(dialog_id, is_group=0, page=0, page_size=20):
    f = is_group == 1
    audio_folder = create_partitioned_path(dialog_id, 'AUDIO', '', f)
    all_files = []
    
    # Собираем все аудиофайлы с разрешенными расширениями
    for filename in sorted(os.listdir(audio_folder), reverse=True):
        if allowed_file(filename, ALLOWED_AUDIO_EXTENSIONS):
            all_files.append(filename)
    
    # Пагинация
    start = page * page_size
    end = start + page_size
    paginated_files = all_files[start:end]
    
    return jsonify({'filename': paginated_files})


@uploads_bp.route('/files/<int:is_group>/<int:dialog_id>/media/<int:page>', methods=['GET'])
@jwt_required()
def fetch_media(dialog_id, is_group=0, page=0):
    return get_dialog_medias(dialog_id, is_group, page)


@uploads_bp.route('/files/<int:is_group>/<int:dialog_id>/file/<int:page>', methods=['GET'])
@jwt_required()
def fetch_file(dialog_id, is_group=0, page=0):
    return get_dialog_files(dialog_id, is_group, page)


@uploads_bp.route('/files/<int:is_group>/<int:dialog_id>/audio/<int:page>', methods=['GET'])
@jwt_required()
def fetch_audio(dialog_id, is_group=0, page=0):
    return get_dialog_audios(dialog_id, is_group, page)
