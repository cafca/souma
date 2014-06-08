from flask import abort, flash, redirect, render_template, request, session, url_for
from web_ui import app, db, logged_in
from reflection.models import Catalogue

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

    return render_template('show_catalogue.html', catalogue=catalogue)