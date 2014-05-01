from datetime import datetime

from sklearn.naive_bayes import GaussianNB

from astrolab import logger
from astrolab.helpers import get_site_content
from astrolab.topicmodel import TopicModel
from nucleus.models import Persona, Oneup, Star, LinkPlanet
from web_ui import db, app


class InterestModel(db.Model):

    __tablename__ = "interestmodel"
    id = db.Column(db.String(32), primary_key=True)
    persona_id = db.Column(db.String(32), db.ForeignKey('persona.id'))
    persona = db.relationship("Persona",
                              backref=db.backref('interestmodel'),
                              primaryjoin="Persona.id==InterestModel.persona_id")
    classifier = db.Column(db.PickleType())
    last_fit = db.Column(db.DateTime)
    last_prediction = db.Column(db.DateTime)

    def __init__(self, persona_id):
        self.persona_id = persona_id
        self.classifier = GaussianNB()

        self.last_fit = datetime.now()
        self.last_prediction = 0

    def is_interesting(self, text):
        topics = TopicModel.get_topics_text(text)
        interesting = self.classifier.predict(topics)
        return interesting


def update():
    logger.info("Updating interest model")

    topic_model = TopicModel(
        app.config["ASTROLAB_MODEL"], app.config["ASTROLAB_MODEL_IDS"])

    for persona in Persona.query.filter_by(_stub=False).all():
        interestmodel = InterestModel.query.filter_by(persona_id=persona.id).first()

        if interestmodel is None:
            interestmodel = InterestModel(persona.id)

        fit(interestmodel, topic_model)

    del topic_model
    logger.info("Update finished")


def fit(interestmodel, topic_model):
    train_set_pos = []
    train_set_neg = []
    for star in Star.query.filter_by(state=0, kind='star'):
        like = star.author_id == interestmodel.persona_id
        if not like:
            like = Oneup.query.filter(
                Oneup.state >= 0).filter_by(parent_id=star.id, author_id=interestmodel.persona_id).all()


        content = star.text
        for planet_assoc in star.planet_assocs:
            planet = planet_assoc.planet
            if isinstance(planet, LinkPlanet):
                link = planet.url
                link_content = get_site_content(link)
                content += ' ' + link_content

        topics = topic_model.get_topics_text(content)

        if like:
            train_set_pos.append(topics)
        else:
            train_set_neg.append(topics)

    logger.info("Fitting persona %s" % interestmodel.persona_id)
    logger.info("Positive: %d    Negative: %d" % (len(train_set_pos), len(train_set_neg)))
    if len(train_set_pos) > 0:
        train_labels = [1 for x in range(len(train_set_pos))]
        train_set = train_set_pos

        if len(train_set_neg) > 0:
            train_set.extend(train_set_neg)
            train_labels.extend([0 for x in range(len(train_set_neg))])

        interestmodel.classifier.fit(train_set, train_labels)

    interestmodel.last_fit = datetime.now()
