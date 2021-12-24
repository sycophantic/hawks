#!/usr/bin/env python3

import api_server
import http.server
import json
import os
import requests
import tempfile
import time

from urllib.parse import unquote

class HawksApiValidationException(Exception):
    def __init__(self, msg, status_code=400):
        self.msg = msg
        self.status_code = status_code
        super().__init__(msg)

def read_urls(hawks):
    urls = []
    try:
        URLS = open(hawks.settings.urls_file, 'r')
        urls = URLS.read().splitlines()
        URLS.close()
    except FileNotFoundError:
        pass
    return urls

def run_api(ip, port, hawks):
    api = api_server.Api(prefix="/")

    hawks.settings.set("urls", "", choices=read_urls(hawks), show=False)

    def tups(parts):
        return ((parts[n], parts[n+1]) for n in range(0, len(parts), 2))

    def usage(req, msg=""):
        settings_help = "\n".join(
            ["  {0}{1}{2}".format(k, " " * (24 - len(k)), v) for k, v in hawks.settings]
        )
        body = """
Hawks API usage:
  /api/get                Return current settings
  /api/get/settings       Return current settings
  /api/get/setting/key    Return the value of one setting (404 on error)
  /api/get/key            Return the value of one setting (200 w/usage on error)
  /api/get/presets        Return a list of presets
  /api/set/key/value      Modify a current setting. /key/value can be repeated.
  /api/do/image           Returns a PNG of the current image
  /api/do/preset/name     Apply the named preset
  /api/do/save            Save the current configuration
  /api/do/load            Load a saved configuration

Settings:
{0}

{1}
""".format(
            settings_help, msg
        )
        return req.send(200, body=body)

    def api_get(req):
        parts = req.parts[2:]
        if not parts or parts[0] == "settings":
            # GET /api or /api/settings, return a dump of all of the settings
            return req.send(
                200, body=json.dumps(dict((k, v) for k, v in hawks.settings))
            )
        if parts[0] == "presets":
            # GET /api/presets, dump the list of available presets
            return req.send(200, body=json.dumps(list(hawks.PRESETS.keys())))
        if parts[0] == "setting":
            # GET /api/setting/foo, return setting foo or 404 if setting foo does not exist
            # use this instead of GET /api/foo if you want a 404 when you screw up
            if hawks.settings.get(parts[1]):
                return req.send(200, body=json.dumps(hawks.settings.get(parts[1])))
            return req.send(404, body=f"No such setting {parts[1]}")
        if hawks.settings.get(parts[0]):
            # GET /api/foo, return setting foo if it exists, otherwise, fall through to a 200 from usage()
            # use this when you want the get/set sematics to be the same and you don't care about getting
            # a 404 when you screw up
            return req.send(200, body=json.dumps(hawks.settings.get(parts[0])))
        return usage(req)

    def make_tuple(*args, **kwargs):
        result = [*args]
        result.extend(list(kwargs.values()))
        return tuple(result)

    def test_url(url):
        response = requests.head(url)
        if response.status_code > 299:
            return False
        return True

    def normalize_data(data):
        """
        Use API-specific knowledge to validate and normalize settings input.
        Raises HakwsApiValidationException with an error message and status_code.
        """
        for key, value in data.items():
            if key == "filename":
                if not only_alpha(value):
                    raise HawksApiValidationException(f"Invalid filename: {value}")
            elif key == "text" or key == "url" or key == "urls":
                value = unquote(value)
                data[key] = value
                if key == "url" and value:
                    if not test_url(value):
                        raise HawksApiValidationException(f"Unable to fetch image from {value}")
                    if value not in hawks.settings.choices["urls"]:
                        hawks.settings.choices["urls"].append(value)
                    if hawks.settings.urls_file:
                        try:
                            URLS = open(hawks.settings.urls_file, "w")
                            URLS.write("\n".join(hawks.settings.choices["urls"]))
                            URLS.close()
                        except Exception as e:
                            print(e)
            _val = hawks.settings.get(key)
            if _val is not None:
                if type(_val) is float:
                    try:
                        value = float(value)
                    except:
                        raise HawksApiValidationException(f"Value for key {key} must be of type float")
                elif type(_val) is int:
                    try:
                        value = int(value)
                    except:
                        raise HawksApiValidationException(f"Value for key {key} must be of type int")
                elif type(_val) is bool:
                    if value in ["True", "true", True]:
                        value = True
                    elif value in ["False", "false", False]:
                        value = False
                    else:
                        raise HawksApiValidationException(f"Value for key {key} must be of type bool")
                else:
                    value = value

                data[key] = value

            else:
                raise HawksApiValidationException(f"Unknown attribute: {key}", status_code=404)

        return data

    def api_set(req, msg=None, respond=True):
        # such a stupid hack
        if respond:
            send = req.send
        else:
            send = make_tuple

        data = {}
        try:
            data = json.loads(req.data)
        except:
            pass
        data.update(dict(tups(req.parts[2:])))

        try:
            data = normalize_data(data)
        except HawksApiValidationException as e:
            return send(e.status_code, body=e.msg)

        show = False
        for key, value in data.items():
            if hawks.settings.get(key) != value:
                hawks.settings.set(key, value, show=False)
                show = True

        if show:
            hawks.show()

        if msg:
            return send(200, body=msg)
        return send(200)

    def api_do(req):
        parts = req.parts[2:]
        if not parts:
            return req.send(
                400, body="API action 'do' requires at least one command and argument"
            )
        if parts[0] == "preset":
            if parts[1]:
                if hawks.apply_preset(parts[1]):
                    return req.send(200)
                return req.send(400, body=f"Unknown preset: {parts[1]}")
            else:
                return usage(
                    req, body="Path must have non-zero, even number of elements"
                )
        elif parts[0] == "image":
            return req.send(
                200, body=hawks.screenshot(), content_type="image/png"
            )
        elif parts[0] == "save":
            if parts[1]:
                hawks.settings.save(parts[1])
                hawks.settings.save_to_file()
                return req.send(
                    200, body="config saved as \"{}\"".format(parts[1])
                )
            else:
                return req.send(
                    400, body="unable to save config"
                )
        elif parts[0] == "load":
            if parts[1]:
                if parts[1] in hawks.settings.configs:
                    hawks.settings.load(parts[1])
                    return req.send(
                        200, body="config loaded from {}".format(parts[1])
                    )
                else:
                    return req.send(
                        404, body="unable to find saved config {}".format(parts[1])
                    )
            else:
                return req.send(
                    400, body="no config name specified"
                )
        else:
            return usage(req, body == f"Unknown command: {parts[0]}")

    def api_fetch(req):
        with open("/".join(unquote(part) for part in req.parts), "rb") as IMG:
            img = IMG.read()
            req.send(200, body=img, content_type="image/jpeg")

    def only_alpha(name):
        name = unquote(name)
        if name.startswith("/"):
            return False
        if ".." in name:
            return False
        for c in name:
            if (
                c
                not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.-_/"
            ):
                return False
        return True

    def webui_form(req, message=None):
        if req.command == "POST":
            message = webui_submit(req)
        filepath = hawks.settings.filepath or "img"
        api_js = f'''
        var update_preview = function(value) {{
            img_tag = document.getElementById("preview")
            img_tag.src="{filepath}/" + value
        }}
        var update_url = function(value) {{
            url_field = document.getElementsByName("url")[0]
            url_field.value = value
            img_tag = document.getElementById("preview")
            img_tag.src = value
        }}
        '''

        try:
            hawks.settings.choices["filename"] = [
                #os.path.join(filepath, item) for item in os.listdir(filepath)
                item for item in os.listdir(filepath)
            ]
        except FileNotFoundError:
            hawks.settings.choices["filename"] = None

        hawks.settings.set("urls", hawks.settings.url, choices=read_urls(hawks), show=False)

        body = []
        body.append(f"<html><head><title>Hawks UI</title><script>{api_js}</script></head><body><H1>Hawks UI</H1>")
        if message:
            body.append(f"<h3>{time.asctime()}: {message}</h3>")
        body.append('<form method="post" action="/"><table>')
        body.append('<tr><td></td><td></td><td rowspan=4><img height="64" src="/api/do/image"></img></td></tr>')
        for setting, value in hawks.settings:
            if setting == "filename":
                value = unquote(value).replace(f"{filepath}/", "")
            body.append("<tr>")
            if setting in hawks.settings.helptext:
                helptext = hawks.settings.helptext[setting]
                body.append(f'<td title="{helptext}">')
            else:
                body.append("<td>")
            body.append(f"{setting}</td><td>")
            if setting in hawks.settings.choices and hawks.settings.choices[setting]:
                choices = hawks.settings.choices[setting]
                if setting == "filename":
                    choices.sort()
                    body.append(f'<select name={setting} value={value} size=12 oninput="update_preview(this.value)">')
                    for choice in choices:
                        if choice == value:
                            body.append(f'<option value="{choice}" selected="selected">{choice}</option>')
                        else:
                            body.append(f'<option value="{choice}">{choice}</option>')
                    body.append("</select></td><td rowspan=1><img style=\"max-height: 200px;\" id=\"preview\"</img>")
                elif setting == "urls":
                    choices.sort()
                    body.append(f'<select name={setting} value={value} size=12 oninput="update_url(this.value)">')
                    for choice in choices:
                        if choice == value:
                            body.append(f'<option value="{choice}" selected="selected">{choice}</option>')
                        else:
                            body.append(f'<option value="{choice}">{choice}</option>')
                    body.append("</select></td><td rowspan=1>")
                else:
                    body.append(f"<select name={setting} value={value}>")
                    choices.sort(key=lambda x: x != value)
                    for choice in choices:
                        body.append(f'<option value="{choice}">{choice}</option>')
                    body.append("</select>")
            else:
                if setting == "url":
                    body.append(f'<input name={setting} value="{value}" type=text style="width:100%;box-sizing:border-box;"></input>')
                else:
                    body.append(f"<input name={setting} value=\"{value}\" type=text></input>")
            body.append("</td></tr>")
        body.append("</table><br><input type=submit>")
        body.append("</form></body></html>")
        req.send(200, body="".join(body))

    def webui_submit(req):
        req.parts = ["api", "set"]
        filepath = hawks.settings.filepath or "img"
        data = req.data.decode()
        for part in data.split("&"):
            key, value = part.split("=")
            #if value in ["True", "true"]:
            #    value = True
            #elif value in ["False", "false"]:
            #    value = False
            if key == "filename":
                value = f"{filepath}/{value}"
            req.parts.extend([key, value])
        code, message = api_set(req, msg="Settings accepted", respond=False)
        return message

    def api_help(req):
        usage(req)

    api.register_endpoint("default", usage)
    api.register_endpoint("/api/get", api_get)
    api.register_endpoint("/api/set", api_set)
    api.register_endpoint("/api/do", api_do)
    api.register_endpoint("/help", api_help)
    api.register_endpoint("/api/help", api_help)
    api.register_endpoint("/img", api_fetch)
    #if hawks.settings.filepath:
    #    api.register_endpoint(f"/{hawks.settings.filepath}", api_fetch)
    api.register_endpoint("/", webui_form, methods=["GET", "POST"])
    # api.register_endpoint("/submit", webui_submit, methods=["POST"])
    api.run(ip, port)
