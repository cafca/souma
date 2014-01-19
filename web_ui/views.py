import os
import datetime
import requests

from flask import abort, flash, json, redirect, render_template, request, session, url_for
from hashlib import sha256
from operator import itemgetter

from web_ui import app, cache, db, logged_in, attachments
from web_ui.forms import *
from web_ui.helpers import get_active_persona
from nucleus import notification_signals
from nucleus.models import Persona, Star, Planet, PicturePlanet, LinkPlanet, Group
from nucleus.vesicle import Vesicle

# Create blinker signal namespace
star_created = notification_signals.signal('star-created')
star_deleted = notification_signals.signal('star-deleted')
persona_created = notification_signals.signal('persona-created')
contact_request_sent = notification_signals.signal('contact-request-sent')
new_contact = notification_signals.signal('new-contact')
group_created = notification_signals.signal('group-created')


class PageManager():
    def __init__(self):
        self.layouts = app.config['LAYOUT_DEFINITIONS']
        self.screen_size = (12.0, 8.0)

    def auto_layout(self, stars):
        """Return a layout for given stars in a list of css class, star pairs.
        """

        # Rank stars by score
        stars_ranked = sorted(stars, key=lambda s: s.hot(), reverse=True)

        # Find best layout by filling each one with stars
        # and determining which one gives the best score
        layout_scores = dict()
        for layout in self.layouts:
            # print("\nLayout: {}".format(layout['name']))
            layout_scores[layout['name']] = 0

            for i, star_cell in enumerate(layout['stars']):
                if i >= len(stars_ranked):
                    continue
                star = stars_ranked[i]

                cell_score = self._cell_score(star_cell)
                layout_scores[layout['name']] += star.hot() * cell_score
                # print("{}\t{}\t{}".format(star, star.hot() * cell_score, cell_score))
            # print("Score: {}".format(layout_scores[layout['name']]))

        # Select best layout
        selected_layouts = sorted(
            layout_scores.iteritems(),
            key=itemgetter(1),
            reverse=True)

        if len(selected_layouts) == 0:
            app.logger.error("No fitting layout found")
            return

        for layout in self.layouts:
            if layout['name'] == selected_layouts[0][0]:
                break

        # print("Chosen {}".format(layout))

        # Create list of elements in layout
        page = list()
        for i, star_cell in enumerate(layout['stars']):
            if i >= len(stars_ranked):
                break

            star = stars_ranked[i]

            # CSS class name format
            # col   column at which the css container begins
            # row   row at which it begins
            # w     width of the container
            # h     height of the container
            css_class = "col{} row{} w{} h{}".format(
                star_cell[0],
                star_cell[1],
                star_cell[2],
                star_cell[3])
            page.append([css_class, star])
        return page

    def _cell_score(self, cell):
        """Return a score that describes how valuable a given cell on the screen is.
        Cell on the top left is 1.0, score diminishes to the right and bottom. Bigger
        cells get higher scores, cells off the screen get a 0.0"""
        import math

        # position score
        if cell[0] > self.screen_size[0] or cell[1] > self.screen_size[1]:
            pscore = 0.0
        else:
            score_x = 1.0 if cell[0] == 0 else 1.0 / (1.0 + (cell[0] / self.screen_size[0]))
            score_y = 1.0 if cell[1] == 0 else 1.0 / (1.0 + (cell[1] / self.screen_size[1]))
            pscore = (score_x + score_y) / 2.0

        # size score (sigmoid)
        area = cell[2] * cell[3]
        sscore = 1.0 / (1 + pow(math.exp(1), -0.1 * (area - 12.0)))
        return pscore * sscore


@app.context_processor
def persona_context():
    """Makes controlled_personas available in templates"""
    return dict(controlled_personas=Persona.query.filter('sign_private != ""'))


@app.before_request
def before_request():
    """Preprocess requests"""

    allowed_paths = [
        '/setup',
        '/login']

    session['active_persona'] = get_active_persona()

    if app.config['PASSWORD_HASH'] is None and request.path not in allowed_paths and request.path[1:7] != 'static':
        app.logger.info("Redirecting to Setup")
        return redirect(url_for('setup', _external=True))

    if request.path not in allowed_paths and not logged_in() and request.path[1:7] != 'static':
        app.logger.info("Redirecting to Login")
        return redirect(url_for('login', _external=True))


