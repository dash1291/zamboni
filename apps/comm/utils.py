from django.conf import settings

import commonware.log
from email_reply_parser import EmailReplyParser
import waffle

from access.models import Group
from amo.helpers import absolutify
from amo.utils import send_mail_jinja
from comm.models import  (CommunicationNote, CommunicationThreadCC,
                          CommunicationThreadToken)
from users.models import UserProfile


log = commonware.log.getLogger('comm')


def get_reply_token(thread, user):
    tok, created = CommunicationThreadToken.objects.get_or_create(
        thread=thread, user=user)

    # Reset the use count if the token already exists.
    if not created:
        tok.use_count = 0
        tok.save()

    log.info('Created token with UUID %s for user_id: %s.' % (
             tok.uuid, user))
    return tok


def get_recipients(note, fresh_thread=False):
    """
    Create/refresh tokens for users based on the thread permissions.
    """
    thread = note.thread
    recipients = []

    # TODO: Possible optimization.
    # Fetch tokens from the database if `fresh_thread=False` and use them to
    # derive the list of recipients instead of doing a couple of multi-table
    # DB queries.
    cc_list = thread.thread_cc.all()
    recipients = [cc.user for cc in cc_list]

    # Include devs.
    if thread.read_permission_developer:
        recipients += list(thread.addon.authors.all())

    groups_list = []
    # Include app reviewers.
    if thread.read_permission_reviewer:
        groups_list.append('App Reviewers')

    # Include senior app reviewers.
    if thread.read_permission_senior_reviewer:
        groups_list.append('Senior App Reviewers')

    # Include admins.
    if thread.read_permission_staff:
        groups_list.append('Admins')

    if len(groups_list) > 0:
        groups = Group.objects.filter(name__in=groups_list)
        for group in groups:
            recipients += list(group.users.all())

    # Include Mozilla contact.
    if thread.read_permission_mozilla_contact:
        if thread.addon.mozilla_contact:
            recipients.append(thread.addon.mozilla_contact)

    recipients = list(set(recipients))

    if note.author.email in recipients:
        get_reply_token(note.thread, note.author.email)
        recipients.remove(note.author)

    new_recipients_list = []
    for u in recipients:
        tok = get_reply_token(note.thread, u)
        new_recipients_list.append((u.email, tok))

    return new_recipients_list


class ThreadObjectPermission(object):
    """
    Class for determining user permissions on a thread.
    """

    def check_acls(self, acl_type):
        """
        Check ACLs using Group queries.
        """
        user = self.user_profile
        obj = self.thread_obj
        if acl_type == 'moz_contact':
            return user.email == obj.addon.mozilla_contact
        elif acl_type == 'admin':
            group_name = 'Admins'
        elif acl_type == 'reviewer':
            group_name = 'App Reviewers'
        elif acl_type == 'senior_reviewer':
            group_name = 'Senior App Reviewers'
        else:
            raise 'Invalid ACL lookup.'

        return Group.objects.get(name=group_name).users.filter(
            user=user).exists()

    def user_has_permission(self, thread, profile):
        """
        Check if the user has read/write permissions on the given thread.

        Developers of the add-on used in the thread, users in the CC list,
        and users who post to the thread are allowed to access the object.

        Moreover, other object permissions are also checked agaisnt the ACLs
        of the user.
        """
        self.thread_obj = thread
        self.user_profile = profile
        user_post = CommunicationNote.objects.filter(author=profile,
            thread=thread)
        user_cc = CommunicationThreadCC.objects.filter(user=profile,
            thread=thread)

        if user_post.exists() or user_cc.exists():
            return True

        # User is a developer of the add-on and has the permission to read.
        user_is_author = profile.addons.filter(pk=thread.addon_id)
        if thread.read_permission_developer and user_is_author.exists():
            return True

        if thread.read_permission_reviewer and self.check_acls('reviewer'):
            return True

        if (thread.read_permission_senior_reviewer and self.check_acls(
            'senior_reviewer')):
            return True

        if (thread.read_permission_mozilla_contact and self.check_acls(
            'moz_contact')):
            return True

        if thread.read_permission_staff and self.check_acls('admin'):
            return True

        return False


class CommEmailParser():
    """Utility to parse email replies."""

    address_prefix = 'reply+'

    def __init__(self, email_text):
        self.email_text = EmailReplyParser.read(email_text).reply
        self.headers = self._parse_headers()

    def _parse_headers(self):
        headers = {}
        in_pos = self.email_text.find('\n\n')
        header_lines = self.email_text[:in_pos].split('\n')

        for line in header_lines:
            col_pos = line.find(':')
            key = line[:col_pos].strip().lower()
            value = line[col_pos+1:].strip()
            headers[key] = value

        return headers

    def _parse_address_line(self):
        address_line = self.headers['to']
        address_in = address_line.find('<')
        address_end = address_line.find('>')

        name = address_line[:address_in].strip()
        address = address_line[address_in + 1: address_end]
        return (name, address)

    def get_uuid(self):
        name, addr = self._parse_address_line()
        if self.address_prefix in addr:
            uuid = addr[len(self.address_prefix): addr.find('@')]
        else:
            raise Exception('Error parsing UUID in address %s' % addr)

        return uuid

    def get_body(self):
        body_in = self.email_text.find('\n\n')
        return self.email_text[body_in + 2:]


def save_from_email_reply(reply_text):
    parser = CommEmailParser(reply_text)
    uuid = parser.get_uuid()

    try:
        tok = CommunicationThreadToken.objects.get(uuid=uuid)
        if ThreadObjectPermission().user_has_permission(tok.thread, tok.user):
            CommunicationNote.obejcts.create(note_type=comm.NO_ACTION)
                thread=tok.thread, author=tok.user, body=parser.get_body())
        else:
            tok.delete()
            raise Exception('The user is not permitted anymore.')
    except:
        raise Exception('Looks like %s its not valid reply token' % uuid)
