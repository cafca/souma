import os
import datetime

from flask import abort, flash, redirect, render_template, request, session, url_for, jsonify as json_response
from hashlib import sha256

from web_ui import app, cache, db, logged_in, attachments
from web_ui import pagemanager
from web_ui.forms import *
from web_ui.helpers import get_active_persona
from nucleus import notification_signals, PersonaNotFoundError
from nucleus.models import Persona, Star, Planet, PicturePlanet, LinkPlanet, Group, Starmap

# Create blinker signal namespace
local_model_changed = notification_signals.signal('local-model-changed')
contact_request_sent = notification_signals.signal('contact-request-sent')
new_contact = notification_signals.signal('new-contact')
group_created = notification_signals.signal('group-created')

pagemanager = pagemanager.PageManager()

@app.context_processor
def persona_context():
    """Makes controlled_personas available in templates"""
    return dict(
        controlled_personas=Persona.list_controlled(),
        active_persona=Persona.query.get(get_active_persona())
    )


@app.before_request
def before_request():
    """Preprocess requests"""

    session['active_persona'] = get_active_persona()

    def pass_thru(path):
        """Return True if no auth required for path"""
        allowed_paths = [
            '/setup',
            '/login'
        ]
        return path in allowed_paths or request.path[1:7] == 'static'

    if not pass_thru(request.path) and not logged_in():
        app.logger.info("Not logged in: Redirecting to Login")
        return redirect(url_for('login', _external=True))