@app.teardown_request
def teardown_request(exception):
    """Things to do after a request"""
    pass


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Display a login form and create a session if the correct pw is submitted"""
    from Crypto.Protocol.KDF import PBKDF2

    error = None
    if request.method == 'POST':
        # TODO: Is this a good idea?
        salt = app.config['SECRET_KEY']
        pw_submitted = PBKDF2(request.form['password'], salt)

        if sha256(pw_submitted).hexdigest() != app.config['PASSWORD_HASH']:
            error = 'Invalid password'
        else:
            cache.set('password', pw_submitted, 3600)
            flash('You are now logged in')
            return redirect(url_for('universe'))
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    cache.set('password', None)
    flash('You were logged out')
    return redirect(url_for('login'))


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    from Crypto.Protocol.KDF import PBKDF2
    from hashlib import sha256

    error = None
    if request.method == 'POST':
        logged_in()
        if request.form['password'] is None:
            error = 'Please enter a password'
        else:
            salt = app.config['SECRET_KEY']
            password = PBKDF2(request.form['password'], salt)
            password_hash = sha256(password).hexdigest()

            app.config['PASSWORD_HASH'] = password_hash
            os.environ['SOUMA_PASSWORD_HASH_{}'.format(app.config['LOCAL_PORT'])] = password_hash
            cache.set('password', password, 3600)
            return redirect(url_for('universe'))
    return render_template('setup.html', error=error)


@app.route('/p/<id>/')
def persona(id):
    """ Render home view of a persona """

    persona = Persona.query.filter_by(id=id).first_or_404()
    starmap = Star.query.filter(
        Star.creator_id == id,
        Star.state >= 0,
        Star.group_id == '')[:4]

    # TODO: Use new layout system
    vizier = Vizier([
        [1, 5, 6, 2],
        [1, 1, 6, 4],
        [7, 1, 2, 2],
        [7, 3, 2, 2],
        [7, 5, 2, 2]])

    return render_template(
        'persona.html',
        layout="persona",
        vizier=vizier,
        starmap=starmap,
        persona=persona)


@app.route('/p/create', methods=['GET', 'POST'])
def create_persona():
    """ Render page for creating new persona """
    from uuid import uuid4

    form = Create_persona_form()
    if form.validate_on_submit():
        # This is a unique ID which identifies the persona across all contexts
        uuid = uuid4().hex

        # Save persona to DB
        p = Persona(
            uuid,
            request.form['name'],
            request.form['email'])

        # Create keypairs
        p.generate_keys(cache.get('password'))

        # TODO: Error message when user already exists
        db.session.add(p)
        db.session.commit()

        persona_created.send(create_persona, message=p)

        flash("New persona {} created!".format(p.username))
        return redirect(url_for('persona', id=uuid))

    return render_template(
        'create_persona.html',
        form=form,
        next=url_for('create_persona'))


@app.route('/p/<id>/activate', methods=['GET'])
def activate_persona(id):
    """ Activate a persona """
    p = Persona.query.get(id)
    if not p:
        app.logger.error("Tried to activate a nonexistent persona")
        abort(404)
    if p.sign_private == "":
        app.logger.error("Tried to activate foreign persona")
        flash("That is not you!")
    else:
        app.logger.info("Activated {}".format(p))
        session['active_persona'] = id
    return redirect(url_for('universe'))


@app.route('/s/create', methods=['GET', 'POST'])
def create_star():
    from uuid import uuid4
    """ Create a new star """

    # Load author drop down contents
    controlled_personas = Persona.query.filter(Persona.sign_private != None).all()
    creator_choices = [(p.id, p.username) for p in controlled_personas]
    active_persona = Persona.query.get(session['active_persona'])

    form = Create_star_form(default_creator=session['active_persona'])
    form.creator.choices = creator_choices
    if form.validate_on_submit():
        uuid = uuid4().hex

        new_star = Star(
            uuid,
            request.form['text'],
            request.form['creator'],
            request.form['group_id'])
        db.session.add(new_star)
        db.session.commit()

        flash('New star created!')
        app.logger.info('Created new {}'.format(new_star))

        if 'picture' in request.files and request.files['picture'].filename != "":
            # compute hash
            picture_hash = sha256(request.files['picture'].stream.read()).hexdigest()
            request.files['picture'].stream.seek(0)

            # create or get planet
            planet = Planet.query.filter_by(id=picture_hash[:32]).first()
            if not planet:
                app.logger.info("Storing submitted file")
                filename = attachments.save(request.files['picture'], folder=picture_hash[:2], name=picture_hash[2:]+".")
                planet = PicturePlanet(
                    id=picture_hash[:32],
                    filename=os.path.join(attachments.name, filename))
                db.session.add(planet)

            # attach to star
            new_star.planets.append(planet)

            # commit
            db.session.add(new_star)
            db.session.commit()
            app.logger.info("Attached {} to new {}".format(planet, new_star))

        if 'link' in request.form and request.form['link'] != "":
            link_hash = sha256(request.form['link']).hexdigest()[:32]
            planet = Planet.query.filter_by(id=link_hash).first()
            if not planet:
                app.logger.info("Storing new Link")
                planet = LinkPlanet(
                    id=link_hash,
                    url=request.form['link'])
                db.session.add(planet)

            new_star.planets.append(planet)
            db.session.add(new_star)
            db.session.commit()
            app.logger.info("Attached {} to new {}".format(planet, new_star))

        star_created.send(create_star, message=new_star)

        # if new star belongs to a group, show group page
        if new_star.group_id:
            return redirect(url_for('group', id=new_star.group_id))

        return redirect(url_for('star', id=uuid))
    return render_template('create_star.html', form=form, active_persona=active_persona)


@app.route('/s/<id>/delete', methods=["GET"])
def delete_star(id):
    """ Delete a star """
    # TODO: Should only accept POST instead of GET
    # TODO: Check permissions!

    # Load instance and creator persona
    s = Star.query.get(id)

    if s is None:
        abort(404)

    s.set_state(-2)
    db.session.add(s)
    db.session.commit()

    star_deleted.send(delete_star, message=s)

    app.logger.info("Deleted star {}".format(id))
    return redirect(url_for('debug'))


@app.route('/')
def universe():
    """ Render the landing page """
    stars = Star.query.filter(Star.state >= 0, Star.group_id == '').all()
    pm = PageManager()
    page = pm.auto_layout(stars)

    if len(persona_context()['controlled_personas'].all()) == 0:
        return redirect(url_for('create_persona'))

    if len(stars) == 0:
        return redirect(url_for('create_star'))

    return render_template('universe.html', layout="sternenhimmel", stars=page)


@app.route('/s/<id>/', methods=['GET'])
def star(id):
    """ Display a single star """
    star = Star.query.filter(Star.id==id, Star.state >= 0).first_or_404()
    creator = Persona.query.filter_by(id=id)

    return render_template('star.html', layout="star", star=star, creator=creator)


@app.route('/debug/')
def debug():
    """ Display raw data """
    stars = Star.query.all()
    personas = Persona.query.all()
    planets = Planet.query.all()
    groups = Group.query.all()

    return render_template(
        'debug.html',
        stars=stars,
        personas=personas,
        planets=planets,
        groups=groups
    )


@app.route('/find-people', methods=['GET', 'POST'])
def find_people():
    """Search for and follow people"""
    from synapse.electrical import ElectricalSynapse

    form = FindPeopleForm(request.form)
    found = None
    error = None

    if request.method == 'POST' and form.validate():
        # Compile message
        address = request.form['email']
        payload = {
            "email_hash": [sha256(address).hexdigest(), ]
        }

        # Create a temporary electrical synapse to make a synchronous glia request
        electrical = ElectricalSynapse(None)
        resp, errors = electrical.find_persona(address)

        # TODO: This should flash an error message. It doesn't.
        if errors:
            flash("Server error: {}".format(str(errors)))

        elif resp and resp['personas']:
            found = resp['personas']

            for p in found:
                if Persona.query.get(p['id']) is None:
                    app.logger.info("Storing new Persona {}".format(p['id']))
                    p_new = Persona(
                        id=p['id'],
                        username=p['username'],
                        email=address,
                        crypt_public=p['crypt_public'],
                        sign_public=p['sign_public'])
                    db.session.add(p_new)
                    db.session.commit()
        else:
            error = "No record for {}. Check the spelling!".format(address)

    return render_template('find_people.html', form=form, found=found, error=error)


@app.route('/p/<persona_id>/add_contact', methods=['GET', "POST"])
def add_contact(persona_id):
    """Add a persona to the current persona's address book"""
    form = AddContactForm(request.form)
    persona = Persona.query.get(persona_id)
    author = Persona.query.get(get_active_persona())

    if request.method == 'POST' and persona is not None:
        author.contacts.append(persona)
        db.session.add(author)
        db.session.commit()

        new_contact.send(add_contact, message={'new_contact': persona, 'author': author})

        flash("Added {} to {}'s address book".format(persona.username, author.username))
        app.logger.info("Added {} to {}'s contacts: {}".format(persona, author, author.contacts))
        return redirect(url_for('persona', id=persona.id))

    return render_template('add_contact.html', form=form, persona=persona)


