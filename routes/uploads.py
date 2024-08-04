import os
import uuid
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from flask_jwt_extended import jwt_required

uploads_bp = Blueprint('uploads', __name__)

# File Upload Configurations
UPLOAD_FOLDER_PHOTOS = 'uploads/photos'
UPLOAD_FOLDER_AUDIO = 'uploads/audio'
UPLOAD_FOLDER_FILES = 'uploads/files'

current_app.config['UPLOAD_FOLDER_PHOTOS'] = UPLOAD_FOLDER_PHOTOS
current_app.config['UPLOAD_FOLDER_AUDIO'] = UPLOAD_FOLDER_AUDIO
current_app.config['UPLOAD_FOLDER_FILES'] = UPLOAD_FOLDER_FILES

ALLOWED_PHOTO_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'ogg'}
ALLOWED_FILE_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}


def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def save_file(file, folder, allowed_extensions):
    if file and allowed_file(file.filename, allowed_extensions):
        filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower()
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER_' + folder.upper()], filename))
        return filename
    return None


# Routes for file operations
@uploads_bp.route('/upload/photo', methods=['POST'])
@jwt_required()
def upload_photo():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file provided'}), 400

    filename = save_file(file, 'PHOTOS', ALLOWED_PHOTO_EXTENSIONS)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    return jsonify({'filename': filename}), 201


@uploads_bp.route('/upload/audio', methods=['POST'])
@jwt_required()
def upload_audio():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file provided'}), 400

    filename = save_file(file, 'AUDIO', ALLOWED_AUDIO_EXTENSIONS)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    return jsonify({'filename': filename}), 201


@uploads_bp.route('/upload/file', methods=['POST'])
@jwt_required()
def upload_file():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file provided'}), 400

    filename = save_file(file, 'FILES', ALLOWED_FILE_EXTENSIONS)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    return jsonify({'filename': filename}), 201


@uploads_bp.route('/files/<folder>/<filename>', methods=['GET'])
@jwt_required()
def get_file(folder, filename):
    folder_mapping = {
        'photos': current_app.config['UPLOAD_FOLDER_PHOTOS'],
        'audio': current_app.config['UPLOAD_FOLDER_AUDIO'],
        'files': current_app.config['UPLOAD_FOLDER_FILES']
    }
    if folder not in folder_mapping:
        return jsonify({'error': 'Invalid folder'}), 400

    return send_from_directory(folder_mapping[folder], filename)


# Ensure the upload folders exist
def create_upload_folders():
    for folder in [UPLOAD_FOLDER_PHOTOS, UPLOAD_FOLDER_AUDIO, UPLOAD_FOLDER_FILES]:
        if not os.path.exists(folder):
            os.makedirs(folder)


create_upload_folders()
