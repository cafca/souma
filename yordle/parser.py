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

    lemmarer=WordNetLemmatizer()
    for i in range(0,len(doc)):
        lemma = lemmarer.lemmatize(doc[i])
        if lemma == doc[i]:
            doc[i] = lemmarer.lemmatize(doc[i],'v')
        else:
            doc[i] = lemma
           
    return doc


def extract_doc_feats_tfidf(refactorized_documents):
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


    for i in range(0, doc_num):
        doc_features = [0]*len(tokens)
        doc_freqs = FreqDist(refactorized_documents[i])

        for (tok,freq) in doc_freqs.items():
            indx = tokens.index(tok)
            doc_features[indx] = freq*doc_freqs.N()

        f_tmp = numpy.asarray(doc_features)
        glob_features[i] = f_tmp.tolist()

    return (glob_features,tokens)