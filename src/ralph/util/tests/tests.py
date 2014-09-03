#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Common utilities tests. Requirements:

 * Internet access with working DNS

 * tests ran by root or bin/python setuid or bin/python setcap CAP_NET_RAW
   (this is required because there's a pure Python ping implementation used)
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from datetime import datetime, timedelta, date
import re
import textwrap

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from tastypie.models import ApiKey
from unittest import skip

from ralph.business.models import Venture
from ralph.discovery.models import (
    ComponentModel,
    ComponentModelGroup,
    ComponentType,
    DeprecationKind,
    Device,
    DeviceModelGroup,
    DeviceType,
    DiskShare,
    DiskShareMount,
    IPAddress,
    MarginKind,
    PricingAggregate,
    PricingFormula,
    PricingGroup,
    PricingValue,
    PricingVariable,
)
from ralph.util import api_pricing


EXISTING_DOMAIN = settings.SANITY_CHECK_PING_ADDRESS
NON_EXISTENT_DOMAIN = 'nxdomain.allegro.pl'
NON_EXISTENT_HOST_IP = '11.255.255.254'

IP2HOST_IP = settings.SANITY_CHECK_IP2HOST_IP
IP2HOST_HOSTNAME_REGEX = settings.SANITY_CHECK_IP2HOST_HOSTNAME_REGEX

THROTTLE_AT = settings.API_THROTTLING['throttle_at']


class NetworkTest(TestCase):

    @skip('uses external resources')
    # @skipIf(sys.platform in ('darwin',), "Ping on MacOS X requires root.")
    def test_ping(self):
        from ralph.util.network import ping
        # existing domain; big timeout for running tests through GPRS
        msg = textwrap.dedent("""
            {} is not pingable from Python. Things you might want to check:
            * are you connected to the Internet
            * is this domain pingable from your terminal
            * is your python binary capped with setcap CAP_NET_RAW
              or
            * are you running tests from root
              or
            * are you using setuid bin/python""".format(
            EXISTING_DOMAIN)).strip()
        self.assertIsNotNone(ping(EXISTING_DOMAIN, 2), msg)
        self.assertTrue(ping(EXISTING_DOMAIN, 2) > 0)
        # non-existent domain
        self.assertIsNone(ping(NON_EXISTENT_DOMAIN))
        # non-pingable host
        self.assertIsNone(ping(NON_EXISTENT_HOST_IP))

    @skip('uses external resources')
    def test_hostname(self):
        from ralph.util.network import hostname
        # existing host
        self.assertIsNotNone(hostname(IP2HOST_IP))
        self.assertIsNotNone(re.match(IP2HOST_HOSTNAME_REGEX,
                                      hostname(IP2HOST_IP)))
        # non-existent host
        self.assertIsNone(hostname(NON_EXISTENT_HOST_IP))


class ApiTest(TestCase):

    def setUp(self):
        cache.delete("api_user_accesses")

    def _save_ventures(self, count):
        id_list = []
        for i in range(0, count):
            v = Venture(name=i, symbol=i)
            v.save()
            id_list.append(v.id)
        return id_list

    def test_throttling(self):
        user = User.objects.create_user(
            'api_user',
            'test@mail.local',
            'password'
        )
        user.save()
        api_key = ApiKey.objects.get(user=user)
        data = {
            'format': 'json',
            'username': user.username,
            'api_key': api_key.key
        }
        status_list = []
        id_list = self._save_ventures(THROTTLE_AT + 2)

        for id in id_list:
            path = "/api/v0.9/venture/%s" % id
            response = self.client.get(path=path, data=data, follow=True)
            status_list.append(response.status_code)
        gen_list = [200 for x in range(0, THROTTLE_AT)]
        gen_list.append(429)
        gen_list.append(429)
        self.maxDiff = None
        self.assertListEqual(gen_list, status_list)


class ApiPricingTest(TestCase):

    def setUp(self):
        self.venture, created = Venture.objects.get_or_create(
            name="Sample venture",
        )
        self.venture.save()

        self.device, created = Device.objects.get_or_create(
            name="Device1",
            venture=self.venture,
        )
        self.device_without_venture, created = Device.objects.get_or_create(
            name="Device2",
        )

        self.ip1 = IPAddress(address='1.1.1.1', device=self.device)
        self.ip2 = IPAddress(address='2.2.2.2', venture=self.venture)
        self.ip1.save()
        self.ip2.save()

        self.device.save()
        self.device_without_venture.save()

    def test_get_device_by_name_with_venture(self):
        # device with venture
        device1 = api_pricing.get_device_by_name("Device1")
        self.assertEqual(device1['device_id'], self.device.id)
        self.assertEqual(device1['venture_id'], self.venture.id)

    def test_get_device_by_name_without_venture(self):
        # device without venture
        device2 = api_pricing.get_device_by_name("Device2")
        self.assertEqual(device2['device_id'], self.device_without_venture.id)
        self.assertIsNone(device2['venture_id'])

    def test_get_device_by_name_wrong_name(self):
        # device does not exist
        device3 = api_pricing.get_device_by_name("Device3")
        self.assertEqual(device3, {})

    def test_get_ip_info(self):
        result = api_pricing.get_ip_info(ipaddress='1.1.1.1')
        self.assertEquals(result, {
            'device_id': self.device.id,
            'venture_id': self.venture.id,
        })

    def test_get_ip_info_without_device(self):
        result = api_pricing.get_ip_info(ipaddress='2.2.2.2')
        self.assertEquals(result, {
            'venture_id': self.venture.id,
        })

    def test_get_ip_info_empty(self):
        result = api_pricing.get_ip_info(ipaddress='3.3.3.3')
        self.assertEquals(result, {})


class UncompressBase64DataTest(TestCase):

    def test_base64_encoded_data(self):
        import base64
        from ralph.util import uncompress_base64_data

        raw = "Zażółć gęślą jaźń.".encode('utf8')
        encoded = base64.b64encode(raw)
        self.assertEqual(uncompress_base64_data(encoded), raw)

    def test_zlib_compressed_data(self):
        import zlib
        from ralph.util import uncompress_base64_data

        raw = "Zażółć gęślą jaźń.".encode('utf8')
        compressed = zlib.compress(raw)
        self.assertEqual(uncompress_base64_data(compressed), raw)

    def test_base64_encoded_zlib_compressed_data(self):
        import base64
        import zlib
        from ralph.util import uncompress_base64_data

        raw = "Zażółć gęślą jaźń.".encode('utf8')
        compressed = zlib.compress(raw)
        encoded = base64.b64encode(compressed)
        self.assertEqual(uncompress_base64_data(encoded), raw)

    def test_wrong_way__zlib_compressed_base64_encoded_data(self):
        """Here the input is made by zlib(base64(raw_data)) instead of
        base64(zlib(raw_data)). uncompress_base64_data should return
        the base64 representation."""
        import base64
        import zlib
        from ralph.util import uncompress_base64_data

        raw = "Zażółć gęślą jaźń.".encode('utf8')
        encoded = base64.b64encode(raw)
        compressed = zlib.compress(encoded)
        self.assertEqual(uncompress_base64_data(compressed), encoded)
