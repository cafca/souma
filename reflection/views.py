from flask import abort, flash, redirect, render_template, request, session, url_for
from web_ui import app, db, logged_in
from reflection.models import Catalogue, CatalogueQuestion
from reflection.forms import *

# reflection views
@app.route('/catalogue_overview')
def catalogue_overview():
    cs = Catalogue.query
    return render_template('reflection/view_catalogues.html', catalogues = cs)


@app.route('/catalogue/<id>/', methods=['GET'])
def catalogue(id):
    """ Display a catalogue """
    catalogue = Catalogue.query.filter(Catalogue.id == id).first_or_404()
    #author = Persona.query.filter_by(id=id)

    return render_template('reflection/show_catalogue.html', catalogue=catalogue)

@app.route('/answer_catalogue/<id>/', methods=['GET'])
def answer_catalogue(id):
    """ Display a form to answer catalogue """

    catalogue = Catalogue.query.filter(Catalogue.id == id).first_or_404()

    range_forms = {}
    text_forms={}
    
    for q in catalogue.questions:

        if q.identifier== "catalogue_range_question":
            
            new_range_form=Answer_range_question_form()

            #Choices
            range_choices=[]
            split_text_values=q.range_text_values.split(',')
            for i in range(q.start_value,q.end_value+1):
                range_choices.append([i,split_text_values[i-1]])
            new_range_form.range_value.choices = range_choices

            #add To collection
            range_forms[q.id] = new_range_form


        if q.identifier == "catalogue_text_question":
            text_forms[q.id] = Answer_text_question_form()

    for rf in range_forms.itervalues():
     if rf.validate_on_submit():
        print "Range Form Validate check"
    
    
    return render_template('reflection/answer_catalogue.html', catalogue=catalogue, range_forms = range_forms, text_forms=text_forms)