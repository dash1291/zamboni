import logging
from celeryutils import task

from comm.models import CommunicationNoteRead
from comm.utils import (filter_notes_by_read_status, get_recipients,
                        save_from_email_reply)


log = logging.getLogger('z.task')


@task
def consume_email(email_text, **kwargs):
    """Parse emails and save notes."""
    res = save_from_email_reply(email_text)
    if not res:
        log.error('Failed to save email.')


@task
def mark_thread_read(thread, user, **kwargs):
    """This marks each unread note in a thread as read - in bulk."""
    object_list = []
    unread_notes = filter_notes_by_read_status(thread.notes, user, False)

    for note in unread_notes:
        object_list.append(CommunicationNoteRead(note=note, user=user))

    CommunicationNoteRead.objects.bulk_create(object_list)


@task
def send_note_emails(note, send_mail_func, data={}, **kwargs):
    recipients = get_recipients(note, False)
    name = note.thread.addon.name
    data.update({
        'name': name,
        'sender': note.author.name,
        'comments': note.body,
        'thread_id': str(note.thread.id)
    })
    for email, tok in recipients:
        reply_to = 'reply+%s@mozilla.org' % tok
        subject = u'%s has been reviewed.' % name
        send_mail_func(subject, 'reviewers/emails/decisions/post.txt', data,
                       [email], perm_setting='app_reviewed', reply_to=reply_to)
