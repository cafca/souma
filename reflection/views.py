from flask import abort, flash, redirect, render_template, request, session, url_for
from web_ui import app, db, logged_in
from reflection.models import Catalogue

# reflection views
@app.route('/catalogue_overview')
def catalogue_overview():
	cs = Catalogue.query
	return render_template('reflection/view_catalogue.html', catalogues = cs)