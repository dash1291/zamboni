from django.core.urlresolvers import reverse

from nose.tools import eq_

from addons.models import Addon, AddonUser
from amo.tests import TestCase
from comm.models import (CommunicationNote, CommunicationThread,
                         CommunicationThreadCC)
from mkt.api.tests.test_oauth import RestOAuth
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp
from users.models import UserProfile


class TestThread(RestOAuth):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestThread, self).setUp()
        self.addon = Webapp.objects.get(pk=337141)

    def test_response(self):
        thread = CommunicationThread.objects.create(addon=self.addon)
        note = CommunicationNote.objects.create(thread=thread,
            author=self.profile, note_type=0)
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        eq_(res.status_code, 200)
        eq_(len(res.json['notes']), 1)

    def test_cc(self):
        thread = CommunicationThread.objects.create(addon=self.addon)
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        # Test with no CC.
        eq_(res.status_code, 403)

        # Test with CC created.
        cc = CommunicationThreadCC.objects.create(thread=thread,
            user=self.profile)
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        eq_(res.status_code, 200)

    def test_read_public(self):
        thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_public=True)
        thread.save()
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        eq_(res.status_code, 200)

    def test_read_developer(self):
        thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_developer=True)
        AddonUser.objects.create(addon=self.addon, user=self.profile)
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        eq_(res.status_code, 200)

    def test_read_moz_contact(self):
        thread = CommunicationThread.objects.create(addon=self.addon,
            read_permission_mozilla_contact=True)
        thread.addon.mozilla_contact = self.user.email
        thread.addon.save()
        res = self.client.get(reverse('comm-thread-detail',
                                      kwargs={'pk': thread.pk}))
        eq_(res.status_code, 200)        
             
    """
    def test_read_reviewer(self):


    def test_read_senior_reviewer(self):


    def test_read_staff(self):
    """
