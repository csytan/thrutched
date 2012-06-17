import cgi
import datetime
import hashlib
import json
import logging
import math
import re
import urllib
import urlparse
import uuid

from google.appengine.ext import ndb

import feedparser
import bs4


### Models ###
class Votable(ndb.Model):
    created = ndb.DateTimeProperty(auto_now_add=True)
    points = ndb.IntegerProperty(default=1)
    score = ndb.FloatProperty()
    ip_likes = ndb.StringProperty(repeated=True)
    ip_dislikes = ndb.StringProperty(repeated=True)
    
    def update_score(self):
        """Adapted from reddit's algorithm
        http://code.reddit.com/browser/r2/r2/lib/db/sorts.py?rev=4778b17e939e119417cc5ec25b82c4e9a65621b2
        """
        td = (self.created or datetime.datetime.now()) - datetime.datetime(1970, 1, 1)
        epoch_seconds = td.days * 86400 + td.seconds + (float(td.microseconds) / 1000000)
        order = math.log(max(abs(self.points), 1), 10)
        sign = 1 if self.points > 0 else -1 if self.points < 0 else 0
        seconds = epoch_seconds - 1134028003
        self.score = round(order + sign * seconds / 45000, 7)


class Video(Votable):
    author = ndb.StringProperty()
    title = ndb.StringProperty(indexed=False)
    youtube = ndb.StringProperty()
    vimeo = ndb.StringProperty()
    thumbnail = ndb.StringProperty(indexed=False)
    text = ndb.TextProperty(default='')

    @classmethod
    def hottest(cls, page=0):
        return cls.query().order(-Video.created).fetch(9, offset=page*9)

    @classmethod
    def add_youtube(cls, id):
        video = cls.query(cls.youtube == id).get()
        if video: return video

        api = 'http://gdata.youtube.com/feeds/api/videos/' + id + '?v=2&alt=json&key=AI39si5nwWTo74H9slMDgT-fO_PkbBGIKzEMwJ53iWOUUKaHFmphCjXDoYFyagU5W15Q7ZB7wRpON-fHNLdMnGOWsiz18_kQig'
        response = urllib.urlopen(api).read()
        try:
            data = json.loads(response)
        except ValueError:
            logging.error(id + '\n' + response)
            return

        video = cls(
            youtube=id,
            title=data['entry']['title']['$t'],
            text=data['entry']['media$group']['media$description']['$t'],
            thumbnail='http://img.youtube.com/vi/' + id + '/hqdefault.jpg')
        video.update_score()
        video.put()

    @classmethod
    def add_vimeo(cls, id):
        video = cls.query(cls.vimeo == id).get()
        if video: return video

        api = 'http://vimeo.com/api/v2/video/' + id + '.json'
        response = urllib.urlopen(api).read()
        data = json.loads(response)
        if not data:
            return

        video = cls(
            vimeo=id,
            title=data[0]['title'],
            text=data[0]['description'],
            thumbnail=data[0]['thumbnail_large'])
        video.update_score()
        video.put()

    def next_vid(self):
        return Video.query(Video.created < self.created).order(-Video.created).get()


_YOUTUBE_RE = re.compile(r'youtube\.com\/watch\?\S*v=([^&\s]{11})')
_VIMEO_RE = re.compile(r'vimeo\.com\/(\d+)')


class Feed(ndb.Model):
    updated = ndb.DateTimeProperty(auto_now=True)
    name = ndb.StringProperty(indexed=False)
    url = ndb.StringProperty(indexed=False)
    find_words = ndb.StringProperty(repeated=True, indexed=False)

    def fetch_vids(self):
        rss = feedparser.parse(self.url)
        entries = rss.entries or rss.channel
        for entry in rss.entries:
            text = entry.link + ' ' + entry.title + ' ' + entry.description
            #text = bs4.BeautifulSoup(text).text
            text_lowered = text.lower()

            if self.find_words:
                for word in self.find_words:
                    if word in text:
                        break
                else:
                    continue
            #logging.error(text)
            youtube = _YOUTUBE_RE.findall(text)
            vimeo = _VIMEO_RE.findall(text)
            if youtube:
                Video.add_youtube(youtube[0])
            elif vimeo:
                Video.add_vimeo(vimeo[0])

