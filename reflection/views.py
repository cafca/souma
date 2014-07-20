from flask import abort, escape, flash, redirect, render_template, request, session, url_for
from web_ui import app, db, logged_in
from uuid import uuid4
import datetime
from reflection.models import *
from reflection.forms import *
from sqlalchemy import desc
import json

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

    percentage = get_progress_bar_percent(q.catalogue_id, q.index)
   
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
        return render_template('reflection/answer_text_question.html', question=q, form=form, percentage=percentage)


@app.route('/answer_range_question/<id>/', methods=['GET','POST'])
def answer_range_question(id):
    """ Display a form to answer catalogue """

    q = CatalogueQuestion.query.filter(CatalogueQuestion.id == id).first_or_404()
      
    form=Answer_range_question_form()
    percentage = get_progress_bar_percent(q.catalogue_id, q.index)
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
    
        return render_template('reflection/answer_range_question.html', question=q, form=form, percentage=percentage)


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


def get_progress_bar_percent(cat_id, question_index):
    nex_question = CatalogueQuestion.query.filter(CatalogueQuestion.catalogue_id == cat_id,CatalogueQuestion.index == question_index).first()  
    max_index = len(nex_question.catalogue.questions)
    return round(100 * float(question_index)/float(max_index+1),2)

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

@app.route('/show_catalogue_answers/<id>/<index>', methods=['GET'])
def show_catalouge_answers(id, index):


    offset_index = int(index)
    catalogue_answers = None

    prev_index = offset_index -1
    next_index = offset_index +1

    # correct if first or last item
    max_runs = CatalogueAnswer.query.join(CatalogueQuestion).join(CatalogueQuestion.catalogue).filter(Catalogue.id==id).group_by(CatalogueAnswer.run_id).order_by(CatalogueAnswer.answer_time.desc()).count()

    if offset_index == 0:
        prev_index = -1
    if offset_index == max_runs -1:
        next_index = -1

        
    catalogue_answer_run_id  = CatalogueAnswer.query.join(CatalogueQuestion).join(CatalogueQuestion.catalogue).filter(Catalogue.id==id).group_by(CatalogueAnswer.run_id).order_by(CatalogueAnswer.answer_time.desc()).offset(offset_index).first()
    if catalogue_answer_run_id is not None:
        catalogue_answers = CatalogueAnswer.query.filter(CatalogueAnswer.run_id==catalogue_answer_run_id.run_id).all()
    else:
        catalogue_answers = CatalogueAnswer.query.join(CatalogueQuestion).join(CatalogueQuestion.catalogue).filter(Catalogue.id==id).all()

    #import pdb; pdb.set_trace()
    # if index > len(catalogue_answers)-1:
    #     #Ende erreicht
    #     return 404
    # else:
    return render_template('reflection/show_catalogue_answers.html', answers = catalogue_answers, cat_id=id, prev_index=prev_index, next_index=next_index)

@app.route('/show_graph', methods=['GET'])
def show_graph():

    short_moods = CatalogueAnswer.query.join(CatalogueQuestion).join(Catalogue).filter(Catalogue.system_name=="ShortMood", CatalogueAnswer.identifier=="catalogue_range_answer").all()
    if short_moods is not None:

        question = short_moods[0].question
        graph_title = question.catalogue.name
        yAxis_title = question.question_text



        x_data_list = []
        data_list = []

        range_value_texts = question.range_text_values.split(',')
        plot_band_string = '['

        for range_index in range(0, len(range_value_texts)):
            range_text_dict=dict()
            range_text_dict["from"]=range_index+1
            range_text_dict["to"]=range_index+2
            if range_index % 2 == 0:
                range_text_dict["color"]="#fff"
            else:
                range_text_dict["color"]="#f1f1f1"
            range_text_dict["label"]={"text": str(range_value_texts[range_index]), "style": {"color":'#606060'}}

            plot_band_string += json.dumps(range_text_dict) + ','

        plot_band_string += ']'

            # { // Light air
            #             from: 0.3,
            #             to: 1.5,
            #             color: 'rgba(68, 170, 213, 0.1)',
            #             label: {
            #                 text: 'Light air',
            #                 style: {
            #                     color: '#606060'
            #                 }
            #             }
            

        for a in short_moods:
             data_list.append(a.range_value)
             x_data_list.append(a.answer_time.strftime('%m-%d'))

        start_date_year=short_moods[0].answer_time.strftime('%Y')
        start_date_month=short_moods[0].answer_time.strftime('%m')
        start_date_day=short_moods[0].answer_time.strftime('%d')

        data_dict = {}
        data_dict["data"] = data_list
        data_dict["pointInterval"] = 24*3600*1000
        #data_dict["pointStart"]=start_date
        data_dict["name"] = yAxis_title
        
        
        json_string = json.dumps(data_dict)
        final_string='[' +json_string + ']'
                    
        #import pdb; pdb.set_trace()

        return render_template('reflection/show_diagramm.html', graph_title=graph_title, yAxis_title=yAxis_title, series=final_string, x_values=x_data_list, plot_band_values=plot_band_string, start_date_y=start_date_year, start_date_m=start_date_month, start_date_d=start_date_day)

    else:
        return 404

   