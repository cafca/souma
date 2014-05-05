from operator import itemgetter

from web_ui import app
from web_ui.helpers import watch_layouts

from gevent import Greenlet

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

        # Load layouts once and then continuously update them
        Greenlet.spawn(watch_layouts)

        # Number of items on one page
        # Flask-SQLAlchemy pagination requires this to be static, i.e.
        # it is not possible to have different number of items on consecutive
        # pages. If we need that, we will have to implement our own pagination.
        self.page_size = 7

    def _add_static_section(self, page, section, layout):
        # if section contains only one cell it's not a list
        if not isinstance(layout[section][0], list):
            page.add_to_section(section, layout[section], None)
            return

        for cell in layout[section]:
            page.add_to_section(section, cell, None)

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

    def _get_layouts_for(self, context):
        """ Returns all layouts appropriate for context

        Args:
            context (String): Name of the context

        Returns:
            list: List of dicts containing layout information
        """

        layouts = app.config["LAYOUT_DEFINITIONS"]
        if len(layouts) == 0:
            # Asynchronous loading has not completed, load synchronously
            layouts = watch_layouts(continuous=False)

        return [layout for layout in layouts if
                context in layout['context']]

    def _best_layout(self, layouts, stars):
        """Find the best layout for some Stars

        This method will fill each of the layouts with the given Stars
        and then calculate a score for each of them and return the best.

        _cell_score is used to assign a score to each cell contained
        in the layout.

        Args:
            layouts (list): List of layout dicts
            stars (iterable): Stars for the layout

        Returns:
            dict: Best layout
        """
        # Find best layout by filling each one with stars
        # and determining which one gives the best score
        layout_scores = dict()
        for layout in layouts:
            # print("\nLayout: {}".format(layout['name']))
            layout_scores[layout['name']] = 0

            stars_with_images = [s for s in stars if s.has_picture()]
            all_stars = stars[:]

            if "stars_with_images" in layout:
                for i, star_cell in enumerate(layout['stars_with_images']):
                    if i >= len(stars_with_images):
                        # Penalty for layouts that are not completely filled
                        layout_scores[layout['name']] -= 0.1
                        continue
                    star = stars_with_images[i]

                    cell_score = self._cell_score(star_cell) * 2.0
                    layout_scores[layout['name']] += (1 + star.oneup_count()) * cell_score
                    all_stars.remove(star)

            for i, star_cell in enumerate(layout['stars']):
                if i >= len(all_stars):
                    layout_scores[layout['name']] -= 0.1
                    continue
                star = all_stars[i]

                cell_score = self._cell_score(star_cell)
                layout_scores[layout['name']] += (1 + star.oneup_count()) * cell_score
                # print("{}\t\t{}\t{}\t{}".format(star, star.oneup_count(), cell_score, (1 + star.oneup_count()) * cell_score))
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
                best_layout = layout

        return best_layout

    def create_group_layout(self):
        """Returns a page for creating groups.

        Returns:
            Page: Layout object for the page
        """

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

    def create_star_layout(self):
        """Returns a page for creating stars.

        Returns:
            Page: Layout object for the page
        """

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

    def group_layout(self, stars, current_page=1):
        """Given some stars, return Chapter for a group page containing these Stars.

        Args:
            stars (flask.ext.sqlalchemy.BaseQuery): Query for stars to contain in the page
            current_page (int): Page number used for pagination

        Returns:
            Chapter: Layout object for the page
        """
        context = 'group_page'

        if stars is None:
            stars_ranked = list()
        else:
            # Rank stars by score
            stars_ranked = sorted(stars, key=lambda s: s.hot())

        layouts = self._get_layouts_for(context)
        ch = Chapter(current_page=current_page)

        while ch.empty or len(stars_ranked) > 0:
            page = Page()

            best_layout = self._best_layout(layouts, stars_ranked)

            # Add header to group page
            section = 'header'
            page.add_to_section(section, best_layout[section], None)

            # Add create_star form to page
            section = 'create_star_form'

            for cell in best_layout[section]:
                page.add_to_section(section, cell, None)

            section = 'stars_with_images'
            if section in best_layout:
                for i, star_cell in enumerate(best_layout[section]):
                    for star in reversed(stars_ranked):
                        if star.has_picture():
                            page.add_to_section(section, star_cell, star)
                            stars_ranked.remove(star)
                            break

            section = 'stars'
            for i, star_cell in enumerate(best_layout[section]):
                if len(stars_ranked) > 0:
                    star = stars_ranked.pop()
                    page.add_to_section(section, star_cell, star)

            ch.add_page(page)
        return ch

    def persona_layout(self, persona, stars=None, current_page=1):
        """Return Chapter for a Persona's profile page

        Args:
            persona (Persona): Persona object whose profile will be used to fill the page
            stars (flask.ext.sqlalchemy.BaseQuery): Optional query for stars to replace persona's profile
            current_page (int): Page number used for pagination

        Returns:
            Chapter: Layout object for the star collection
        """
        from nucleus.models import Star

        if stars is None and hasattr(persona, "profile") and hasattr(persona.profile, "index"):
            stars = persona.profile.index.filter(Star.state >= 0).filter(Star.parent_id == None)

        context = 'persona_page'

        if stars is None:
            stars_ranked = list()
        else:
            # Rank stars by score
            stars_ranked = sorted(stars, key=lambda s: s.hot(), reverse=True)

        # Find best layout
        layouts = self._get_layouts_for(context)
        ch = Chapter(current_page=current_page)

        while ch.empty or len(stars_ranked) > 0:
            page = Page()

            best_layout = self._best_layout(layouts, stars_ranked)

            # Add vcard to group page
            section = 'vcard'
            page.add_to_section(section, best_layout[section], None)

            section = 'stars_with_images'
            if section in best_layout:
                for i, star_cell in enumerate(best_layout[section]):
                    for star in reversed(stars_ranked):
                        if star.has_picture():
                            page.add_to_section(section, star_cell, star)
                            stars_ranked.remove(star)
                            break

            section = 'stars'
            for i, star_cell in enumerate(best_layout[section]):
                if len(stars_ranked) > 0:
                    star = stars_ranked.pop()
                    page.add_to_section(section, star_cell, star)

            ch.add_page(page)

        return ch

    def star_layout(self, stars, current_page=1):
        """Return a chapter containing layouts for the given stars.

        Args:
            stars (flask.ext.sqlalchemy.BaseQuery): Query for stars in the page
            current_page (int): Page number used for pagination

        Returns:
            Chapter: Layout object for the star collection
        """

        context = 'star_page'

        if stars is None:
            stars_ranked = list()
        else:
            # Rank stars by score
            stars_ranked = sorted(stars, key=lambda s: s.hot())

        layouts = self._get_layouts_for(context)
        ch = Chapter(current_page=current_page)

        while ch.empty or len(stars_ranked) > 0:
            page = Page()

            best_layout = self._best_layout(layouts, stars_ranked)

            section = 'stars_with_images'
            if section in best_layout:
                for i, star_cell in enumerate(best_layout[section]):
                    for star in reversed(stars_ranked):
                        if star.has_picture():
                            page.add_to_section(section, star_cell, star)
                            stars_ranked.remove(star)
                            break

            section = 'stars'
            for i, star_cell in enumerate(best_layout[section]):
                if len(stars_ranked) > 0:
                    star = stars_ranked.pop()
                    page.add_to_section(section, star_cell, star)

            ch.add_page(page)

        return ch


