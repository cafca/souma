#!/usr/bin/env python


# Allows you to get a console and enter commands within your flask environment. 
# Maybe not as nice as debugging with pdb, but always useful (when you will initialize your database).


import os
import readline
from pprint import pprint

from flask import *
from app import *

os.environ['PYTHONINSPECT'] = 'True'
