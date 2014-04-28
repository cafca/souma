from operator import itemgetter
from web_ui import app

from flask.ext.sqlalchemy import Pagination


class PageManager(object):
    """ Holds all factory methods for Page creation.
    Those methods read in possible layouts, and create
    and a Page instance arrangeing content in the most
    beneficial way. Also see Page class below.
    """

    def __init__(self):
        """ Initializes screen size and  loads all layouts
        for the right context, using the context defined in
        the concrete subclass.
        """

        # Dimension of layout in cells
        self.screen_size = (12.0, 8.0)

        # Number of items on one page
        # Flask-SQLAlchemy pagination requires this to be static, i.e.
        # it is not possible to have different number of items on consecutive
        # pages. If we need that, we will have to implement our own pagination.
        self.page_size = 7

        self.all_layouts = app.config['LAYOUT_DEFINITIONS']

    def _add_static_section(self, page, section, layout):
        # if section contains only one cell it's not a list
        if not isinstance(layout[section][0], list):
            page.add_to_section(section, layout[section], None)
            return

        for cell in layout[section]:
            page.add_to_section(section, cell, None)

    def _get_layouts_for(self, context):
        """ Returns all layouts appropriate for context """

        return [layout for layout in app.config['LAYOUT_DEFINITIONS'] if
                context in layout['context']]

    def group_layout(self, stars, current_page=1):
        context = 'group_page'
        layouts = self._get_layouts_for(context)

        if stars is None:
            pagination = Pagination(list(), current_page, self.page_size, 0, None)
        else:
            pagination = stars.paginate(current_page, self.page_size)
            stars = pagination.items

        # currently no logic to choose among different layouts
        assert(len(layouts) == 1)
        best_layout = layouts[0]

        page = Page()

        # Add pagination information
        setattr(page, "pagination", pagination)

        # Add header to group page
        section = 'header'
        page.add_to_section(section, best_layout[section], None)

        # Add create_star form to page
        section = 'create_star_form'

        for cell in layouts[0][section]:
            page.add_to_section(section, cell, None)

        if stars is not None:
            # Add the stars of the group to page
            section = 'stars'

            # Rank stars by score
            stars_ranked = sorted(stars, key=lambda s: s.hot(), reverse=True)

            for i, star_cell in enumerate(best_layout[section]):
                if i >= len(stars_ranked):
                    break

                star = stars_ranked[i]
                page.add_to_section(section, star_cell, star)

        return page

    def create_star_layout(self):
        """Returns a page for creating stars."""

        # use layouts for create_star_page context
        context = 'create_star_page'
        layouts = self._get_layouts_for(context)

        # currently no logic to choose among different layouts
        assert(len(layouts) == 1)

        # page entry containing the form will be called:
        section = 'create_star_form'

        page = Page()

        for cell in layouts[0][section]:
            page.add_to_section(section, cell, None)

        return page

    def create_group_layout(self):
        """Returns a page for creating groups."""

        # use layouts for create_group_page context
        context = 'create_group_page'
        layouts = self._get_layouts_for(context)
        page = Page()

        # currently no logic to choose among different layouts
        assert(len(layouts) == 1)
        best_layout = layouts[0]

        # add layout for static fields
        self._add_static_section(page, 'header', best_layout)
        self._add_static_section(page, 'create_group_form', best_layout)

        return page

    def persona_layout(self, persona, stars=None, current_page=1):
        """Return page for a Persona's profile page"""
        from nucleus.models import Star

        if stars is None and hasattr(persona, "profile") and hasattr(persona.profile, "index"):
            stars = persona.profile.index.filter(Star.state >= 0).filter(Star.parent_id == None)

        context = 'persona_page'
        layouts = self._get_layouts_for(context)

        if stars is None:
            pagination = Pagination(list(), current_page, self.page_size, 0, None)
        else:
            pagination = stars.paginate(current_page, self.page_size)
            stars = pagination.items

        # currently no logic to choose among different layouts
        assert(len(layouts) == 1)
        best_layout = layouts[0]

        page = Page()

        # Add vcard to group page
        section = 'vcard'
        page.add_to_section(section, best_layout[section], None)

        # Add pagination information
        setattr(page, "pagination", pagination)

        if stars is not None:
            # Add the stars of the profile to page
            section = 'stars'

            # Rank stars by score
            stars_ranked = sorted(stars, key=lambda s: s.hot(), reverse=True)

            for i, star_cell in enumerate(best_layout[section]):
                if i >= len(stars_ranked):
                    break

                star = stars_ranked[i]
                page.add_to_section(section, star_cell, star)

        return page

    def star_layout(self, stars, current_page=1):
        """Return the optimal layouted page for the given stars."""

        context = 'star_page'
        layouts = self._get_layouts_for(context)

        if stars is None:
            pagination = Pagination(list(), current_page, self.page_size, 0, None)
        else:
            pagination = stars.paginate(current_page, self.page_size)
            stars = pagination.items

        # Rank stars by score
        stars_ranked = sorted(stars, key=lambda s: s.hot(), reverse=True)

        # Find best layout by filling each one with stars
        # and determining which one gives the best score
        layout_scores = dict()
        for layout in layouts:
            # print("\nLayout: {}".format(layout['name']))
            layout_scores[layout['name']] = 0

            stars_with_images = [s for s in stars_ranked if s.has_picture()]
            all_stars = stars_ranked[:]

            if "stars_with_images" in layout:
                for i, star_cell in enumerate(layout['stars_with_images']):
                    if i >= len(stars_with_images):
                        continue
                    star = stars_with_images[i]

                    cell_score = self._cell_score(star_cell) * 2.0
                    layout_scores[layout['name']] += star.hot() * cell_score
                    all_stars.remove(star)

            for i, star_cell in enumerate(layout['stars']):
                if i >= len(all_stars):
                    continue
                star = all_stars[i]

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
            # TODO: Throw exception here, if no layout found the PM failed
            app.logger.error("No fitting layout found")
            return

        for layout in layouts:
            if layout['name'] == selected_layouts[0][0]:
                break

        # print("Chosen {}".format(layout))

        page = Page()

        # Add pagination information
        setattr(page, "pagination", pagination)

        section = 'stars_with_images'
        if section in layout:
            for i, star_cell in enumerate(layout[section]):
                if i >= len(stars_ranked):
                    break

                for star in stars_ranked:
                    if star.has_picture():
                        page.add_to_section(section, star_cell, star)
                        stars_ranked.remove(star)

        section = 'stars'
        for i, star_cell in enumerate(layout[section]):
            if i >= len(stars_ranked):
                break

            star = stars_ranked[i]
            page.add_to_section(section, star_cell, star)

        return page

    def _cell_score(self, cell):
        """ Return a score that describes how valuable a given cell on
        the screen is. Cell on the top left is 1.0, score diminishes to
        the right and bottom. Bigger cells get higher scores, cells off
        the screen get a 0.0 """

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


class Page(object):
    """Responsible for the layout of a page. Instances of Page
    hold variables for each dynamic section of the page. This
    variables hold a list with the entries of the section.
    An entry is a dict with the keys 'css_class' and 'content'.
    Example:
        star_page:
            + header:[
                {css_class:'col1 row1 w3 h1', content: None}
              ]
            + stars: [
                {css_class:'col1 row2 w3 h1', content: star1},
                {css_class:'col1 row3 w3 h1', content: star2}
              ]
    """

    def add_to_section(self, section, entry, content):
        """ Adds a new entry to the page section 'section'
        (and creates it if necessary). """

        section_entry = self._create_entry(entry, content)

        if not hasattr(self, section):
            setattr(self, section, [])

        attr = getattr(self, section)
        attr.append(section_entry)

    def _create_entry(self, cell, content):
        """ Creates a section of a page consisting of a dict
        containing the css_class and the content of the section.
        CSS class name format
         col   column at which the css container begins
         row   row at which it begins
         w     width of the container
         h     height of the container
        """
        css_class = "col{} row{} w{} h{}".format(
            cell[0],
            cell[1],
            cell[2],
            cell[3])

        return {'css_class': css_class, 'content': content}
