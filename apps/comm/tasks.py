from celeryutils import task
import logging

from amo.storage_utils import walk_storage
from comm.utils import save_from_email_reply


log = logging.getLogger('z.task')


# TODO: Set this constant when value is available.
EMAILS_DIRECTORY = 'emails_dir'

@task
def consume_emails():
    for path, names, filenames in walk_storage(directory):
        for f in filenames:
            file_path = os.path.join(path, f)
            log.info('parsing email reply in file: %s' % file_path)
            save_from_email_reply(open(file_path).read())