class Chapter(object):
    """Contains a set of pages with layout information"""

    def __init__(self, current_page=1):
        self.current_page = current_page
        self.pages = list()

    def add_page(self, page):
        """Append a page to this chapter

        Args:
            page (Page): Page object
        """
        self.pages.append(page)

    @property
    def empty(self):
        """Return True if no pages"""
        return self.page_count == 0

    @property
    def has_next(self):
        """True if a next page exists."""
        return self.current_page < self.page_count

    @property
    def has_prev(self):
        """True if a previous page exists"""

    def iter_pages(self, left_edge=2, left_current=2,
                   right_current=5, right_edge=2):
        """Iterates over the page numbers in the pagination.  The four
        parameters control the thresholds how many numbers should be produced
        from the sides.  Skipped page numbers are represented as `None`.

        This method is taken from the Pagination class in the Flask-SQLAlchemy
        package (Copyright (c) 2010 by Armin Ronacher) and licensed under the
        Flask-SQLAlchemy LICENSE as seen in the /licenses folder of this
        repository.
        """
        last = 0
        for num in xrange(1, self.page_count + 1):
            if num <= left_edge or \
               (num > self.current_page - left_current - 1 and
                num < self.current_page + right_current) or \
               num > self.page_count - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num

    def next(self):
        """Return the next page"""
        self.pages[self.next_num]

    @property
    def next_num(self):
        """Number of the next page"""
        return self.current_page + 1

    @property
    def page(self):
        """Return current page"""
        return self.pages[self.current_page - 1]

    @property
    def page_count(self):
        """The total number of pages"""
        return len(self.pages)

    @property
    def prev(self):
        """Previous page"""
        self.pages[self.prev_num]

    @property
    def prev_num(self):
        """Number of the previous page."""
        self.current_page - 1


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

    def __init__(self, pagination=None):
        self.pagination = pagination

    def _create_entry(self, cell, content):
        """ Creates a section of a page consisting of a dict
        containing the css_class and the content of the section.

         Args:
            cell (list): List of four elements:
                0 (int) -- column at which the css container begins
                1 (int) -- row at which it begins
                2 (int) -- width of the container
                3 (int) -- height of the container
            content (object): Object containing entry contents

        Returns:
            dict: Entry information
                css_class (String): CSS classname of the entry
                content (object): Object containing page contents
        """
        css_class = "col{} row{} w{} h{}".format(
            cell[0],
            cell[1],
            cell[2],
            cell[3])

        return {'css_class': css_class, 'content': content}

    def add_to_section(self, section, entry, content):
        """ Adds a new entry to the page section 'section'
        (and creates it if necessary).

        Args:
            section (String): Section name
            entry (list): List of four elements:
                0 (int) -- column at which the css container begins
                1 (int) -- row at which it begins
                2 (int) -- width of the container
                3 (int) -- height of the container
            content (object): Object containing entry contents
        """

        section_entry = self._create_entry(entry, content)

        if not hasattr(self, section):
            setattr(self, section, [])

        attr = getattr(self, section)
        attr.append(section_entry)
