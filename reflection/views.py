# reflection views
@app.route('/catalogues')
def catalogues()
	return render_template('view_catalogue.html')