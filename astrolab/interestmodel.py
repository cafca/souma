from astrolab import topic_model
from web_ui import db, app
from nucleus.models import Persona, Oneup, Star, LinkPlanet
from sklearn.naive_bayes import GaussianNB
from helpers import get_site_content
from datetime import datetime


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
        topics = topic_model.get_topics_text(text)
        interesting = self.classifier.predict(topics)
        return interesting


def update():
    app.logger.info("Test1")
    for persona in Persona.query.all():
        interestmodel = InterestModel.query.filter_by(persona_id=persona.id).first()

        if interestmodel is None:
            interestmodel = InterestModel(persona.id)

        fit(interestmodel)


def fit(interestmodel):
    app.logger.info("Fitting")
    train_set = list()
    for oneup in Oneup.query.filter_by(creator_id=interestmodel.persona_id):
        star = Star.query.get(oneup.star_id)

        for planet in star.planets:
            if isinstance(planet, LinkPlanet):
                link = planet.url
                link_content = get_site_content(link)
                topics = topic_model.get_topics_text(link_content)
                train_set.append(topics)

        topics = topic_model.get_topics_text(star.text)
        train_set.append(topics)

    if len(train_set) > 0:
        train_labels = [[1] * len(train_set)]
        interestmodel.classifier.fit(train_set, train_labels)
    interestmodel.last_fit = datetime.now()
    app.logger.info("Finished")
