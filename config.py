import os


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://alex:45839761@localhost/messenger_db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY', 'AOPSIJRD123DLKJ3ASD84HuhQW6YRGGQ7Wr3osjafh2nasfghqwUMNGP942HME46')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'g0PtQm97!XyD@z6w#rF2VkLb$Np8YcT&Jh5Za*M4UoE^HdB1Cs') 
    UPLOAD_FOLDER_BASE = 'uploads'
    UPLOAD_FOLDER_PHOTOS = 'photos'
    UPLOAD_FOLDER_AUDIO = 'audio'
    UPLOAD_FOLDER_FILES = 'files'
    UPLOAD_FOLDER_DIALOGS = 'dialogs'
    UPLOAD_FOLDER_GROUPS = 'groups'
