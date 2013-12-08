import lxml.html
from lxml.html import clean

from gensim.models import LdaModel
from gensim import utils

def _clean_attrib(node):
	for n in node:
		_clean_attrib(n)
	node.attrib.clear()

def clean_document(document):
	"""Removes HTML from strings"""

	tree = lxml.html.fromstring(document)
	cleaner = clean.Cleaner(style=True)
	cleaner.clean_html(tree)
	_clean_attrib(tree)

	return lxml.html.tostring(tree, encoding='unicode', pretty_print=True, 
                         method='text')

def tokenize_document(document):
	"""Tokenizes string into list of words"""

	return [token.encode('utf8') for token in utils.tokenize(document, lower=True, errors='ignore')
			if 2<= len(token) <=15 and not token.startswith('_')]

class TopicModel(LdaModel):
	"""Loads a trained LDA Model"""

	def document2bow(self, doc_tokenized):
		"""Transforms tokenized document into Bag-of-Words"""

		return self.id2word.doc2bow(doc_tokenized)

	def predict_topics(self, document, clean=False):
		"""Predict the topics of a document"""
		
		if not clean:
			document = clean_document(document)

		doc_tokenized = tokenize_document(document)
		doc_bow = self.document2bow(doc_tokenized)

		topic_values = self[doc_bow]
		full_topic_values = [0] * self.num_topics

		for topic in topic_values:
			full_topic_values[topic[0]] = topic[1]

		return full_topic_values