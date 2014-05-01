import os

from web_ui import app

ASTROLAB_MODEL = os.path.join(app.config["USER_DATA"], 'enwiki_lda.model')
ASTROLAB_MODEL_IDS = os.path.join(app.config["USER_DATA"], 'enwiki__wordids.txt')

ASTROLAB_UPDATE = "http://dl.dropboxusercontent.com/u/46877/topic_model/enwiki_lda.model"
ASTROLAB_IDS_UPDATE = "http://dl.dropboxusercontent.com/u/46877/topic_model/enwiki__wordids.txt"
