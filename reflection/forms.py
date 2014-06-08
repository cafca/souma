from flask.ext.wtf import Form
from wtforms.fields import TextField, TextAreaField, RadioField, HiddenField
from wtforms.validators import DataRequired, InputRequired

class Answer_range_question_form(Form):
    """ Generate form for answering a range question """
    range_value = RadioField('RangeValue', coerce=int, validators=[InputRequired(), ])
   

class Answer_text_question_form(Form):
    """ Generate form for answering a text question """
    text = TextAreaField('Text', validators=[DataRequired(), ])