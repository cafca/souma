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

@app.route('/answer_text_question/<id>/', methods=['GET','POST'])
def answer_text_question(id):
    """ Display a form to answer catalogue """

    q = CatalogueQuestion.query.filter(CatalogueQuestion.id == id).first_or_404()

    form = Answer_text_question_form()

   
    if form.validate_on_submit():
        import pdb; pdb.set_trace()
        return redirect('/catalogue_overview')
    
    
    return render_template('reflection/answer_text_question.html', question=q, form=form)


@app.route('/answer_range_question/<id>/', methods=['GET','POST'])
def answer_range_question(id):
    """ Display a form to answer catalogue """

    q = CatalogueQuestion.query.filter(CatalogueQuestion.id == id).first_or_404()
      
    form=Answer_range_question_form()

    #Choices
    range_choices=[]
    split_text_values=q.range_text_values.split(',')
    for i in range(q.start_value,q.end_value+1):
        range_choices.append([i,split_text_values[i-1]])
    form.range_value.choices = range_choices

    
    if form.validate_on_submit():
      #import pdb; pdb.set_trace()
      flash("New Answer created!")
      return redirect('/catalogue_overview')
    
    
    return render_template('reflection/answer_range_question.html', question=q, form=form)