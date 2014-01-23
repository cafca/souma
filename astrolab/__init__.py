from astrolab.topicmodel import TopicModel
from astrolab.helpers import repeated_func_schedule
from astrolab.interestmodel import update

topic_model = TopicModel('enwiki_lda.model', 'enwiki__wordids.txt')

repeated_func_schedule(60 * 60, update())
