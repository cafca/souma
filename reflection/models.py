from nucleus.models import Serializable, Persona, Oneup, Star, LinkPlanet
from web_ui import db, app
from uuid import uuid4
import os


class Catalogue(Serializable, db.Model):
    
    __tablename__ = "catalogue"

    id = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(100))
    description = db.Column(db.String(500))

    author_id = db.Column(db.String(32), db.ForeignKey('persona.id'))
    author = db.relationship('Persona',primaryjoin="Persona.id==Catalogue.author_id")
    
    questions = db.relationship('CatalogueQuestion',
        primaryjoin="CatalogueQuestion.catalogue_id==Catalogue.id",
        backref=db.backref('catalogue'))

    activated = db.Column(db.Boolean)

    def __repr__(self):
        return "ID: {}, Name: {}".format(self.id,self.name)

    @staticmethod
    def readFromCSV():

        catalogue_obj = Catalogue()
        range_start = 0;
        range_end = 0;
        range_values = ""
        results = False
        resultEndLine=0

        import csv
        with open(os.path.join(app.config["USER_DATA"], "eggs.csv"), 'rb') as csvfile:
            spamreader = csv.reader(csvfile, delimiter=',', quotechar='"')
            for line, row in enumerate(spamreader):
                if line <= 4:
                    if line == 0:
                        catalogue_obj.id = uuid4().hex
                        catalogue_obj.name = row[1]
                    if line == 1:
                        catalogue_obj.description = row[1].decode('utf-8')
                        db.session.add(catalogue_obj)
                        #db.session.commit()
                    if line == 2:
                        range_start = row[1]
                    if line == 3:
                        range_end = row[1]
                    if line == 4:
                        range_values = row[1].decode('utf-8')

                if line >= 6:
                    if row[0] == "" and row[1] == "":
                        results= True
                        resultEndLine = line 
                if results and line > resultEndLine:
                        question = CatalogueRangeQuestion(range_start, range_end, range_values)
                        question.id = uuid4().hex
                        question.index = row[0]
                        question.question_text = row[1].decode('utf-8')
                        #print catalogue_obj.id
                        question.catalogue_id = catalogue_obj.id
                        db.session.add(question)
                        #db.session.commit()
                        #print question


            print catalogue_obj
            db.session.commit()         
            #print row[0]
            #print ', '.join(row)
        

class CatalogueQuestion(Serializable, db.Model):

    __tablename__ ="catalogue_question"
    id = db.Column(db.String(32), primary_key=True)
    question_text=db.Column(db.Text)
    index = db.Column(db.Integer)

    catalogue_id = db.Column(db.String(32), db.ForeignKey('catalogue.id'))
    answers = db.relationship('CatalogueAnswer',
        primaryjoin="CatalogueAnswer.question_id==CatalogueQuestion.id",
        backref=db.backref('question'))


    identifier = db.Column(db.String(50))

    def __init__(self,identifier):
        self.type=identifier

    __mapper_args__ = {
        'polymorphic_identity':'catalogue_question',
        'polymorphic_on': identifier
    }


class CatalogueRangeQuestion(CatalogueQuestion):

    __tablename__ ="catalogue_range_question"

    id = db.Column(db.String, db.ForeignKey('catalogue_question.id'), primary_key=True)

    start_value = db.Column(db.Integer)
    end_value = db.Column(db.Integer)

    range_text_values=db.Column(db.String)

    def __init__(self, start_value, end_value, rangetextv):
        CatalogueQuestion.__init__(self,type)
        self.start_value = start_value
        self.end_value = end_value
        self.range_text_values = rangetextv

    def __repr__(self):
        return "Index: {}, Start: {}, End: {}".format(self.index,self.start_value,self.end_value)

    __mapper_args__ = {
        'polymorphic_identity':'catalogue_range_question'
    }


class CatalogueTextQuestion(CatalogueQuestion):

    __tablename__ ="catalogue_text_question"
    id = db.Column(db.String, db.ForeignKey('catalogue_question.id'), primary_key=True)

    requires_short_answer=db.Column(db.Boolean)

    def __init__(self, requires_short_answer):
        self.requires_short_answer=requires_short_answer

    __mapper_args__ = {
        'polymorphic_identity':'catalogue_text_question'
    }


class CatalogueAnswer(Serializable, db.Model):

    __tablename__ ="catalogue_answer"
    id = db.Column(db.String(32), primary_key=True)

    answer_time=db.Column(db.DateTime)

    question_id = db.Column(db.String(32), db.ForeignKey('catalogue_question.id'))
    

    type = db.Column(db.String(50))

    def __init__(self,type):
        self.type=type

    __mapper_args__ = {
        'polymorphic_identity':'catalogue_answer',
        'polymorphic_on':type
    }

class CatalogueRangeAnswer(CatalogueAnswer):

    __tablename__ ="catalogue_range_answer"
    id = db.Column(db.String, db.ForeignKey('catalogue_answer.id'), primary_key=True)

    range_value= db.Column(db.Integer)

    __mapper_args__ = {
        'polymorphic_identity':'catalogue_range_answer'
    }


""" We need a connection to question type as -requires short answer- is otherwise obsolete """
class CatalogueTextAnswer(CatalogueAnswer):

    __tablename__ ="catalogue_text_answer"
    id = db.Column(db.String, db.ForeignKey('catalogue_answer.id'), primary_key=True)

    answer_text= db.Column(db.Text)

    __mapper_args__ = {
        'polymorphic_identity':'catalogue_text_answer'
    }


