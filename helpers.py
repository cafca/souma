from datetime import datetime


class Serializable():
    """ Make SQLAlchemy models json serializable"""
    def export(self, exclude=[], include=None):
        """Return this object as a dict"""
        if include:
            return {
                field: str(getattr(self, field)) for field in include}
        else:
            return {
                c.name: str(getattr(self, c.name)) for c in self.__table__.columns if c not in exclude}

    def json(self, exclude=[]):
        """Return this object JSON encoded"""
        import json
        return json.dumps(self.export(exclude), indent=4)


# For calculating scores
epoch = datetime.utcfromtimestamp(0)
epoch_seconds = lambda dt: (dt - epoch).total_seconds() - 1356048000


def score(star_object):
    import random
    return random.random() * 100 - random.random() * 10
