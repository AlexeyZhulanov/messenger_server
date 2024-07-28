import os


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://postgres:45839761@localhost/messenger_db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY', 'AOPSIJRD123DLKJ3ASD84HuhQW6YRGGQ7Wr3osjafh2nasfghqwUMNGP942HME46')
