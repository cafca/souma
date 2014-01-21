# from web_ui import db


# t_starmap_index = db.Table(
#     'starmap_index',
#     db.Column('starmap_id', db.String(32), db.ForeignKey('starmap.id')),
#     db.Column('orb_id', db.String(32), db.ForeignKey('orb.id'))
# )


# class Starmap(db.Model):
#     __tablename__ = 'starmap'
#     id = db.Column(db.String(32), primary_key=True)
#     index = db.relationship(
#         'Orb',
#         secondary='starmap_index',
#         primaryjoin='starmap_index.c.starmap_id==starmap.c.id',
#         secondaryjoin='starmap_index.c.orb_id==orb.c.id')

#     def __init__(self, id):
#         self.id = id

#     def __contains__(self, key):
#         return (key in self.index)

#     def __repr__(self):
#         return "<Starmap {}>".format(self.id)

#     def add(self, orb):
#         """Add Orb to this starmap"""
#         if orb in self.index:
#             raise KeyError("{} is already part of {}.".format(orb, self))
#         return self.index.append(orb)


# class Orb(db.Model):
#     """Stub for any object that might exist in a starmap"""

#     __tablename__ = 'orb'
#     id = db.Column(db.String(32), primary_key=True)
#     type = db.Column(db.String(32))
#     modified = db.Column(db.DateTime)
#     creator = db.Column(db.String(32))

#     def __init__(self, object_type, id, modified, creator=None):
#         self.id = id
#         self.type = object_type
#         self.modified = modified
#         self.creator = creator

#     def __repr__(self):
#         return "<Orb:{} {}>".format(self.type, self.id[:6])
