from django.conf import settings

import commonware.log
import waffle

from access.models import Group
from amo.helpers import absolutify
from amo.utils import send_mail_jinja
from comm.models import CommunicationThreadToken
from users.models import UserProfile


log = commonware.log.getLogger('comm')


def get_reply_token(thread, user):
    tok, created = CommunicationThreadToken.objects.get_or_create(
        thread=thread, user=user)

    # Reset the use count if the token already exists.
    if not created:
        tok.use_count = 0
        tok.save()

    log.info('Created token with UUID %s for user_id: %s.' %
             (tok.uuid, user))
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
