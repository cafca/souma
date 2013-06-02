from flask.ext.wtf import Form, TextField, SelectField, Required, Email
from flask.ext.wtf import widgets


class Create_persona_form(Form):
    """ Generate form for creating a persona """
    name = TextField('Name', validators=[Required(), ])
    email = TextField('Email (optional)', validators=[Email(), ])


class Create_star_form(Form):
    """ Generate form for creating a star """
    # Choices of the creator field need to be set before displaying the form
    # TODO: Validate creator selection
    creator = SelectField('Creator', validators=[Required(), ])
    text = TextField('Content', validators=[Required(), ], widget=widgets.TextArea())


class FindPeopleForm(Form):
    email = TextField('Email-Address', validators=[
        Required(), Email()])


class AddContactForm(Form):
    recipient_id = TextField('Persona ID', validators=[Required()])
    author_id = SelectField('Contact as', validators=[Required()])
