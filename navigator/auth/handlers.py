# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import json
from aiohttp import web
from navigator.conf import (
    SESSION_KEY
)
from navigator.handlers import nav_exception_handler
from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth
)
from navigator.auth.sessions import get_session
from navigator.views import BaseView, BaseHandler
from asyncdb.utils.encoders import DefaultEncoder
from navigator.auth.models import User

class UserHandler(BaseView):

    async def session(self):
        session = None
        try:
            session = await get_session(self.request)
        except Exception as err:
            print(err)
            return self.critical(
                request=self.request,
                exception=err
            )
        return session

    async def get(self):
        """ Getting Session information."""
        session = await self.session()
        try:
            if not session:
                headers = {"x-status": "Empty", "x-message": "Invalid User Session"}
                return self.no_content(headers=headers)
            else:
                try:
                    id = session[SESSION_KEY]
                except KeyError:
                    return self.error('Invalid Session, missing Session ID')
                headers = {"x-status": "OK", "x-message": "Session OK"}
                userdata = dict(session)
                data = {
                    "session_id": id,
                    **userdata
                }
                if data:
                    return self.json_response(
                        response=data,
                        headers=headers
                    )
        except Exception as err:
            return self.error(
                self.request,
                exception=err
            )

    async def delete(self):
        """ Close and Delete User Session."""
        session = await self.session()
        try:
            app = self.request.app
            router = app.router
            session.invalidate()
            print(session)
        except Exception as err:
            print(err, err.__class__.__name__)
            return self.critical(
                request=self.request,
                exception=err,
                state=501
            )
        # return a redirect to LOGIN
        return web.HTTPFound(router["login"].url_for())

    async def put(self):
        """Re-login and re-authenticate..."""


class UserInfo(BaseHandler):

    async def session(self, request):
        session = None
        try:
            session = await get_session(request)
        except Exception as err:
            print(err)
            return self.critical(
                request=request,
                exception=err
            )
        return session

    async def profile(self, request):
        session = await self.session(request)
        print(session)
        if not session:
            headers = {"x-status": "Empty", "x-message": "Invalid User Session"}
            return self.no_content(headers=headers)
        else:
            try:
                sessionid = session['id']
            except KeyError:
                return self.error('Invalid Session, missing Session ID')
        # getting User information
        try:
            user_id = request["user_id"]
        except KeyError:
            info = session[sessionid]
            user_id = info['user_id']
        try:
            user = await User.get(user_id=user_id)
            return web.Response(
                text=user.json(ensure_ascii=True, indent=4),
                status=200,
                content_type="application/json"
            )
        except Exception as err:
            print(err)
            return self.critical(
                request=request,
                exception=err
            )

    async def logout(self, request):
        """ Close and Delete User Session."""
        session = await self.session(request)
        try:
            app = request.app
            router = app.router
            session.invalidate()
        except Exception as err:
            print(err, err.__class__.__name__)
            response = {
                "message": f"Exception on: {err.__class__.__name__}",
                "error": str(err)
            }
            args = {
                "status": 501,
                "content_type": "application/json",
                "text": json.dumps(response, cls=DefaultEncoder)
            }
            return web.Response(**args)
        # return a redirect to LOGIN
        # TODO: configure the return of LOGOUT
        return web.HTTPFound('/')
