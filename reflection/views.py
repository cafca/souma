from flask import abort, flash, redirect, render_template, request, session, url_for
from web_ui import app, db, logged_in

# reflection views
@app.route('/catalogue_overview')
def catalogues():
	return render_template('view_catalogue.html')