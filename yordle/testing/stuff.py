def map_data(feature_matrix):
    from mvpa2.suite import SimpleSOMMapper as SOM
    import sompy
    import math
    import numpy

    n_train = len(feature_matrix)
    size = math.sqrt(n_train)
    som = SOM((50,50), 400, learning_rate=0.05)
    som.train(numpy.asarray(feature_matrix))

    #som = sompy.SOM(20,20, len(feature_matrix[0]))
    #som.train(500, feature_matrix)

    return som

def classify_bayes(feature_matrix, classes):
    from sklearn.naive_bayes import GaussianNB
    import numpy

    classifier = GaussianNB()
    classifier.fit(numpy.asarray(feature_matrix), numpy.asarray(classes))

    return classifier

def classify_feats(feature_matrix, classes, utags):
    from sklearn.naive_bayes import MultinomialNB
    import numpy

    models = list()
    for tag in numpy.arange(0,len(utags)):
        count = numpy.zeros((2,feature_matrix.shape[1]))
        count[0,:] = feature_matrix[tag,:]
        count[1,:] = sum(feature_matrix) - count[0,:]

        classifier = MultinomialNB(alpha=0.1)
        classifier.fit(count, [1,0])
        models.append(classifier)

    return models

def classify_feats_tfidf(feature_matrix, classes, utags):
    from sklearn.naive_bayes import MultinomialNB
    import numpy

    models = list()
    for tag in numpy.arange(0,len(utags)):
        hits = numpy.where(classes == utags[tag])
        hits = hits[0]
        class_ = numpy.zeros(len(classes))
        class_[hits] = 1

        classifier = MultinomialNB(alpha=0.1)
        classifier.fit(feature_matrix, class_)
        models.append(classifier)

    return models

def classify_tags(feats,tags):
    from sklearn.naive_bayes import BernoulliNB
    import numpy

    classifier = BernoulliNB()
    classifier.fit(feats, tags.tolist())

    return classifier

def make_tag_vecs(doc_feats,models):
    import numpy
    probs = numpy.zeros((len(doc_feats),len(models)))
    for j,model in enumerate(models):
        prob = model.predict(doc_feats)
        probs[:,j] = numpy.asarray(prob)

    return probs

def lemmatize(word, pos='n'):
    from nltk.corpus import wordnet
    lemmas = wordnet._morphy(word, pos)
    return min(lemmas, key=len) if lemmas else None


def refactor_doc(doc):
    from nltk.stem.wordnet import WordNetLemmatizer
    import unicodedata
    from nltk.tokenize import wordpunct_tokenize
    from nltk.corpus import stopwords
    import re

    doc = unicode(doc).lower()

    doc = ''.join(c for c in unicodedata.normalize('NFD', doc)
                              if unicodedata.category(c) != 'Mn')

    doc = re.sub('_+', '_', doc)
    doc = set(wordpunct_tokenize(doc.replace('=\n', '').lower()))
    doc = doc.difference(stopwords.words('english'))

    doc = [w for w in doc if re.search('[a-zA-Z]', w) and len(w) > 1]
    ndoc = list()

    lemmarer=WordNetLemmatizer()
    for i in range(0,len(doc)):
        lemma = lemmatize(doc[i])
        if lemma == doc[i]:
            lemma = lemmatize(doc[i],'v')
        else:
            lemma = lemma

        if lemma!=None:
            ndoc.append(lemma)
           
    return doc

    
def extract_doc_feats(refactorized_documents):
    from nltk import FreqDist
    from collections import defaultdict
    import itertools
    import math
    import pdb
    import numpy

    doc_num = len(refactorized_documents)

    occurences = defaultdict(lambda: 0)
    for doc in refactorized_documents:
        for x in set(doc): occurences[x] += 1

    ref_docs_flat = list(itertools.chain.from_iterable(refactorized_documents))
    glob_freqs = FreqDist(ref_docs_flat)

    tokens = glob_freqs.samples()
    glob_features = [{}]*doc_num


    for i in range(0, doc_num):
        doc_features = [0]*len(tokens)
        doc_freqs = FreqDist(refactorized_documents[i])
        doc_len = len(refactorized_documents[i])

        for (tok,num) in doc_freqs.items():
            max_doc_freq = doc_freqs.freq(doc_freqs.max())*float(doc_len)

            # augmented
            #tf = 0.5 + (0.5*float(num)) / float(max_doc_freq)
            tf = 1+math.log(num,10)
            idf = math.log( float(doc_num) / (float(occurences[tok])) ,10)
            tfidf = tf*idf

            indx = tokens.index(tok)
            doc_features[indx] = tfidf

        f_tmp = numpy.asarray(doc_features)
        f_tmp = f_tmp/(numpy.linalg.norm(f_tmp)+numpy.finfo(float).eps)
        glob_features[i] = f_tmp.tolist()

    glob_features = numpy.asarray(glob_features)*glob_freqs.N()
    print "Glob Freqs:", glob_freqs.N()

    return (glob_features,tokens)

def extract_doc_feats_counts(refactorized_documents):
    from nltk import FreqDist
    from collections import defaultdict
    import itertools
    import math
    import pdb
    import numpy

    doc_num = len(refactorized_documents)

    ref_docs_flat = list(itertools.chain.from_iterable(refactorized_documents))
    glob_freqs = FreqDist(ref_docs_flat)

    tokens = glob_freqs.samples()
    glob_features = [{}]*doc_num


    for i in range(0, doc_num):
        doc_features = [0]*len(tokens)
        doc_freqs = FreqDist(refactorized_documents[i])

        for (tok,freq) in doc_freqs.items():
            indx = tokens.index(tok)
            doc_features[indx] = freq

        f_tmp = numpy.asarray(doc_features)
        glob_features[i] = f_tmp.tolist()

    return (glob_features,tokens)

def word_under_tag_count(feats, tags, utags):
    import numpy
    counts = numpy.zeros((len(utags),feats.shape[1]))

    for (i,tagp) in enumerate(tags):
        for tag in tagp:
            counts[numpy.where(utags==tag),:] += feats[i,:]

    return counts