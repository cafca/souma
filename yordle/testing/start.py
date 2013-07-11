# -*- coding: cp1252 -*-
import stuff
from nltk.corpus import reuters, brown
from nltk.util import flatten
import json
import pdb
import numpy as np
from nltk import FreqDist

"""Trainiert 2 verschiedene Naive Bayes classifier auf für einen User interessante
Texte.
Der erste classifier lernt Texte in verschiedene Kategorien einzuordnen
Der zweite lernt welche Kategorien der User interessant findet"""

# 1500 zufällige Textpassagen aus dem Reuters
print 'Load corpus'
#corp = reuters.raw()
print 'Loaded corpus'
#rnd = np.random.randint(0,len(corp)/2,1500)
#raw_documents = [corp[i:i+300] for i in rnd]
print 'Created docs'

pdb.set_trace()
corp = brown.paras(categories='hobbies')
rnd = np.random.randint(0,len(corp)-3,300)
raw_documents = [flatten(corp[i:i+3]) for i in rnd]
pdb.set_trace()
raw_doc2 = list()
for doc in raw_documents:
    raw_doc2.append(''.join(str(word)+" " for word in doc))
raw_documents = raw_doc2

pdb.set_trace()
#posts_j = json.load(open('cogsci.json'))
#posts = posts_j.values()
#raw_documents = list()
#for post in posts:
#    if post.has_key('message'):
#        raw_documents.append(post['message'])
#
max_docs = len(raw_documents)
doc = [{}]*max_docs
for i in range(0,max_docs):
    doc[i] = stuff.refactor_doc(raw_documents[i]) #Bearbeite Dokumente vor

print 'Refactored docs'

pdb.set_trace()
features = stuff.extract_doc_feats(doc) #TFIDF extrahieren
print 'Extracted features'

pdb.set_trace()
feats = np.asarray(features[0])
tags = feats.argsort(axis=1)[:,-10:] #Findet für jeden Text die 10 wichtigsten Wörter

tflat = tags.flatten()
counts = FreqDist(tflat.tolist()) #Zählt wie oft welcher Tag vorkommt

# Wähle mir 15 zufällige Interessen aus den Tags heraus
# Wobei wichtigere Tags wahrscheinlicher sind
interests_idx = np.ceil(np.random.beta(2,5,10)*100)
interests_idx = interests_idx[interests_idx<100]
interests = np.asarray(counts.keys())
interests = interests[interests_idx.astype(int)]

# Jedes Dokument, das eine Interesse als Tag enthält wird "geliket"
likes = np.zeros(max_docs)
for i in np.arange(0,max_docs):
    tmp = np.intersect1d(tags[i,:],interests)
    if len(tmp) > 0:
        likes[i] = 1


#Trainings und Testsets
u_tags = counts.keys()[0:100]

feats_train = feats[0:200,:]
feats_test = feats[200:-1,:]

tags_train = tags[0:200,:]
tags_test = tags[200:-1,:]

likes_train = likes[0:200]
likes_test = likes[200:-1]

pdb.set_trace()
#counts = stuff.word_under_tag_count(feats_train, tags_train, u_tags)

#m = stuff.map_data(features[0])
pdb.set_trace()
#feat_models = stuff.classify_feats(counts,tags_train, u_tags)

#Trainiere welche TFIDFs welche Tags vorraussagen
feat_models = stuff.classify_feats_tfidf(feats_train,tags_train, u_tags)

pdb.set_trace()
#Erstelle aus dem Modell binary arrays, die besagen ob ein Text ein Tag
#enthalten sollte oder nicht
tag_vectors_train = stuff.make_tag_vecs(feats_train,feat_models)
tag_vectors_test = stuff.make_tag_vecs(feats_test,feat_models)

pdb.set_trace()
#Trainiere Tag-Kombinationen auf die vorlieben des Users
tag_model = stuff.classify_tags(tag_vectors_train,likes_train)
print 'Did map'
pdb.set_trace()

#Sage für das Testset voraus, welche Dokumente der User liken sollte
classify_test = tag_model.predict(tag_vectors_test)

#buggy performance_feats = float(np.sum(tag_vectors_test==tags_test).sum())/float(len(tags_test.flatten()))
performance_tags = float(np.sum(classify_test==likes_test))/float(len(likes_test))

#print "Perf. Feats:", performance_feats
print "Perf. Tags:", performance_tags
pdb.set_trace()


try:
    f = open("textx.txt", "w")
    try:
        f.write('Interessen:\n')
        for interest in interests:
            f.writelines([features[1][interest],'\n'])

        f.write('\n')
        f.write('\n')
        f.write('Gelikte Trainingstexte:\n')
        for i,like in enumerate(likes_train):
            if like == 1:
                f.writelines([raw_documents[i],'\n'])
                f.writelines(np.asarray([[features[1][tag],'\n'] for tag in tags_train[i]]).flatten().tolist())
                f.write('\n') 

        f.write('\n')
        f.write('\n')
        f.write('Gelikte Testtexte:\n')
        for i,like in enumerate(classify_test):
            if like == 1:
                f.writelines([raw_documents[i+200],'\n'])
                f.writelines(np.asarray([[features[1][tag],'\n'] for tag in tags_test[i]]).flatten().tolist())
                f.write('\n') 

    finally:
        f.close()
except IOError:
    pass
