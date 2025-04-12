import requests
import os
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from app import logger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Директория скрипта
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "XXXXXXX.json")

# Получаем токен доступа
def get_access_token():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/firebase.messaging"]
    )
    credentials.refresh(Request())
    return credentials.token

# Отправка FCM для пробуждения приложения
def send_push_wakeup(fcm_token):
    if not fcm_token:
        return

    access_token = get_access_token()
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "message": {
            "token": fcm_token,
            "data": {
                "type": "wakeup"  # Просто флаг, который можно обработать на клиенте
            }
        }
    }

    response = requests.post(
        "https://fcm.googleapis.com/v1/projects/XXXXXXXXXXX",
        json=payload,
        headers=headers
    )
    
    return response.json()


# Функция отправки уведомлений с хука
def send_gitlab_notification(fcm_token, title, body, url):
    if not fcm_token:
        return None

    # Формируем payload для FCM
    payload = {
        "message": {
            "token": fcm_token,
            "notification": {
                "title": title,
                "body": body
            },
            "data": {
                "type": "gitlab",
                "url": url
            }
        }
    }

    # Отправка уведомления
    access_token = get_access_token()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    logger.info(f"payload: {str(payload)}")
    try:
        response = requests.post(
            "https://fcm.googleapis.com/v1/projects/XXXXXXXXXXXXX",
            json=payload,
            headers=headers
        )
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка отправки FCM: {str(e)}")
        return None