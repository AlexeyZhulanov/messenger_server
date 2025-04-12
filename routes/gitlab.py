from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, GitlabSubs
import requests
from fcm import send_gitlab_notification
from app import logger


GITLAB_URL = "https://gitlab.amessenger.ru"
MESSENGER_HOOK_URL = "https://amessenger.ru/gitlab/webhook"

gitlab_bp = Blueprint('gitlab', __name__)


def load_gitlab_auth_token():
    with open('/etc/secrets/auth_token', 'rb') as f:
        return f.read().decode().strip()


# Генерация title и body для FCM-уведомления
def compose_notification(event_type, data):
    repo = data.get("project", {}).get("name", "Неизвестный репозиторий")
    url = data.get("project", {}).get("web_url", "https://gitlab.amessenger.ru")

    if event_type == "Push Hook":
        branch = data.get("ref", "").replace("refs/heads/", "")
        user = data.get("user_name") or data.get("user", {}).get("name", "Неизвестно")
        title = f"{user} сделал push"
        body = f"Ветка: {branch} | Репозиторий: {repo}"

    elif event_type == "Merge Request Hook":
        attr = data.get("object_attributes", {})
        user = data.get("user", {}).get("name", "Неизвестно")
        source = attr.get("source_branch", "")
        target = attr.get("target_branch", "")
        action = attr.get("action", "изменён")
        title = f"{user} {action} MR"
        body = f"{source} → {target} | {repo}"

    elif event_type == "Tag Push Hook":
        tag = data.get("ref", "").replace("refs/tags/", "")
        user = data.get("user_name") or data.get("user", {}).get("name", "Неизвестно")
        title = f"{user} создал тег"
        body = f"Тег: {tag} | Репозиторий: {repo}"

    elif event_type == "Issue Hook":
        attr = data.get("object_attributes", {})
        user = data.get("user", {}).get("name", "Неизвестно")
        action = attr.get("action", "изменён")
        title = f"{user} {action} issue"
        body = f"{attr.get('title', '')} | Репозиторий: {repo}"

    elif event_type == "Note Hook":
        attr = data.get("object_attributes", {})
        user = data.get("user", {}).get("name", "Неизвестно")
        note_type = attr.get("noteable_type", "объект")
        title = f"{user} оставил комментарий"
        body = f"К {note_type.lower()} в {repo}"

    elif event_type == "Release Hook":
        version = data.get("tag", "Новый релиз")
        user = data.get("commit", {}).get("author", {}).get("name", "Неизвестно")
        title = f"{user} создал релиз"
        body = f"{version} | Репозиторий: {repo}"

    else:
        title = f"Событие: {event_type}"
        body = f"Новое событие в {repo}"

    return title, body, url


@gitlab_bp.route("/gitlab/webhook", methods=["POST"])
def gitlab_webhook():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400
    
    token = request.headers.get("X-Gitlab-Token")
    if token != load_gitlab_auth_token():
        return jsonify({"error": "Unauthorized"}), 403

    event_type = request.headers.get("X-Gitlab-Event", "Unknown")

    project = data.get("project")
    if not project:
        return jsonify({"error": "No project data"}), 400
    
    project_id = project.get("id")
    if not project_id:
        return jsonify({"error": "No project ID"}), 400

    # Находим пользователей, подписанных на данный проект и событие
    subscriptions = GitlabSubs.query.filter_by(project_id=project_id).all()
    fcm_tokens = [
        sub.user.fcm_token
        for sub in subscriptions
        if sub.user.fcm_token and (
            (event_type == "Push Hook" and sub.hook_push) or
            (event_type == "Merge Request Hook" and sub.hook_merge) or
            (event_type == "Tag Push Hook" and sub.hook_tag) or
            (event_type == "Issue Hook" and sub.hook_issue) or
            (event_type == "Note Hook" and sub.hook_note) or
            (event_type == "Release Hook" and sub.hook_release)
        )
    ]
    
    title, body, url = compose_notification(event_type, data)
    # Вызываем отправку уведомлений
    for fcm_token in fcm_tokens:
        if fcm_token:
            send_gitlab_notification(fcm_token, title, body, url)

    return jsonify({"message": "Webhook обработан"}), 200


@gitlab_bp.route('/gitlab/<token>', methods=['GET'])
@jwt_required()
def get_repositories(token):
    try:
        """Получает список всех репозиториев и проверяет наличие Webhook'ов."""
        headers = {"PRIVATE-TOKEN": token}
        response = requests.get(f"{GITLAB_URL}/api/v4/projects", headers=headers)

        if response.status_code != 200:
            logger.info(f"Ошибка при получении репозиториев: {response.json()}")
            return jsonify({"error": "Repositories not found"}), 404

        user_id = get_jwt_identity()

        projects = response.json()
        projects_sorted = sorted(
            projects,
            key=lambda x: x["last_activity_at"],
            reverse=True  # Сортировка по убыванию (сначала самые свежие)
        )

        repo_info = []

        for project in projects_sorted:
            project_id = project["id"]
            project_name = project["name"]
            web_url = project["web_url"]
            last_activity = project["last_activity_at"]

            hooks = GitlabSubs.query.filter_by(user_id=user_id, project_id=project_id).first()

            repo_info.append({
                "id": project_id,
                "name": project_name,
                "web_url": web_url,
                "last_activity": last_activity,
                "hook_push": hooks.hook_push if hooks else False,
                "hook_merge": hooks.hook_merge if hooks else False,
                "hook_tag": hooks.hook_tag if hooks else False,
                "hook_issue": hooks.hook_issue if hooks else False,
                "hook_note": hooks.hook_note if hooks else False,
                "hook_release": hooks.hook_release if hooks else False
            })

        return jsonify(repo_info), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@gitlab_bp.route('/gitlab/notifications/<int:project_id>', methods=['PUT'])
@jwt_required()
def update_sub(project_id):
    try:
        user_id = get_jwt_identity()
        sub = GitlabSubs.query.filter_by(user_id=user_id, project_id=project_id).first()
        if not sub:
            new_sub = GitlabSubs(user_id=user_id, project_id=project_id)
            db.session.add(new_sub)
            db.session.flush()
            sub = new_sub

        data = request.get_json()
        sub.hook_push = data.get('hook_push', sub.hook_push)
        sub.hook_merge = data.get('hook_merge', sub.hook_merge)
        sub.hook_tag = data.get('hook_tag', sub.hook_tag)
        sub.hook_issue = data.get('hook_issue', sub.hook_issue)
        sub.hook_note = data.get('hook_note', sub.hook_note)
        sub.hook_release = data.get('hook_release', sub.hook_release)
        db.session.commit()
        return jsonify({'message': 'Sub updated successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
