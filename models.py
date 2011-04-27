import cgi
import datetime
import hashlib
import logging
import math
import re
import urllib
import urlparse
import uuid

from google.appengine.ext import db
from django.utils import simplejson as json


### Functions ###
def prefetch_refprop(entities, prop):
    ref_keys = [prop.get_value_for_datastore(x) for x in entities]
    entities = [e for e, k in zip(entities, ref_keys) if k is not None]
    ref_keys = [k for k in ref_keys if k is not None]
    ref_entities = dict((x.key(), x) for x in db.get(set(ref_keys)))
    for entity, ref_key in zip(entities, ref_keys):
        prop.__set__(entity, ref_entities[ref_key])
    return entities


### Models ###
class Votable(db.Model):
    created = db.DateTimeProperty(auto_now_add=True)
    updated = db.DateTimeProperty(auto_now=True)
    points = db.IntegerProperty(default=1)
    score = db.FloatProperty()
    ip_likes = db.StringListProperty()
    ip_dislikes = db.StringListProperty()
    
    def update_score(self):
        """Adapted from reddit's algorithm
        http://code.reddit.com/browser/r2/r2/lib/db/sorts.py?rev=4778b17e939e119417cc5ec25b82c4e9a65621b2
        """
        td = self.created - datetime.datetime(1970, 1, 1)
        epoch_seconds = td.days * 86400 + td.seconds + (float(td.microseconds) / 1000000)
        order = math.log(max(abs(self.points), 1), 10)
        sign = 1 if self.points > 0 else -1 if self.points < 0 else 0
        seconds = epoch_seconds - 1134028003
        self.score = round(order + sign * seconds / 45000, 7)


class Video(Votable):
    author = db.StringProperty()
    title = db.StringProperty(indexed=False)
    youtube = db.StringProperty()
    vimeo = db.StringProperty()
    thumbnail = db.StringProperty(indexed=False)
    text = db.TextProperty(default='')
    n_comments = db.IntegerProperty(default=0)
    
    def set_thumbnail(self):
        if self.youtube:
            api = 'http://gdata.youtube.com/feeds/api/videos/' + self.youtube + '?v=2&alt=json'
            response = urllib.urlopen(api).read()
            logging.error(response)
            try:
                data = json.loads(response)
            except ValueError:
                return
            self.thumbnail = data['entry']['media$group']['media$thumbnail'][1]['url']
        elif self.vimeo:
            api = 'http://vimeo.com/api/v2/video/' + self.vimeo + '.json'
            response = urllib.urlopen(api).read()
            data = json.loads(response)
            if not data: return
            self.thumbnail = data[0]['thumbnail_large']
        
    def replies(self):
        """Fetches the topic's comments & sets each comment's 'replies' attribute"""
        keys = {}
        comments = self.comments.order('-score').fetch(1000)
        for comment in comments:
            keys[str(comment.key())] = comment
            comment.replies = []
        for comment in comments:
            parent_key = Comment.reply_to.get_value_for_datastore(comment)
            parent = keys.get(str(parent_key))
            if parent:
                parent.replies.append(comment)
        replies = [c for c in comments if not c.reply_to]
        prefetch_refprop(replies, Comment.author)
        return replies


class Comment(Votable):
    author = db.StringProperty()
    video = db.ReferenceProperty(Video, collection_name='comments')
    text = db.TextProperty()
    reply_to = db.SelfReferenceProperty(collection_name='reply_to_set')


