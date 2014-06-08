from flask import abort, escape, flash, redirect, render_template, request, session, url_for
from web_ui import app, db, logged_in
from uuid import uuid4
import datetime
from reflection.models import *
from reflection.forms import *
from sqlalchemy import desc

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



@app.route('/activate_catalogue/<id>/', methods=['GET'])
def activate_catalogue(id):

    catalogue = Catalogue.query.filter(Catalogue.id == id).first_or_404()
    catalogue.activated = True
    db.session.commit()

    return redirect(url_for('catalogue_overview'))

@app.route('/deactivate_catalogue/<id>/', methods=['GET'])
def deactivate_catalogue(id):

    catalogue = Catalogue.query.filter(Catalogue.id == id).first_or_404()
    catalogue.activated = False
    db.session.commit()

    return redirect(url_for('catalogue_overview'))


@app.route('/start_catalogue/<id>/', methods=['GET'])
def start_catalogue(id):

    catalogue = Catalogue.query.filter(Catalogue.id == id).first_or_404()
    max_index = len(catalogue.questions)

    #find last answered question to continue with next 
    laq = CatalogueAnswer.query.join(CatalogueQuestion).join(CatalogueQuestion.catalogue).filter(Catalogue.id==catalogue.id).order_by(CatalogueAnswer.answer_time.desc()).first()
    if laq is not None:
        if laq.question.index < max_index:
            return redirect(route_to_next_question(catalogue.id, laq.question.index +1))
        else:
            return redirect(route_to_next_question(catalogue.id, 1))
    else:
        return redirect(route_to_next_question(catalogue.id, 1))


@app.route('/answer_text_question/<id>/', methods=['GET','POST'])
def answer_text_question(id):
    """ Display a form to answer catalogue """

    q = CatalogueQuestion.query.filter(CatalogueQuestion.id == id).first_or_404()

    form = Answer_text_question_form()
   
    if form.validate_on_submit():
        #import pdb; pdb.set_trace()

        run_uuid = get_run_uuid(q.catalogue_id, q.index)
      
        #neue Antwort anlegen
        answer = CatalogueTextAnswer()
        answer.id=uuid4().hex
        answer.answer_text = request.form['text']
        answer.answer_time = datetime.datetime.utcnow()
        answer.question_id = q.id
        answer.run_id = run_uuid
        db.session.add(answer)
        db.session.commit()

        #find next question
        return redirect(route_to_next_question(q.catalogue_id , q.index +1))

        #flash("New Answer created!")
        #return redirect('/catalogue_overview')
    else:
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
     
        run_uuid = get_run_uuid(q.catalogue_id, q.index)
      
        #neue Antwort anlegen
        answer = CatalogueRangeAnswer()
        answer.id=uuid4().hex
        answer.range_value = request.form['range_value']
        answer.answer_time = datetime.datetime.utcnow()
        answer.question_id = q.id
        answer.run_id = run_uuid
        db.session.add(answer)
        db.session.commit()

        #find next question
        return redirect(route_to_next_question(q.catalogue_id , q.index+1))

    else:
    
        return render_template('reflection/answer_range_question.html', question=q, form=form)


def get_run_uuid(cat_id, q_index):

    #vorgaenger Antwort finden
    if q_index == 1:
        return uuid4().hex
    else:
        prev_q= CatalogueQuestion.query.filter(CatalogueQuestion.catalogue_id == cat_id, CatalogueQuestion.index == q_index-1).first()
        if prev_q is not None:
            prev_a = CatalogueAnswer.query.filter(CatalogueAnswer.question_id==prev_q.id).order_by(CatalogueAnswer.answer_time.desc()).first()
            if prev_a is not None:
                return prev_a.run_id
                #Todo: what if he does not find the previous answer?

def route_to_next_question(cat_id, redirect_question_index):
    nex_question = CatalogueQuestion.query.filter(CatalogueQuestion.catalogue_id == cat_id,CatalogueQuestion.index == redirect_question_index).first()
    
    if nex_question is not None:
        #flash("New Answer created!")
        if nex_question.identifier == "catalogue_range_question":
            return url_for('answer_range_question', id= nex_question.id)
        if nex_question.identifier == "catalogue_text_question" :
             return url_for('answer_text_question', id= nex_question.id)
    else:
        flash("Excellent Job! Questionnaire completely answered.")
        return '/catalogue_overview'