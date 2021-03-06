# -*- coding:utf-8 -*-
import os
import sublime
from urllib.parse import urljoin
from sublime_plugin import ApplicationCommand

from .command import CommandWithStatus

from ..logger import logger
from ..archiver import Archiver
from .. import requests
from .. import SETTINGS_USER_FILE


class UploadCommand(ApplicationCommand, CommandWithStatus):
    def __init__(self, *args, **kwargs):
        super(UploadCommand, self).__init__(*args, **kwargs)
        self.running = False
        self.password = None
        self.archive_filename = None

    def post_send(self):
        """
        Resets values
        """
        self.unset_message()
        self.running = False
        self.password = None
        self.archive_filename = None

    def prompt_password(self):
        """
        Shows an input panel for entering password
        """
        logger.info('Prompt archive passphrase')
        sublime.active_window().show_input_panel(
            "Enter archive passphrase",
            initial_text='',
            on_done=self.pack_and_send_async,
            on_cancel=self.pack_and_send_async,
            on_change=None
        )

    def pack_and_send(self):
        """
        Create archive and send it to the API
        """
        self.set_message("Creating archive...")

        archiver = Archiver()
        try:
            self.archive_filename = archiver.pack_packages(
                password=self.password,
                exclude_from_package_control=self.exclude_from_package_control)
        except Exception as err:
            self.set_timed_message(str(err), clear=True)
            logger.error(err)
            self.post_send()

        self.send_to_api()

    def pack_and_send_async(self, password=None):
        """
        Starts ansync command
        """
        self.password = password or None
        sublime.set_timeout_async(self.pack_and_send, 0)

    def send_to_api(self):
        """
        Send archive file to API
        """
        self.set_message("Sending archive...")
        f = open(self.archive_filename, 'rb')

        files = {
            'package': f.read(),
            'version': sublime.version()[:1],
            'platform': sublime.platform(),
            'arch': sublime.arch(),
            'email': self.email,
            'api_key': self.api_key,
        }

        # Send data and delete temporary file
        proxies = {}
        if self.settings.get('http_proxy', ''):
            proxies = {'http': self.settings.get('http_proxy')}
        try:
            r = requests.post(
                url=self.api_upload_url,
                files=files,
                proxies=proxies,
                timeout=self.settings.get('http_upload_timeout'))
        except requests.exceptions.ConnectionError as err:
            self.set_timed_message(
                "Error while sending archive: server not available, try later",
                clear=True)
            print(err)
            self.running = False
            logger.error(
                'Server (%s) not available, try later.\n'
                '==========[EXCEPTION]==========\n'
                '%s\n'
                '===============================' % (
                    self.api_upload_url, err))
            return
        except requests.exceptions.Timeout as err:
            self.set_timed_message(
                "Error while sending archive: upload take to long time. "
                "Increase \"http_upload_timeout\" setting.",
                clear=True)
            self.running = False
            logger.error(
                'Server (%s) time out, request take too long, try later.\n'
                '==========[EXCEPTION]==========\n'
                '%s\n'
                '===============================' % (
                    self.api_upload_url, err))
            return

        f.close()
        os.unlink(self.archive_filename)

        if r.status_code == 201:
            self.set_timed_message("Successfully sent archive", clear=True)
            logger.info('HTTP [%s] Successfully sent archive' % r.status_code)
        elif r.status_code == 403:
            self.set_timed_message(
                "Error while sending archive: wrong credentials", clear=True)
            logger.info('HTTP [%s] Bad credentials' % r.status_code)
        elif r.status_code == 413:
            self.set_timed_message(
                "Error while sending archive: filesize too large (>30MB)", clear=True)
            logger.error("HTTP [%s] %s" % (r.status_code, r.content))
        else:
            msg = "Unexpected error (HTTP STATUS: %s)" % r.status_code
            try:
                j = r.json()
                for error in j.get('errors'):
                    msg += " - %s" % error
            except:
                pass
            self.set_timed_message(msg, clear=True, time=10)
            logger.error('HTTP [%s] %s' % (r.status_code, r.content))

        self.post_send()

    def run(self, *args):
        """
        Create an archive of all packages and settings
        """
        if self.running:
            self.set_timed_message("Already working on a backup...")
            logger.warn('Already working on a backup')
            return

        self.settings = sublime.load_settings(SETTINGS_USER_FILE)
        self.api_upload_url = urljoin(
            self.settings.get('api_root_url'), self.settings.get('api_upload_url'))

        logger.info('Starting upload')

        self.email = self.settings.get('email', '')
        self.api_key = self.settings.get('api_key', '')
        self.exclude_from_package_control = self.settings.get(
            'exclude_from_package_control', False)
        self.encrypt = self.settings.get('encrypt', False)

        if not self.email or not self.api_key:
            self.set_timed_message(
                "api_key or email is missing in your Sublimall configuration", clear=True)
            logger.warn('API key or email is missing in configuration file. Abort')
            return

        self.running = True

        logger.info('Encrypt enabled')
        if self.encrypt:
            self.prompt_password()
        else:
            self.pack_and_send_async()
