from sklearn.naive_bayes import MultinomialNB
import numpy as np
from yordle.models import Naive_Bayes_Model, Word_Collection, Tag, Word_under_Tag_Count
from web_ui import app, db, notification_signals
from web_ui.helpers import get_active_persona

class Learner()

	def feature_fit():
		tags = Tag.query.filter_by(persona=get_active_persona)
		word_collections = Word_Collection.query.filter_by(persona=get_active_persona)
		word_collection_ids = np.asarray([coll.id for coll in word_collections])

		collection_counts = np.zeros(len(tags),len(word_collection_ids)

		tag_ids = list()
		word_counts = list()
		for i,tag in enumerate(tags):
			tag_ids.append(tag.id)
			word_counts_res = Word_under_Tag_Count.query.filter_by(persona=get_active_persona, tag_id=tag.id)
			counts = np.asarray([[res.collection_id, res.count] for res in word_counts_res])

			for j in np.arange(0,len(counts)):
				collection_counts[i,word_collection_ids==counts(j,0)] = counts(j,1)

		tag_ids = np.asarray(tag_ids)

		for i,id in enumerate(tag_ids):
			model = MultinomialNB()
			train_data = np.zeros(2,len(word_collection_ids))
			train_data[0,:] = collection_counts[i,:]
			train_data[1,:] = collection_counts.sum-train_data[0,:]
			model.fit(train_data, [1,0])

    		db_model = Naive_Bayes_Tag_Model.query.query.filter_by(persona=get_active_persona, tag_id=id)
    		db_model.model = model