@app.route('/g/<id>/', methods=['GET'])
def group(id):
    """ Render home view of a group """

    group = Group.query.filter_by(id=id).first_or_404()

    # Load author drop down contents
    controlled_personas = Persona.query.filter(Persona.sign_private != None).all()
    creator_choices = [(p.id, p.username) for p in controlled_personas]
    active_persona = Persona.query.get(session['active_persona'])

    form = Create_star_form(default_creator=session['active_persona'])
    form.creator.choices = creator_choices

    # Fill in group-id to be used in star creation
    form.group_id.data = group.id

    starmap = group.posts

    # TODO: Use new layout system
    vizier = Vizier([
        [1, 5, 6, 2],
        [1, 1, 6, 4],
        [7, 1, 2, 2],
        [7, 3, 2, 2],
        [7, 5, 2, 2]])

    return render_template(
        'group.html',
        layout="group",  # TODO: Where's that one from?! web_ui/layouts.json?
        vizier=vizier,
        group=group,
        starmap=starmap,
        active_persona=active_persona,
        form=form)


@app.route('/g/create', methods=['GET', 'POST'])
def create_group():
    """ Render page for creating new group """

    from uuid import uuid4

    form = Create_group_form()
    if form.validate_on_submit():
        # create ID to identify the group across all contexts
        uuid = uuid4().hex

        # Create group and add to DB
        g = Group(
            uuid,
            request.form['groupname'],
            request.form['description'])

        db.session.add(g)
        db.session.commit()

        group_created.send(create_group, message=g)

        flash("New group {} created!".format(g.groupname))
        return redirect(url_for('group', id=g.id))

    return render_template(
        'create_group.html',
        form=form,
        next=url_for('create_group'))
        
@app.route('/g/', methods=['GET'])
def groups():
    groups = Group.query.all()

    return render_template(
        'groups.html',
        groups=groups
    )

class Vizier():
    """Old layout system. Use Pagemanager instead"""
    def __init__(self, layout):
        from collections import defaultdict

        cells = defaultdict(list)
        for e in layout:
            x_pos = e[0]
            y_pos = e[1]
            x_size = e[2]
            y_size = e[3]

            for col in xrange(x_pos, x_pos + x_size):
                for row in xrange(y_pos, y_pos + y_size):
                    if col in cells and row in cells[col]:
                        app.logger.warning("Double binding of cell ({x},{y})".format(x=col, y=row))
                    else:
                        cells[col].append(row)

        self.layout = layout
        self.index = 0

    def get_cell(self):
        """ Return the next free cell's class name """
        if len(self.layout) <= self.index:
            app.logger.warning("Not enough layout cells provided for content.")
            return "hidden"

        class_name = "col{c} row{r} w{width} h{height}".format(
            c=self.layout[self.index][0],
            r=self.layout[self.index][1],
            width=self.layout[self.index][2],
            height=self.layout[self.index][3])

        self.index += 1
        return class_name
