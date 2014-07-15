from gensim.models import LdaModel
from gensim.corpora import Dictionary
from astrolab.helpers import tokenize


class TopicModel(object):

    num_topics = 200

    def __init__(self, lda_file, dic_file):
        self.lda_model = LdaModel.load(lda_file)
        self.dictionary = Dictionary.load_from_text(dic_file)

    def get_topics_text(self, text):
        clear_content = tokenize(text)
        bow = self.dictionary.doc2bow(clear_content)

        return self.get_topics_bow(bow)

    def get_topics_bow(self, bow):
        topics = self.lda_model[bow]
        topic_vec = [0] * self.num_topics
        for topic in topics:
            topic_vec[topic[0]] = topic[1]

        return topic_vec
