import json
from datetime import datetime

from django.contrib.auth.models import User

from mock import patch
from nose.tools import eq_, ok_

import amo
import mkt.regions
from addons.models import (AddonCategory, AddonDeviceType, AddonUpsell,
                           Category)
from amo.tests import app_factory, ESTestCase
from market.models import AddonPremium, Price, PriceCurrency
from stats.models import ClientData
from users.models import UserProfile

from mkt.api.base import list_url
from mkt.api.models import Access, generate
from mkt.api.tests.test_oauth import BaseOAuth, OAuthClient
from mkt.constants.features import FeatureProfile
from mkt.search.forms import DEVICE_CHOICES_IDS
from mkt.site.fixtures import fixture
from mkt.webapps.models import Installed, Webapp


class TestApi(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.create_switch('search-api-es')
        self.client = OAuthClient(None)
        self.url = list_url('search')
        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)
        self.webapp.save()
        self.refresh('webapp')

    def test_verbs(self):
        self._allowed_verbs(self.url, ['get'])

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.url), 'get')

    def test_meta(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(set(res.json.keys()), set(['objects', 'meta']))
        eq_(res.json['meta']['total_count'], 1)

    def test_wrong_category(self):
        res = self.client.get(self.url + ({'cat': self.category.pk + 1},))
        eq_(res.status_code, 400)
        eq_(res['Content-Type'], 'application/json')

    def test_wrong_weight(self):
        self.category.update(weight=-1)
        res = self.client.get(self.url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 0)

    def test_wrong_sort(self):
        res = self.client.get(self.url + ({'sort': 'awesomeness'},))
        eq_(res.status_code, 400)

    def test_right_category(self):
        res = self.client.get(self.url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        eq_(res.json['objects'], [])

    def create(self):
        AddonCategory.objects.create(addon=self.webapp, category=self.category)
        self.webapp.save()
        self.refresh('webapp')

    def test_right_category_present(self):
        self.create()
        res = self.client.get(self.url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 1)

    def test_dehydrate(self):
        with self.settings(SITE_URL=''):
            self.create()
            res = self.client.get(self.url + ({'cat': self.category.pk},))
            eq_(res.status_code, 200)
            obj = res.json['objects'][0]
            eq_(obj['absolute_url'], self.webapp.get_absolute_url())
            eq_(obj['app_type'], self.webapp.app_type)
            eq_(obj['content_ratings'], None)
            eq_(obj['current_version']['version'], u'1.0')
            eq_(obj['description'], unicode(self.webapp.description))
            eq_(obj['icons']['128'], self.webapp.get_icon_url(128))
            eq_(obj['id'], str(self.webapp.id))
            eq_(obj['manifest_url'], self.webapp.get_manifest_url())
            eq_(obj['payment_account'], None)
            eq_(obj['privacy_policy'], '/api/v1/apps/app/337141/privacy/')
            eq_(obj['public_stats'], self.webapp.public_stats)
            eq_(obj['ratings'], {'average': 0.0, 'count': 0})
            eq_(obj['resource_uri'], '/api/v1/apps/app/337141/')
            eq_(obj['slug'], self.webapp.app_slug)
            eq_(obj['summary'], u'')
            eq_(obj['supported_locales'], ['en-US', 'es', 'pt-BR'])

            # These only exists if requested by a reviewer.
            ok_('latest_version_status' not in obj)
            ok_('reviewer_flags' not in obj)

    def test_upsell(self):
        upsell = app_factory()
        AddonUpsell.objects.create(free=self.webapp, premium=upsell)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['upsell']['id'], upsell.id)
        eq_(obj['upsell']['app_slug'], upsell.app_slug)
        eq_(obj['upsell']['name'], upsell.name)
        eq_(obj['upsell']['icon_url'], upsell.get_icon_url(128))
        eq_(obj['upsell']['resource_uri'], '/api/v1/apps/app/%s/' % upsell.id)

    def test_dehydrate_regions(self):
        self.webapp.addonexcludedregion.create(region=mkt.regions.BR.id)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        regions = obj['regions']
        ok_(mkt.regions.BR.slug not in [r['slug'] for r in regions])
        eq_(len(regions), len(mkt.regions.ALL_REGION_IDS) - 1)

    def test_q(self):
        res = self.client.get(self.url + ({'q': 'something'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_name_localized(self):
        res = self.client.get(self.url + ({'q': 'something',
                                           'lang': 'es'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)
        eq_(obj['name'], u'Algo Algo Steamcube!')

    def test_name_localized_to_default_locale(self):
        self.webapp.update(default_locale='es')
        self.refresh('webapp')

        # Make a request in another language that we know will fail.
        res = self.client.get(self.url + ({'q': 'something',
                                           'lang': 'de'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)
        eq_(obj['name'], u'Algo Algo Steamcube!')

    def test_device(self):
        AddonDeviceType.objects.create(
            addon=self.webapp, device_type=DEVICE_CHOICES_IDS['desktop'])
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url + ({'device': 'desktop'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_no_flash_on_firefoxos(self):
        AddonDeviceType.objects.create(
            addon=self.webapp, device_type=DEVICE_CHOICES_IDS['firefoxos'])
        f = self.webapp.get_latest_file()
        f.uses_flash = True
        f.save()
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url + ({'dev': 'firefoxos'},))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 0)

    def test_premium_types(self):
        res = self.client.get(self.url + (
            {'premium_types': 'free'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_premium_types_empty(self):
        res = self.client.get(self.url + (
            {'premium_types': 'premium'},))
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

    def test_multiple_premium_types(self):
        res = self.client.get(self.url + (
            {'premium_types': 'free'},
            {'premium_types': 'premium'}))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_app_type_hosted(self):
        res = self.client.get(self.url + ({'app_type': 'hosted'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_app_type_packaged(self):
        self.webapp.update(is_packaged=True)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url + ({'app_type': 'packaged'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_status_anon(self):
        res = self.client.get(self.url + ({'status': 'public'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'status': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = res.json['error_message']
        eq_(error.keys(), ['status'])

        res = self.client.get(self.url + ({'status': 'any'},))
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'],
            'Unauthorized to filter by status.')

        res = self.client.get(self.url + ({'status': 'rejected'},))
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'],
            'Unauthorized to filter by status.')

    def test_status_value_packaged(self):
        # When packaged and not a reviewer we exclude latest version status.
        self.webapp.update(is_packaged=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['status'], amo.STATUS_PUBLIC)
        eq_('latest_version_status' in obj, False)

    def test_addon_type_anon(self):
        res = self.client.get(self.url + ({'type': 'app'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'type': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = res.json['error_message']
        eq_(error.keys(), ['type'])

        res = self.client.get(self.url + ({'type': 'theme'},))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 0)

    @patch.object(mkt.regions.US, 'supports_carrier_billing', False)
    def test_minimum_price_tier(self):
        price = Price.objects.create(name='5', price='0.50')
        PriceCurrency.objects.create(currency='BRL', price='1.00', tier=price)
        AddonPremium.objects.create(addon=self.webapp, price=price)
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url + ({'region': 'br'},))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 1)
        res2 = self.client.get(self.url + ({'region': 'us'},))
        eq_(res2.status_code, 200)
        eq_(len(res2.json['objects']), 0)

    def test_adolescent_popularity(self):
        """
        Adolescent regions use global popularity.

          Webapp:   Global: 0, Regional: 0
          Unknown1: Global: 1, Regional: 1 + 10 * 1 = 11
          Unknown2: Global: 2, Regional: 0

        """
        user = UserProfile.objects.all()[0]
        cd = ClientData.objects.create(region=mkt.regions.BR.id)

        unknown1 = amo.tests.app_factory()
        Installed.objects.create(addon=unknown1, user=user, client_data=cd)

        unknown2 = amo.tests.app_factory()
        Installed.objects.create(addon=unknown2, user=user)
        Installed.objects.create(addon=unknown2, user=user)

        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.url + ({'region': 'br'},))
        eq_(res.status_code, 200)

        objects = res.json['objects']
        eq_(len(objects), 3)

        eq_(int(objects[0]['id']), unknown2.id)
        eq_(int(objects[1]['id']), unknown1.id)
        eq_(int(objects[2]['id']), self.webapp.id)

        # Cleanup to remove these from the index.
        unknown1.delete()
        unknown2.delete()


class TestApiFeatures(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.create_switch('search-api-es')
        self.create_switch('buchets')
        self.client = OAuthClient(None)
        self.url = list_url('search')
        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)
        # A typical desktop profile on Firefox with the following features:
        # {'apps': True,
        #  'audio': True,
        #  'battery': True,
        #  'device_storage': True,
        #  'fullscreen': True,
        #  'geolocation': True,
        #  'idle': True,
        #  'indexeddb': True,
        #  'light_events': True,
        #  'network_info': True,
        #  'orientation': True,
        #  'proximity': True,
        #  'push': True,
        #  'sms': True,
        #  'vibrate': True,
        #  'video_webm': True,
        #  'webaudio': True}
        self.profile = '8a7dd46c.32.1'
        self.qs = {'q': 'something', 'pro': self.profile, 'dev': 'firefoxos'}

    def test_no_features(self):
        # Base test to make sure we find the app.
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url + (self.qs,))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_one_good_feature(self):
        # Enable an app feature that matches one in our profile.
        self.webapp.current_version.features.update(has_geolocation=True)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url + (self.qs,))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_one_bad_feature(self):
        # Enable an app feature that doesn't match one in our profile.
        self.webapp.current_version.features.update(has_pay=True)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url + (self.qs,))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)

    def test_all_good_features(self):
        # Enable app features so they exactly match our device profile.
        fp = FeatureProfile.from_signature(self.profile)
        self.webapp.current_version.features.update(
            **dict(('has_%s' % k, v) for k, v in fp.items()))
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url + (self.qs,))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_bad_profile_on_desktop(self):
        # Enable an app feature that doesn't match one in our profile.
        qs = self.qs.copy()
        del qs['dev']  # Desktop doesn't send a device.
        self.webapp.current_version.features.update(has_pay=True)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url + (qs,))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)


class TestApiReviewer(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self, api_name='apps'):
        self.create_switch('search-api-es')
        self.user = User.objects.get(pk=2519)
        self.profile = self.user.get_profile()
        self.profile.update(read_dev_agreement=datetime.now())
        self.grant_permission(self.profile, 'Apps:Review')

        self.access = Access.objects.create(
            key='test_oauth_key', secret=generate(), user=self.user)
        self.client = OAuthClient(self.access, api_name=api_name)
        self.url = list_url('search')

        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)
        self.webapp.save()
        self.refresh('webapp')

    def test_status_reviewer(self):
        res = self.client.get(self.url + ({'status': 'public'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'status': 'rejected'},))
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

        res = self.client.get(self.url + ({'status': 'any'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'status': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = res.json['error_message']
        eq_(error.keys(), ['status'])

    def test_status_value_packaged(self):
        # When packaged we also include the latest version status.
        self.webapp.update(is_packaged=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['status'], amo.STATUS_PUBLIC)
        eq_(obj['latest_version_status'], amo.STATUS_PUBLIC)

    def test_addon_type_reviewer(self):
        res = self.client.get(self.url + ({'type': 'app'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'type': 'theme'},))
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

        res = self.client.get(self.url + ({'type': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = res.json['error_message']
        eq_(error.keys(), ['type'])

    def test_extra_attributes(self):
        version = self.webapp.versions.latest()
        version.has_editor_comment = True
        version.has_info_request = True
        version.save()

        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]

        # These only exist if requested by a reviewer.
        eq_(obj['latest_version_status'], amo.STATUS_PUBLIC)
        eq_(obj['reviewer_flags']['has_comment'], True)
        eq_(obj['reviewer_flags']['has_info_request'], True)
        eq_(obj['reviewer_flags']['is_escalated'], False)


class TestFeaturedNoCategories(BaseOAuth, ESTestCase):
    fixtures = fixture('user_2519', 'webapp_337141')
    list_url = list_url('search/featured')

    def setUp(self):
        super(TestFeaturedNoCategories, self).setUp()
        self.create_switch('search-api-es')
        self.create_switch('buchets')
        self.cat = Category.objects.create(type=amo.ADDON_WEBAPP, slug='shiny')
        self.app = Webapp.objects.get(pk=337141)
        AddonCategory.objects.get_or_create(addon=self.app, category=self.cat)
        self.make_featured(app=self.app, category=None, region=mkt.regions.US)
        self.profile = '8a7dd46c.32.1'
        self.qs = {'pro': self.profile, 'dev': 'firefoxos'}

    def test_no_category(self):
        self.reindex(Webapp, 'webapp')
        res = self.client.get(self.list_url + (self.qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['featured']), 1)
        eq_(int(res.json['featured'][0]['id']), self.app.pk)

    def test_one_good_feature_no_category(self):
        """Enable an app feature that matches one in our profile."""
        self.app.current_version.features.update(has_geolocation=True)
        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.list_url + (self.qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['featured']), 1)
        eq_(int(res.json['featured'][0]['id']), self.app.pk)

    def test_one_bad_feature_no_category(self):
        """Enable an app feature that doesn't match one in our profile."""
        self.app.current_version.features.update(has_pay=True)
        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.list_url + (self.qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['featured']), 0)

    def test_all_good_features_no_category(self):
        """Enable app features so they exactly match our device profile."""
        fp = FeatureProfile.from_signature(self.profile)
        self.app.current_version.features.update(
            **dict(('has_%s' % k, v) for k, v in fp.items()))
        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.list_url + (self.qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['featured']), 1)
        eq_(int(res.json['featured'][0]['id']), self.app.pk)

    def test_non_matching_profile_desktop_no_category(self):
        """Enable unmatched feature but desktop should find it."""
        self.app.current_version.features.update(has_pay=True)
        self.reindex(Webapp, 'webapp')

        self.qs.update({'dev': ''})
        res = self.client.get(self.list_url + (self.qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['featured']), 1)
        eq_(int(res.json['featured'][0]['id']), self.app.pk)


class TestFeaturedWithCategories(BaseOAuth, ESTestCase):
    fixtures = fixture('user_2519', 'webapp_337141')
    list_url = list_url('search/featured')

    def setUp(self):
        super(TestFeaturedWithCategories, self).setUp()
        self.create_switch('search-api-es')
        self.create_switch('buchets')
        self.cat = Category.objects.create(type=amo.ADDON_WEBAPP, slug='shiny')
        self.app = Webapp.objects.get(pk=337141)
        AddonCategory.objects.get_or_create(addon=self.app, category=self.cat)
        self.make_featured(app=self.app, category=self.cat,
                           region=mkt.regions.US)
        self.profile = '8a7dd46c.32.1'
        self.qs = {'cat': 'shiny', 'pro': self.profile, 'dev': 'firefoxos'}

    def test_featured_plus_category(self):
        app2 = amo.tests.app_factory()
        AddonCategory.objects.get_or_create(addon=app2, category=self.cat)
        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.list_url + (self.qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 2)
        eq_(len(res.json['featured']), 1)
        eq_(int(res.json['featured'][0]['id']), self.app.pk)

    def test_one_good_feature_with_category(self):
        """Enable an app feature that matches one in our profile."""
        self.app.current_version.features.update(has_geolocation=True)
        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.list_url + (self.qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['featured']), 1)
        eq_(int(res.json['featured'][0]['id']), self.app.pk)

    def test_one_bad_feature_with_category(self):
        """Enable an app feature that doesn't match one in our profile."""
        self.app.current_version.features.update(has_pay=True)
        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.list_url + (self.qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['featured']), 0)

    def test_all_good_features_with_category(self):
        """Enable app features so they exactly match our device profile."""
        fp = FeatureProfile.from_signature(self.profile)
        self.app.current_version.features.update(
            **dict(('has_%s' % k, v) for k, v in fp.items()))
        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.list_url + (self.qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['featured']), 1)
        eq_(int(res.json['featured'][0]['id']), self.app.pk)

    def test_non_matching_profile_desktop_with_category(self):
        """Enable unmatched feature but desktop should find it."""
        self.app.current_version.features.update(has_pay=True)
        self.reindex(Webapp, 'webapp')

        self.qs.update({'dev': ''})
        res = self.client.get(self.list_url + (self.qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['featured']), 1)
        eq_(int(res.json['featured'][0]['id']), self.app.pk)
