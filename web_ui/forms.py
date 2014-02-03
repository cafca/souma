from flask.ext.wtf import Form, TextField, SelectField, FileField, HiddenField,\
    Required, Optional, Length, Email, widgets
from flask.ext.wtf.html5 import URLField


class Create_persona_form(Form):
    """ Generate form for creating a persona """
    name = TextField('Name', validators=[Required(), ])
    email = TextField('Email (optional)', validators=[Email(), ])


class Create_star_form(Form):
    """ Generate form for creating a star """
    # Choices of the author field need to be set before displaying the form
    # TODO: Validate author selection
    author = SelectField('Author', validators=[Required(), ])
    text = TextField('Content', validators=[Required(), ], widget=widgets.TextArea())
    picture = FileField('Picture')
    #link = URLField('Link', validators=[url()])
    link = URLField('Link')
    group_id = HiddenField('', validators=[Optional(), Length(min=32, max=32)])


class Create_group_form(Form):
    """ Generate form for creating a group """

    groupname = TextField('Group name', validators=[Required(), ])
    description = TextField('Description', validators=[Required(), ], widget=widgets.TextArea())


class FindPeopleForm(Form):
    email = TextField('Email-Address', validators=[
        Required(), Email()])


class AddContactForm(Form):
    recipient_id = TextField('Persona ID', validators=[Required()])
    author_id = SelectField('Contact as', validators=[Required()])
