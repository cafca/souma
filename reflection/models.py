from nucleus.models import Persona, Oneup, Star, LinkPlanet
from web_ui import db, app


class ReflectionCatalogue(Serializable, db.Model):
    
    __tablename__ = "reflection_catalogue"

    id = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(100))
    description = db.Column(db.String(500))

    author = db.relationship(
        'Persona',
        primaryjoin="Persona.id==ReflectionCatalogue.author_id")

    author_id = db.Column(db.String(32), db.ForeignKey('persona.id'))

    activated = db.Column(db.Boolean)

	def __init__(self, id, name, description, author, activated):
        
        self.id = id
        self.name= name
        self.description=description
        self.activated = activated  

        #äh??? Typsicherheit und so?!
        #define a team pattern: give the instance or the id?
        if not isinstance(author, Persona):
            self.author_id = author
        else:
            self.author_id = author.id


    def readFromCSV():
    	import csv
		with open('eggs.csv', 'rb') as csvfile:
    		spamreader = csv.reader(csvfile, delimiter=' ', quotechar='|')
     		for row in spamreader:
              print ', '.join(row)
    	

class ReflectionCatalogueQuestion(Serializable, db.Model):

	__tablename__ ="reflection_catalogue_question"
	id = db.Column(db.String(32), primary_key=True)
	question_text=db.Column(db.Text)

	catalogue_id = db.Column(db.Integer, db.ForeignKey('catalogue.id'))
    catalogue = db.relationship('ReflectionCatalogue',
        backref=db.backref('questions'))


	type = Column(String(50))

	def __init__(self,type):
		self.type=type

    __mapper_args__ = {
        'polymorphic_identity':'reflection_catalogue_question',
        'polymorphic_on':type
    }


class ReflectionCatalogueRangeQuestion(ReflectionCatalogueQuestion):

	__tablename__ ="reflection_catalogue_range_question"

	id = Column(String, ForeignKey('reflection_catalogue_question.id'), primary_key=True)

	start_value = db.Column(db.Integer)
	end_value = db.Column(db.Integer)
	

	def __init__(self, start_value, end_value):
		self.start_value=start_value
		self.end_value=end_value

	def __init__(self):
		#standardwerte:
		self.start_value=0
		self.end_value=1

	__mapper_args__ = {
        'polymorphic_identity':'reflection_catalogue_range_question'
    }


class ReflectionCataloqueTextQuestion(ReflectionCatalogueQuestion):

	__tablename__ ="reflection_catalogue_text_question"
	id = Column(String, ForeignKey('reflection_catalogue_question.id'), primary_key=True)

	requires_short_answer=db.Column(db.Boolean)

	def __init__(self, requires_short_answer):
		self.requires_short_answer=requires_short_answer

	__mapper_args__ = {
        'polymorphic_identity':'reflection_catalogue_text_question'
    }


class ReflectionCatalogueAnswer(Serializable, db.Model):

	__tablename__ ="reflection_catalogue_answer"
	id = db.Column(db.String(32), primary_key=True)

	answer_time=db.Column(db.DateTime)

	question_id = db.Column(db.Integer, db.ForeignKey('question.id'))
    question = db.relationship('ReflectionCatalogueQuestion',
        backref=db.backref('answers', lazy='dynamic'))


	type = Column(String(50))

	def __init__(self,type):
		self.type=type

    __mapper_args__ = {
        'polymorphic_identity':'reflection_catalogue_answer',
        'polymorphic_on':type
    }

class ReflectionCatalogueRangeAnswer(ReflectionCatalogueAnswer):

	__tablename__ ="reflection_catalogue_range_answer"
	id = Column(String, ForeignKey('reflection_catalogue_answer.id'), primary_key=True)

	range_value= db.Column(db.Integer)

	__mapper_args__ = {
        'polymorphic_identity':'reflection_catalogue_range_answer'
    }


""" We need a connection to question type as -requires short answer- is otherwise obsolete """
class ReflectionCatalogueTextAnswer(ReflectionCatalogueAnswer):

	__tablename__ ="reflection_catalogue_text_answer"
	id = Column(String, ForeignKey('reflection_catalogue_answer.id'), primary_key=True)

	answer_text= db.Column(db.Text)

	__mapper_args__ = {
        'polymorphic_identity':'reflection_catalogue_text_answer'
    }


