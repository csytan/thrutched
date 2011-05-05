import os
import wsgiref.handlers

import tornado.wsgi

import views
import models


settings = {
    'template_path': os.path.join(os.path.dirname(__file__), 'templates'),
    'debug': views.DEBUG,
    'cookie_secret': 'bob',
    'xsrf_cookies': True,
}
application = tornado.wsgi.WSGIApplication([
    (r'/', views.Index),
    (r'/submit', views.Submit),
    (r'/(\d+)', views.Video)
], **settings)


def main():
    wsgiref.handlers.CGIHandler().run(application)


if __name__ == "__main__":
    main()
    