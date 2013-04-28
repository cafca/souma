from flask.ext.wtf import Form, TextField as WTFTextField, SelectField as WTFSelectField, Required, Email


class Create_persona_form(Form):
    """ Generate form for creating a persona """
    name = WTFTextField('Name', validators=[Required(), ])
    email = WTFTextField('Email (optional)', validators=[Email(), ])


class Create_star_form(Form):
    """ Generate form for creating a star """
    # Choices of the creator field need to be set before displaying the form
    # TODO: Validate creator selection
    creator = WTFSelectField('Creator', validators=[Required(), ])
    text = WTFTextField('Content', validators=[Required(), ])


class FindPeopleForm(Form):
    email = WTFTextField('Email-Address', validators=[
        Required(), Email()])


class ContactRequestForm(Form):
    recipient_id = WTFTextField('Persona ID', validators=[Required()])
    author_id = WTFSelectField('Contact as', validators=[Required()])
