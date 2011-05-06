import cgi
import datetime
import logging
import os
import re
import urllib
import urlparse

from google.appengine.ext import db

import tornado.web
from django.utils import simplejson as json

import models



DEBUG = os.environ['SERVER_SOFTWARE'].startswith('Dev')


class BaseHandler(tornado.web.RequestHandler):
    def head(self, *args, **kwargs):
        self.get(*args, **kwargs)
        self.request.body = ''
    
    def render_string(self, template_name, **kwargs):
        return super(BaseHandler, self).render_string(
            template_name,
            truncate=self.truncate,
            relative_date=self.relative_date,
            **kwargs)
        
    def reload(self, copyargs=False, **kwargs):
        data = {}
        if copyargs:
            for arg in self.request.arguments:
                if arg not in ('_xsrf', 'password', 'password_again'):
                    data[arg] = self.get_argument(arg)
        data.update(kwargs)
        self.redirect(self.request.path + '?' + urllib.urlencode(data))
        
    def get_error_html(self, status_code, **kwargs):
        if status_code in (404, 500): # 503 and 403
            pass
            #return self.render_string(str(status_code) + '.html')
        return super(BaseHandler, self).get_error_html(status_code, **kwargs)
        
    ### Template helpers ###
    @staticmethod
    def truncate(string, n_chars):
        new_str = string[0:n_chars]
        if len(new_str) < len(string):
            new_str += '...'
        return cgi.escape(new_str)
        
    @staticmethod
    def markdown(value, video_embed=False):
        # real line breaks
        value = re.sub(r'(\S ?)(\r\n|\r|\n)', r'\1  \n', value)
        # vimeo and youtube embed
        value = re.sub(r'(?:^|\s)http://(?:www\.)?vimeo\.com/(\d+)', r'VIMEO:\1', value)
        value = re.sub(r'(?:^|\s)http://www\.youtube\.com/watch\?\S*v=([^&\s]+)\S*', r'YOUTUBE:\1', value)
        # automatic hyperlinks
        value = re.sub(r'(^|\s)(http:\/\/\S+)', r'[\2](\2)', value)
        html = markdown2.markdown(value, safe_mode='escape')
        if video_embed:
            html = re.sub(r'VIMEO:(\d+)', 
                r'<iframe src="http://player.vimeo.com/video/\1" class="video" frameborder="0"></iframe>', html)
            html = re.sub(r'YOUTUBE:([\w|-]+)', 
                r'<iframe src="http://www.youtube.com/embed/\1?hd=1" class="video" frameborder="0"></iframe>', html)
        else:
            html = re.sub(r'VIMEO:(\d+)', 
                r'<a href="http://vimeo.com/\1" data-embed="http://player.vimeo.com/video/\1" class="video">http://vimeo.com/\1</a>', html)
            html = re.sub(r'YOUTUBE:([\w|-]+)', 
                r'<a href="http://www.youtube.com/watch?v=\1" data-embed="http://www.youtube.com/embed/\1?hd=1" class="video">http://www.youtube.com/watch?v=\1</a>', html)
        html = html.replace('<a href=', '<a rel="nofollow" href=')
        return html
        
    @staticmethod
    def relative_date(date):
        td = datetime.datetime.now() - date
        if td.days == 1:
            return '1 day ago'
        elif td.days:
            return str(td.days) + ' days ago'
        elif td.seconds / 60 / 60 == 1:
            return '1 hour ago'
        elif td.seconds > 60 * 60:
            return str(td.seconds / 60 / 60) + ' hours ago'
        elif td.seconds / 60 == 1:
            return '1 minute ago'
        elif td.seconds > 60:
            return str(td.seconds / 60) + ' minutes ago'
        else:
            return str(td.seconds) + ' seconds ago'


class Index(BaseHandler):
    def get(self):
        page = self.get_argument('page', '')
        page = abs(int(page)) if page.isdigit() else 0
        videos = models.Video.all().order('-score').fetch(9, offset=page*9)
        next_page = page + 1 if len(videos) == 9 else None
        self.render('index.html', videos=videos, next_page=next_page)


class Submit(BaseHandler):
    def get(self):
        self.render('submit.html')
        
    def post(self):
        url = self.get_argument('url', '')
        title = self.get_argument('title', '')
        text = self.get_argument('text', '')
        if not url:
            return self.reload(message='missing_url', copyargs=True)
        elif not title:
            return self.reload(message='missing_title', copyargs=True)
        elif not text:
            return self.reload(message='missing_text', copyargs=True)
        
        youtube = re.findall(r'youtube\.com\/watch\?\S*v=([^&\s]+)', url)
        vimeo = re.findall(r'vimeo\.com\/(\d+)', url)
        youtube = youtube[0] if youtube else None
        vimeo = vimeo[0] if vimeo else None
        if youtube:
            api = 'http://gdata.youtube.com/feeds/api/videos/' + youtube + '?v=2&alt=json'
            response = urllib.urlopen(api).read()
            try:
                data = json.loads(response)
            except ValueError:
                return self.reload(message='not_found', copyargs=True)
            thumbnail = data['entry']['media$group']['media$thumbnail'][1]['url']
        elif vimeo:
            api = 'http://vimeo.com/api/v2/video/' + vimeo + '.json'
            response = urllib.urlopen(api).read()
            data = json.loads(response)
            if not data:
                return self.reload(message='not_found', copyargs=True)
            thumbnail = data[0]['thumbnail_large']
        else:
            return self.reload(message='not_found', copyargs=True)
        
        video = models.Video(
            youtube=youtube,
            vimeo=vimeo,
            title=title,
            text=text,
            thumbnail=thumbnail)
        video.update_score()
        video.put()
        self.redirect('/' + str(video.key().id()))


class Video(BaseHandler):
    def get(self, id):
        video = models.Video.get_by_id(int(id))
        if not video:
            raise tornado.web.HTTPError(404)
        next_vid = models.Video.all().filter('score <', video.score).order('-score').get()
        self.render('video.html', video=video, next_vid=next_vid)
        
    def post(self, id):
        video = models.Video.get_by_id(int(id))
        if not video:
            raise tornado.web.HTTPError(404)
        
        action = self.get_argument('action')
        if action == 'like':
            response = urllib.urlopen(
                'http://graph.facebook.com/?' + \
                urllib.urlencode({'ids': self.request.full_url()})).read()
            data = json.loads(response)
            site = data.values()[0]
            video.points = site.get('shares', 0)
            video.update_score()
            video.put()
        self.write('1')
        
        