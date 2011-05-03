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
    
    def get_current_user(self):
        return self.get_secure_cookie('username')
        
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


class RSS(BaseHandler):
    def get(self):
        raise tornado.web.HTTPError(404)
        self.render('rss.xml')


class Submit(BaseHandler):
    def get(self):
        self.render('submit.html')
        
    def post(self):
        url = self.get_argument('url', '')
        youtube = re.findall(r'youtube\.com\/watch\?\S*v=([^&\s]+)', url)
        vimeo = re.findall(r'vimeo\.com\/(\d+)', url)
        
        if not youtube and not vimeo:
            return self.reload(message='', copyargs=True)
            
        video = models.Video(
            youtube=youtube[0] if youtube else None,
            vimeo=vimeo[0] if vimeo else None,
            title=self.get_argument('title', ''),
            text=self.get_argument('text', '')
        )
        video.set_thumbnail()
        video.update_score()
        video.put()
        self.redirect('/' + str(video.key().id()))


class Video(BaseHandler):
    def get(self, id):
        video = models.Video.get_by_id(int(id))
        if not video:
            raise tornado.web.HTTPError(404)
        next_vid = models.Video.all().filter('score <', video.score).order('-score').get()
        self.render('video.html', video=video, next_vid=next_vid, replies=video.replies())
        
    def render_comments(self, comments):
        return self.render_string('_comment.html', comments=comments)
        
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
        elif action == 'comment':
            reply_to = self.get_argument('reply_to', None)
            if reply_to:
                reply_to = models.Comment.get_by_id(int(reply_to))
            comment = models.Comment(
                author=self.get_argument('author'),
                author_ip=self.request.remote_ip,
                video=video,
                reply_to=reply_to,
                text=self.get_argument('text'))
            comment.update_score()
            comment.put()
        self.redirect(self.request.path + '#c' + str(comment.key().id()))
