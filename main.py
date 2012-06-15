import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), 'lib'))

from google.appengine.ext import ndb
import tornado.wsgi

import views
import models


settings = {
    'template_path': os.path.join(os.path.dirname(__file__), 'templates'),
    'debug': views.DEBUG,
    'cookie_secret': 'bob',
    'xsrf_cookies': True,
}
app = tornado.wsgi.WSGIApplication([
    (r'/', views.Index),
    (r'/submit', views.Submit),
    (r'/admin', views.Admin),
    (r'/cron', views.Cron),
    (r'/(\d+)', views.Video)
], **settings)

app = ndb.toplevel(app)
