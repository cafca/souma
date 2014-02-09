from flask.ext.wtf import Form
from wtforms.fields import TextField, TextAreaField, SelectField, FileField, HiddenField
from wtforms.fields.html5 import URLField
from wtforms.validators import DataRequired, Email


class Create_persona_form(Form):
    """ Generate form for creating a persona """
    name = TextField('Name', validators=[DataRequired(), ])
    email = TextField('Email (optional)', validators=[Email(), ])


class Create_star_form(Form):
    """ Generate form for creating a star """
    # Choices of the author field need to be set before displaying the form
    # TODO: Validate author selection
    author = SelectField('Author', validators=[DataRequired(), ])
    text = TextAreaField('Content', validators=[DataRequired(), ])
    picture = FileField('Picture')
    #link = URLField('Link', validators=[url()])
    link = URLField('Link')
    context = HiddenField('Context', validators=[])


class Create_group_form(Form):
    """ Generate form for creating a group """

    author = HiddenField('Author', validators=[DataRequired(), ])
    groupname = TextField('Group name', validators=[DataRequired(), ])
    description = TextAreaField('Description', validators=[DataRequired(), ])


class FindPeopleForm(Form):
    email = TextField('Email-Address', validators=[
        DataRequired(), Email()])


class AddContactForm(Form):
    recipient_id = TextField('Persona ID', validators=[DataRequired()])
    author_id = SelectField('Contact as', validators=[DataRequired()])
