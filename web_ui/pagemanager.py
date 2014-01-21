from operator import itemgetter
from web_ui import app


class PageManager(object):
    """ Abstract class defining common functions for all
    PageManager subclasses.
    Subclasses should define:
        - class variable: context
        - function: auto_layout
    """

    def __init__(self):
        """ Initializes screen size and  loads all layouts
        for the right context, using the context defined in
        the concrete subclass.
        """

        self.screen_size = (12.0, 8.0)
        self.context = self.__class__.context

        all_layouts = app.config['LAYOUT_DEFINITIONS']
        self.layouts = [layout for layout in all_layouts if
                        self.context in layout['context']]

    def auto_layout(self):
        raise NotImplementedError

    def create_page_section(self, cell, content):
        """ Creates a section of a page consisting of a dict
        with the containing the css_class and the content of
        the section.
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


class CreateStarPageManager(PageManager):
    context = 'create_star_page'

    def auto_layout(self):
        # currently no logic to choose among different layouts
        assert(len(self.layouts) == 1)
        page = {'create_star_form': []}

        for cell in self.layouts[0]['create_star_form']:
            page['create_star_form'].append(
                self.create_page_section(cell, None))

        return page


class StarPageManager(PageManager):
    context = 'star_page'

    def auto_layout(self, stars):
        """Return a page for given stars i.e. a list of
        dicts: (css_class-> x), (content->y).
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
            # TODO: Throw exception here, if no layout found the PM failed
            app.logger.error("No fitting layout found")
            return

        for layout in self.layouts:
            if layout['name'] == selected_layouts[0][0]:
                break

        # print("Chosen {}".format(layout))

        # Create list of elements in layout
        page = {'stars': []}
        for i, star_cell in enumerate(layout['stars']):
            if i >= len(stars_ranked):
                break

            star = stars_ranked[i]
            page['stars'].append(self.create_page_section(star_cell, star))

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