@app.teardown_request
def teardown_request(exception):
    """Things to do after a request"""
    pass


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Display a login form and create a session if the correct pw is submitted. Redirect to /setup if no pw hash."""
    from Crypto.Protocol.KDF import PBKDF2

    try:
        with open(app.config["PASSWORD_HASH_FILE"], "r") as f:
            password_hash = f.read()
    except IOError:
        app.logger.info("No password hash found: Redirecting to Setup")
        return redirect(url_for('setup', _external=True))

    error = None
    if request.method == 'POST':
        # TODO: Is this a good idea?
        salt = app.config['SECRET_KEY']
        pw_submitted = PBKDF2(request.form['password'], salt)

        if sha256(pw_submitted).hexdigest() != password_hash:
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

            with open(app.config["PASSWORD_HASH_FILE"], "w") as f:
                f.write(password_hash)

            cache.set('password', password, 3600)
            return redirect(url_for('universe'))
    return render_template('setup.html', error=error)


@app.route('/p/<id>/')
def persona(id):
    """ Render home view of a persona """

    persona = Persona.query.filter_by(id=id).first_or_404()
    if hasattr(persona, "profile"):
        stars = persona.profile.index
    else:
        stars = []

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
        stars=stars,
        persona=persona)


@app.route('/p/create', methods=['GET', 'POST'])
def create_persona():
    """ Render page for creating new persona """
    from uuid import uuid4

    form = Create_persona_form()
    if form.validate_on_submit():
        # This is a unique ID which identifies the persona across all contexts
        uuid = uuid4().hex
        created_dt = datetime.datetime.utcnow()

        # Save persona to DB
        p = Persona(
            id=uuid,
            username=request.form['name'],
            email=request.form['email'],
            modified=created_dt,
        )

        # Create keypairs
        p.generate_keys(cache.get('password'))

        # TODO: Error message when user already exists
        db.session.add(p)
        db.session.commit()

        p.profile = Starmap(
            id=uuid4().hex,
            author=p,
            kind="persona_profile",
            modified=created_dt
        )
        db.session.add(p.profile)

        p.index = Starmap(
            id=uuid4().hex,
            author=p,
            kind="index",
            modified=created_dt
        )
        db.session.add(p.index)
        db.session.commit()

        local_model_changed.send(create_persona, message={
            "author_id": p.id,
            "action": "insert",
            "object_id": p.id,
            "object_type": "Persona",
        })

        local_model_changed.send(create_persona, message={
            "author_id": p.id,
            "action": "insert",
            "object_id": p.profile.id,
            "object_type": "Starmap",
        })

        local_model_changed.send(create_persona, message={
            "author_id": p.id,
            "action": "insert",
            "object_id": p.index.id,
            "object_type": "Starmap",
        })

        # Activate new Persona
        session["active_persona"] = p.id

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

    form = Create_star_form(default_author=get_active_persona())
    form.author.choices = [(p.id, p.username) for p in Persona.list_controlled()]
    form.author.data = get_active_persona()

    # Default is posting to author profile
    if form.context.data is None:
        form.context.data = Persona.query.get(form.author.data).profile.id

    if form.validate_on_submit():
        uuid = uuid4().hex

        author = Persona.query.get(request.form["author"])
        if not author.controlled():
            app.logger.error("Can't create Star with foreign Persona {}".format(author))
            flash("Can't create Star with foreign Persona {}".format(author))
            return redirect(url_for('create_star')), 401

        new_star_created = datetime.datetime.utcnow()
        new_star = Star(
            id=uuid,
            text=request.form['text'],
            author=author,
            created=new_star_created,
            modified=new_star_created
        )
        db.session.add(new_star)
        db.session.commit()

        flash('New star created!')
        app.logger.info('Created new {}'.format(new_star))
        model_change_messages = list()

        if 'picture' in request.files and request.files['picture'].filename != "":
            # compute hash
            picture_hash = sha256(request.files['picture'].stream.read()).hexdigest()
            request.files['picture'].stream.seek(0)

            # create or get planet
            planet = Planet.query.filter_by(id=picture_hash[:32]).first()
            if not planet:
                app.logger.info("Creating new planet for submitted file")
                filename = attachments.save(request.files['picture'],
                    folder=picture_hash[:2], name=picture_hash[2:] + ".")
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

        model_change_messages.append({
            "author_id": new_star.author.id,
            "action": "insert",
            "object_id": new_star.id,
            "object_type": "Star",
        })

        # Add new Star to a Starmap depending on context
        starmap = Starmap.query.get(request.form["context"])
        if starmap is not None:
            starmap.index.append(new_star)
            starmap.modified = new_star_created
            db.session.add(starmap)

            model_change_messages.append({
                "author_id": new_star.author.id,
                "action": "update",
                "object_id": starmap.id,
                "object_type": "Starmap"
            })

        db.session.commit()

        # db.session.expunge_all()  # Remove everything from session before sending signal
        for m in model_change_messages:
            local_model_changed.send(create_star, message=m)

        # if new star belongs to a group, show group page
        if starmap is None:
            return redirect(url_for('star', id=uuid))
        else:
            return redirect(starmap.get_absolute_url())

    page = pagemanager.create_star_layout()

    return render_template('create_star.html',
                           form=form,
                           page=page)


@app.route('/s/<id>/delete', methods=["GET"])
def delete_star(id):
    """ Delete a star """
    # TODO: Should only accept POST instead of GET

    # Load instance and author persona
    s = Star.query.get(id)
    if s is None:
        abort(404)

    if not s.author.controlled():
        flash("You are not allowed to delete {}'s Stars".format(s.author))
        app.logger.error("Tried to delete one of {}'s Stars".format(s.author))
        return redirect(request.referrer)
    else:
        s.set_state(-2)
        try:
            db.session.add(s)
            db.session.commit()
        except:
            app.logger.info("Error deleting {}".format(s))
            db.session.rollback()
        else:
            message_delete = {
                "author_id": s.author.id,
                "action": "delete",
                "object_id": s.id,
                "object_type": "Star",
            }

            local_model_changed.send(delete_star, message=message_delete)

            app.logger.info("Deleted star {}".format(id))
        return redirect(url_for('debug'))


@app.route('/')
def universe():
    """ Render the landing page """
    # return only stars that are not in a group context
    stars = Star.query.filter(Star.state >= 0).all()
    page = pagemanager.star_layout(stars)

    if len(persona_context()['controlled_personas'].all()) == 0:
        return redirect(url_for('create_persona'))

    if len(stars) == 0:
        return redirect(url_for('create_star'))

    return render_template('universe.html', page=page)


@app.route('/s/<id>/', methods=['GET'])
def star(id):
    """ Display a single star """
    star = Star.query.filter(Star.id == id, Star.state >= 0).first_or_404()
    author = Persona.query.filter_by(id=id)

    return render_template('star.html', layout="star", star=star, author=author)


@app.route('/s/<star_id>/1up', methods=['POST'])
def oneup(star_id):
    """
    Issue a 1up to a Star using the currently activated Persona

    Args:
        star_id (string): ID of the Star
    """
    star = Star.query.get_or_404(star_id)
    try:
        oneup = star.toggle_oneup()
    except PersonaNotFoundError:
        error_message = "Please activate a Persona for upvoting"
        oneup = None

    resp = dict()
    if oneup is None:
        resp = {
            "meta": {
                "oneup_count": star.oneup_count(),
                "error_message": error_message
            }
        }
    else:
        resp = {
            "meta": {
                "oneup_count": star.oneup_count(),
            },
            "oneups": [{
                "id": oneup.id,
                "author": oneup.author.id,
                "state_value": oneup.state,
                "state_name": oneup.get_state()
            }]
        }
    return json_response(resp)


@app.route('/debug/')
def debug():
    """ Display raw data """
    stars = Star.query.all()
    personas = Persona.query.all()
    planets = Planet.query.all()
    groups = Group.query.all()
    starmaps = Starmap.query.all()

    return render_template(
        'debug.html',
        stars=stars,
        personas=personas,
        planets=planets,
        groups=groups,
        starmaps=starmaps
    )


@app.route('/find-people', methods=['GET', 'POST'])
def find_people():
    """Search for and follow people"""
    from synapse.electrical import ElectricalSynapse

    form = FindPeopleForm(request.form)
    error = found = None
    found_processed = list()
    found_new = list()

    if request.method == 'POST' and form.validate():
        # Compile message
        address = request.form['email']

        # Create a temporary electrical synapse to make a synchronous glia request
        electrical = ElectricalSynapse(None)
        resp, errors = electrical.find_persona(address)

        # TODO: This should flash an error message. It doesn't.
        if errors:
            flash("Server error: {}".format(str(errors)))

        elif resp and resp['personas']:
            found = resp['personas']
            active_persona = Persona.query.get(get_active_persona())

            for p in found:
                p_local = Persona.query.get(p['id'])
                if p_local is None:
                    import iso8601
                    app.logger.info("Storing new Persona {}".format(p['id']))

                    modified = iso8601.parse_date(p["modified"]).replace(tzinfo=None)

                    p_new = Persona(
                        id=p['id'],
                        username=p['username'],
                        modified=modified,
                        email=address,
                        crypt_public=p['crypt_public'],
                        sign_public=p['sign_public']
                    )
                    p_new._stub = True
                    found_new.append(p_new)
                    found_processed.append({
                        "id": p["id"],
                        "username": p["username"],
                        "incoming": None,
                        "outgoing": None
                    })
                else:
                    found_processed.append({
                        "id": p["id"],
                        "username": p["username"],
                        "incoming": (active_persona in p_local.contacts),
                        "outgoing": (p_local in active_persona.contacts)
                    })

            try:
                for p in found_new:
                    db.session.add(p)
                db.session.commit()
            except:
                db.session.rollback()
        else:
            error = "No record for {}. Check the spelling!".format(address)

    return render_template('find_people.html', form=form, found=found_processed, error=error)


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

        app.logger.info("Now sharing {}'s posts with {}".format(author, persona))

        local_model_changed.send(add_contact, message={
            "author_id": author.id,
            "action": "update",
            "object_id": author.id,
            "object_type": "Persona"
        })

        new_contact.send(add_contact, message={
            'new_contact_id': persona.id,
            'author_id': author.id
        })

        flash("Now sharing {}'s posts with {}".format(author, persona))
        return redirect(url_for('persona', id=persona.id))

    return render_template('add_contact.html', form=form, persona=persona)


@app.route('/g/<id>/', methods=['GET'])
def group(id):
    """ Render home view of a group """

    group = Group.query.filter_by(id=id).first_or_404()

    form = Create_star_form(default_author=get_active_persona())
    form.author.choices = [(p.id, p.username) for p in Persona.list_controlled()]

    # Fill in group-id to be used in star creation
    form.context.data = group.profile.id

    # create layouted page for group
    page = pagemanager.group_layout(group.profile.index.filter(Star.state >= 0))

    return render_template(
        'group.html',
        group=group,
        page=page,
        form=form)


@app.route('/g/create', methods=['GET', 'POST'])
def create_group():
    """ Render page for creating new group """

    from uuid import uuid4

    form = Create_group_form()
    form.author.choices = [(p.id, p.username) for p in Persona.list_controlled()]
    form.author.data = get_active_persona()

    if form.validate_on_submit():
        # create ID to identify the group across all contexts
        uuid = uuid4().hex
        created_dt = datetime.datetime.utcnow()

        author = Persona.query.get(request.form["author"])
        if not author.controlled():
            app.logger.error("Can't create Group with foreign Persona {}".format(author))
            flash("Can't create Group with foreign Persona {}".format(author))
            return redirect(url_for('create_group')), 401

        # Create group and add to DB
        g = Group(
            id=uuid,
            author=author,
            modified=created_dt,
            groupname=request.form['groupname'],
            description=request.form['description']
        )

        db.session.add(g)
        db.session.commit()

        index = Starmap(
            id=uuid4().hex,
            author=author,
            kind="group_profile",
            modified=created_dt
        )
        g.profile = index
        db.session.add(index)
        db.session.commit()

        flash("New group {} created!".format(g.groupname))
        app.logger.info("Created {} with {}".format(g, g.profile))

        local_model_changed.send(create_group, message={
            "author_id": author.id,
            "action": "insert",
            "object_id": g.id,
            "object_type": "Group",
        })

        local_model_changed.send(create_group, message={
            "author_id": author.id,
            "action": "insert",
            "object_id": g.profile.id,
            "object_type": "Starmap",
        })

        return redirect(url_for('group', id=g.id))

    page = pagemanager.create_group_layout()
    return render_template(
        'create_group.html',
        form=form,
        page=page,
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
