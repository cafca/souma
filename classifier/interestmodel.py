from web_ui import db
from sklearn.naive_bayes import GaussianNB

class InterestModel(Serializable, db.Model):
	"""Model for learning and predicting likes
	   Should be inherited by Personas and Groups later"""

	classifier = db.Column(db.PickleType)

	def __init__(self):
		classifier = GaussianNB()

	def train(self, topic_vectors, likes):
		"""Fits classifier onto topic vectors and the corresponding like/nolike"""
		classifier.fit(topic_vectors, likes)

	def predict_like(self, topic_vectors):
		"""Predicts if the combination of topics is liked"""
		return classifier.predict(topic_vectors)