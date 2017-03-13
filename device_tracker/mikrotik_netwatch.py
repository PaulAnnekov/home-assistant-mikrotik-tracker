"""
Support for Mikrotik routers.
For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/device_tracker.mikrotik/
"""
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.device_tracker import (
    DOMAIN, PLATFORM_SCHEMA, DeviceScanner)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.const import CONF_HOSTS

REQUIREMENTS = ['routeros-api==0.14']

CONF_PORT = 'port'

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_HOST, default='192.168.88.1'): cv.string,
    vol.Required(CONF_HOSTS): cv.ensure_list,
    vol.Optional(CONF_PORT, default=8728): cv.string,
    vol.Optional(CONF_PASSWORD, default='admin'): cv.string,
    vol.Optional(CONF_USERNAME, default=''): cv.string,
})


def get_scanner(hass, config):
    """Validate the configuration and return MTikScanner."""
    scanner = MikrotikDeviceScanner(config[DOMAIN])
    return scanner if scanner.success_init else None


class MikrotikDeviceScanner(DeviceScanner):
    """This class queries a Mikrotik router."""

    def __init__(self, config):
        """Initialize the scanner."""
        self.last_results = None
        self.host = config[CONF_HOST]
        self.hosts = config[CONF_HOSTS]
        self.port = config[CONF_PORT]
        self.username = config[CONF_USERNAME]
        self.password = config[CONF_PASSWORD]
        self.success_init = True

        from routeros_api import RouterOsApiPool

        # Establish a connection to the Mikrotik router.
        try:
            connection = RouterOsApiPool(self.host, username=self.port, password=self.password, port=self.port)
            self.client = connection.get_api()
            self.leases = self.client.get_resource('/ip/dhcp-server/lease').get()
            if self.leases == {}:
                self.connected = True
        except (ValueError, TypeError):
            self.client = None

        # At this point it is difficult to tell if a connection is established.
        # So just check for null objects.
        if self.client is None or not self.connected:
            self.success_init = False

        if self.success_init:
            _LOGGER.info('Successfully connected to Mikrotik device')
            self._update_info()
        else:
            _LOGGER.error('Failed to establish connection to Mikrotik device with IP: %s', self.host)

    # TODO: is there a way to throw exception and make HA don't call these methods?
    def scan_devices(self):
        self._update_info()
        active_hosts = []
        if self.last_results is None:
            return active_hosts
        for device in self.hosts:
            ip = self.hosts[device]
            dev = next((item for item in self.last_results if item['host'] == ip), None)
            if dev is None:
                _LOGGER.error('IP %s declared in "hosts", but not present in Tools - Netwatch', ip)
                continue
            lease = next((item for item in self.leases if item['address'] == dev['host']), None)
            if lease is not None:
                if dev['status'] == 'up':
                    active_hosts.append(lease["mac-address"])
            else:
                _LOGGER.error('IP %s declared in "hosts", but not present in DHCP Server - Leases. Needed to get MAC')
        return active_hosts

    def get_device_name(self, mac):
        if not self.success_init:
            return None
        lease = next((item for item in self.last_results if item['mac-address'] == mac), None)
        if "comment" in lease:
            return lease['comment']
        elif "host-name" in lease and lease["host-name"] != {}:
            return lease['host-name']
        else:
            return None

    def _update_info(self):
        """Retrieve latest information from the Mikrotik box."""
        if not self.success_init:
            return False

        _LOGGER.info('Polling')
        self.last_results = self.client.get_resource('/tool/netwatch').get()
        return True
