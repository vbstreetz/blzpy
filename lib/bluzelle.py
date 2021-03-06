import requests
import json
import base64
import random
import string
import logging
import time
import hashlib
import bech32
import math
import re
import binascii
import urllib.parse
from .mnemonic_utils import mnemonic_to_private_key
from ecdsa import SigningKey, SECP256k1

DEFAULT_ENDPOINT = "http://localhost:1317"
DEFAULT_CHAIN_ID = "bluzelle"
HD_PATH = "m/44'/118'/0'/0/0"
ADDRESS_PREFIX = "bluzelle"
TX_COMMAND = "/txs"
TOKEN_NAME = "ubnt"
PUB_KEY_TYPE = "tendermint/PubKeySecp256k1"
BROADCAST_MAX_RETRIES = 10
BROADCAST_RETRY_INTERVAL_SECONDS = 1
BLOCK_TIME_IN_SECONDS = 5

KEY_MUST_BE_A_STRING = "Key must be a string"
NEW_KEY_MUST_BE_A_STRING = "New key must be a string"
VALUE_MUST_BE_A_STRING = "Value must be a string"
ALL_KEYS_MUST_BE_STRINGS = "All keys must be strings"
ALL_VALUES_MUST_BE_STRINGS = "All values must be strings"
INVALID_LEASE_TIME = "Invalid lease time"
INVALID_VALUE_SPECIFIED = "Invalid value specified"
ADDRESS_MUST_BE_A_STRING = "address must be a string"
MNEMONIC_MUST_BE_A_STRING = "mnemonic must be a string"
UUID_MUST_BE_A_STRING = "uuid must be a string"
INVALID_TRANSACTION = "Invalid transaction."
KEY_CANNOT_CONTAIN_A_SLASH = "Key cannot contain a slash"

CHAIN_ID_MUST_BE_A_STRING = 'chain_id must be a string'
ENDPOINT_MUST_BE_A_STRING = 'endpoint must be a string'

# client option validation error
class OptionsError(Exception):
    pass

# general api error
class APIError(Exception):
    def __init__(self, msg, api_error = None, api_response = None):
        self.message = msg
        self.api_error = api_error or msg
        self.api_response = api_response

class Client:
    def __init__(self, options):
        self.options = options

    #

    def account(self):
        url = "/auth/accounts/%s" % self.address
        return self.api_query(url)['result']['value']

    def version(self):
        url = "/node_info"
        return self.api_query(url)['application_version']['version']

    # mutate methods

    def create(self, key, value, gas_info, lease_info = None):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        if type(value) != str:
            raise APIError(VALUE_MUST_BE_A_STRING)
        payload = { "Key": key }
        if lease_info != None:
            lease = Client.lease_info_to_blocks(lease_info)
            if lease < 0:
                raise APIError(INVALID_LEASE_TIME)
            payload["Lease"] = str(lease)
        payload["Value"] = value
        return self.send_transaction("post", "/crud/create", payload, gas_info)

    def update(self, key, value, gas_info, lease_info = None):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        if type(value) != str:
            raise APIError(VALUE_MUST_BE_A_STRING)
        payload = { "Key": key }
        if lease_info != None:
            lease = Client.lease_info_to_blocks(lease_info)
            if lease < 0:
                raise APIError(INVALID_LEASE_TIME)
            payload["Lease"] = str(lease)
        payload["Value"] = value
        return self.send_transaction("post", "/crud/update", payload, gas_info)

    def delete(self, key, gas_info):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        return self.send_transaction("delete", "/crud/delete", {
            "Key": key,
        }, gas_info)

    def rename(self, key, new_key, gas_info):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        if type(new_key) != str:
            raise APIError(NEW_KEY_MUST_BE_A_STRING)
        Client.validate_key(new_key)
        return self.send_transaction("post", "/crud/rename", {
            "Key": key,
            "NewKey": new_key,
        }, gas_info)

    def delete_all(self, gas_info):
        return self.send_transaction("post", "/crud/deleteall", {}, gas_info)

    def multi_update(self, payload, gas_info):
      return self.send_transaction("post", "/crud/multiupdate", {"KeyValues": payload}, gas_info)

    def renew_lease(self, key, gas_info, lease_info = None):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        payload = {
            "Key": key,
        }
        if lease_info != None:
            lease = Client.lease_info_to_blocks(lease_info)
            if lease < 0:
                raise APIError(INVALID_LEASE_TIME)
            payload["Lease"] = str(lease)
        self.send_transaction("post", "/crud/renewlease", payload, gas_info)

    def renew_all_leases(self, *args, **kwargs):
        return self.renew_lease_all(*args, **kwargs)

    def renew_lease_all(self, gas_info, lease_info = None):
        payload = {}
        if lease_info != None:
            lease = Client.lease_info_to_blocks(lease_info)
            if lease < 0:
                raise APIError(INVALID_LEASE_TIME)
            payload["Lease"] = str(lease)
        self.send_transaction("post", "/crud/renewleaseall", payload, gas_info)

    # query methods

    def read(self, key, proof = None):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        key = Client.encode_safe(key)
        if proof:
            url = "/crud/pread/{uuid}/{key}".format(uuid=self.options["uuid"], key=key)
        else:
            url = "/crud/read/{uuid}/{key}".format(uuid=self.options["uuid"], key=key)
        return self.api_query(url)['result']['value']

    def has(self, key):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        url = "/crud/has/{uuid}/{key}".format(uuid=self.options["uuid"], key=Client.encode_safe(key))
        return self.api_query(url)['result']['has']

    def count(self):
        url = "/crud/count/{uuid}".format(uuid=self.options["uuid"])
        return int(self.api_query(url)['result']['count'])

    def keys(self):
        url = "/crud/keys/{uuid}".format(uuid=self.options["uuid"])
        return self.api_query(url)['result']['keys']

    def key_values(self):
        url = "/crud/keyvalues/{uuid}".format(uuid=self.options["uuid"])
        return self.api_query(url)['result']['keyvalues']

    def get_lease(self, key):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        url = "/crud/getlease/{uuid}/{key}".format(uuid=self.options["uuid"], key=Client.encode_safe(key))
        return Client.lease_blocks_to_seconds(int(self.api_query(url)['result']['lease']))

    def get_n_shortest_leases(self, n):
        if n < 0:
            raise APIError(INVALID_VALUE_SPECIFIED)
        url = "/crud/getnshortestleases/{uuid}/{n}".format(uuid=self.options["uuid"], n=str(n))
        kls = self.api_query(url)['result']['keyleases']
        for kl in kls:
            kl["lease"] = Client.lease_blocks_to_seconds(int(kl["lease"]))
        return kls

    #query tx methods
    def tx_read(self, key, gas_info):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        res = self.send_transaction("post", "/crud/read", {
            "Key": key,
        }, gas_info)
        return res['value']

    def tx_has(self, key, gas_info):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        res = self.send_transaction("post", "/crud/has", {
            "Key": key,
        }, gas_info)
        return res['has']

    def tx_count(self, gas_info):
        res = self.send_transaction("post", "/crud/count", {}, gas_info)
        return int(res['count'])

    def tx_keys(self, gas_info):
        res = self.send_transaction("post", "/crud/keys", {}, gas_info)
        return res['keys']

    def tx_key_values(self, gas_info):
        res = self.send_transaction("post", "/crud/keyvalues", {}, gas_info)
        return res['keyvalues']

    def tx_get_lease(self, key, gas_info):
        if type(key) != str:
            raise APIError(KEY_MUST_BE_A_STRING)
        Client.validate_key(key)
        res = self.send_transaction("post", "/crud/getlease", {
            "Key": key,
        }, gas_info)
        return Client.lease_blocks_to_seconds(int(res['lease']))

    def tx_get_n_shortest_leases(self, n, gas_info):
        if n < 0:
            raise APIError(INVALID_VALUE_SPECIFIED)
        res = self.send_transaction("post", "/crud/getnshortestleases", {
            "N": str(n),
        }, gas_info)
        kls = res['keyleases']
        for kl in kls:
            kl["lease"] = Client.lease_blocks_to_seconds(int(kl["lease"]))
        return kls

    # api
    def api_query(self, endpoint):
        url = self.options['endpoint'] + endpoint
        self.logger.debug('querying url(%s)...' % (url))
        response = requests.get(url)
        error = self.get_response_error(response)
        if error:
            raise error
        data = response.json()
        self.logger.debug('response (%s)...' % (data))
        return data

    def api_mutate(self, method, endpoint, payload):
        url = self.options['endpoint'] + endpoint
        self.logger.debug('mutating url({url}), method({method})...'.format(url=url, method=method))
        payload = self.json_dumps(payload)
        self.logger.debug("%s" % payload)
        response = getattr(requests, method)(
            url,
            data=payload,
            headers={"content-type": "application/json"},
            verify=False
        )
        self.logger.debug("%s" % response.text)
        error = self.get_response_error(response)
        if error:
            raise error
        data = response.json()
        self.logger.debug('response (%s)...' % (data))
        return data

    def send_transaction(self, method, endpoint, payload, gas_info):
        self.broadcast_retries = 0
        txn = self.validate_transaction(method, endpoint, payload)
        return self.broadcast_transaction(txn, gas_info)

    def validate_transaction(self, method, endpoint, payload):
        payload.update({
            "BaseReq": {
                "chain_id": self.options['chain_id'],
                "from": self.address,
            },
            "Owner": self.address,
            "UUID": self.options['uuid'],
        })
        return self.api_mutate(method, endpoint, payload)['value']

    def broadcast_transaction(self, txn, gas_info):
        # set txn memo
        txn['memo'] = Client.make_random_string(32)

        # set txn gas
        Client.validate_gas_info(gas_info)

        fee = txn['fee']
        gas = int(fee['gas'])
        amount = 0
        if len(fee.get('amount', [])) > 0:
            amount = int(fee['amount'][0]['amount'])

        max_gas = gas_info.get('max_gas', 0)
        max_fee = gas_info.get('max_fee', 0)
        gas_price = gas_info.get('gas_price', 0)

        if max_gas != 0 and gas > max_gas:
            gas = max_gas
        if max_fee != 0:
            amount = max_fee
        elif gas_price != 0:
            amount = gas * gas_price

        txn['fee'] = {
            'gas': str(gas),
            'amount': [{ 'denom': TOKEN_NAME, 'amount': str(amount)}]
        }

        # sign
        self.logger.warning( self.get_pub_key_string())
        txn['signatures'] = [{
            "pub_key": {
                "type": PUB_KEY_TYPE,
                "value": self.get_pub_key_string()
            },
            "signature": self.sign_transaction(txn),
            "account_number": str(self.bluzelle_account['account_number']),
            "sequence": str(self.bluzelle_account['sequence'])
        }]

        # broadcast
        payload = {
            "tx": txn,
            "mode": "block"
        }
        response = self.api_mutate(
            "post",
            TX_COMMAND,
            payload
        )

        # https://github.com/bluzelle/blzjs/blob/45fe51f6364439fa88421987b833102cc9bcd7c0/src/swarmClient/cosmos.js#L240-L246
        # note - as of right now (3/6/20) the responses returned by the Cosmos REST interface now look like this:
        # success case: {"height":"0","txhash":"3F596D7E83D514A103792C930D9B4ED8DCF03B4C8FD93873AB22F0A707D88A9F","raw_log":"[]"}
        # failure case: {"height":"0","txhash":"DEE236DEF1F3D0A92CB7EE8E442D1CE457EE8DB8E665BAC1358E6E107D5316AA","code":4,
        #  "raw_log":"unauthorized: signature verification failed; verify correct account sequence and chain-id"}
        #
        # this is far from ideal, doesn't match their docs, and is probably going to change (again) in the future.
        if not ('code' in response):
            self.bluzelle_account['sequence'] += 1
            if 'data' in response:
                return json.loads(bytes.fromhex(response['data']).decode("ascii"))
            return

        raw_log = response['raw_log']
        if "signature verification failed" in raw_log:
            self.broadcast_retries += 1
            self.logger.warning("transaction failed ... retrying(%i) ...", self.broadcast_retries)
            if self.broadcast_retries >= BROADCAST_MAX_RETRIES:
                raise APIError("transaction failed after max retry attempts", response)
            time.sleep(BROADCAST_RETRY_INTERVAL_SECONDS)
            # lookup changed sequence
            self.set_account()
            return self.broadcast_transaction(txn, gas_info)

        raise APIError(raw_log, response)

    def sign_transaction(self, txn):
        payload = {
            "account_number": str(self.bluzelle_account['account_number']),
            "chain_id": self.options['chain_id'],
            "fee": txn["fee"],
            "memo": txn["memo"],
            "msgs": txn["msg"],
            "sequence": str(self.bluzelle_account['sequence']),
        }
        payload = Client.sanitize_string(self.json_dumps(payload))
        self.logger.debug("sign %s" % payload)
        payload = bytes(payload, 'utf-8')
        return base64.b64encode(self.private_key.sign_deterministic(payload, hashfunc=hashlib.sha256)).decode("utf-8")

    def set_account(self):
        self.bluzelle_account = self.account()

    def get_response_error(self, response):
        jsonError = response.json()
        error = jsonError.get('error', '')
        if error:
            return APIError(error, jsonError, response)

    def get_pub_key_string(self):
        return base64.b64encode(self.private_key.verifying_key.to_string("compressed")).decode("utf-8")

    def json_dumps(self, payload):
        return json.dumps(payload, sort_keys=True, separators=(',', ':'))

    @classmethod
    def sanitize_string(cls, s):
        return re.sub(r"([&<>])", Client.sanitize_string_token, s)

    @classmethod
    def sanitize_string_token(cls, m):
        return u"\\u00" + binascii.hexlify(m.group(0).encode('ascii')).decode()

    @classmethod
    def encode_safe(cls, s):
        a = urllib.parse.quote(s, safe='~@#$&()*!+=:;,.?/\'')
        b = re.sub(r"([\#\?])", Client.encode_safe_token, a)
        return b

    @classmethod
    def encode_safe_token(cls, m):
        return u"%" + binascii.hexlify(m.group(0).encode('ascii')).decode()

    @classmethod
    def make_random_string(cls, size):
        return ''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(size))

    def setup_logging(self):
        logger = logging.getLogger('bluzelle')
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        logger.disabled = not self.options['debug']
        self.logger = logger

    def set_private_key(self):
        self.private_key = SigningKey.from_string(
            mnemonic_to_private_key(self.options['mnemonic'], str_derivation_path=HD_PATH),
            curve=SECP256k1
        )

    def set_address(self):
        pk = self.private_key.verifying_key.to_string("compressed")

        h = hashlib.new('sha256')
        h.update(pk)
        s = h.digest()

        h = hashlib.new('ripemd160')
        h.update(s)
        r = h.digest()

        self.address = bech32.bech32_encode(ADDRESS_PREFIX, bech32.convertbits(r, 8, 5, True))

    @classmethod
    def lease_info_to_blocks(cls, lease_info):
        if lease_info == None:
          raise OptionsError('provided lease info is nil')

        if type(lease_info) is not dict:
          raise OptionsError('lease_info should be a dict of {days, hours, minutes, seconds}')

        days = lease_info.get('days', 0)
        hours = lease_info.get('hours', 0)
        minutes = lease_info.get('minutes', 0)
        seconds = lease_info.get('seconds', 0)

        if seconds and type(seconds) is not int:
            raise OptionsError('lease_info[seconds] should be an int')

        if minutes and type(minutes) is not int:
            raise OptionsError('lease_info[minutes] should be an int')

        if hours and type(hours) is not int:
            raise OptionsError('lease_info[hours] should be an int')

        if days and type(days) is not int:
            raise OptionsError('lease_info[days] should be an int')


        seconds += days * 24 * 60 * 60
        seconds += hours * 60 * 60
        seconds += minutes * 60
        return math.floor(seconds / BLOCK_TIME_IN_SECONDS)

    @classmethod
    def lease_blocks_to_seconds(cls, blocks):
        return blocks * BLOCK_TIME_IN_SECONDS

    @classmethod
    def validate_gas_info(cls, gas_info):
        if gas_info == None:
            return OptionsError('gas_info is required')
        if type(gas_info) is not dict:
            raise OptionsError('gas_info should be a dict of {gas_price, max_fee, max_gas}')
        gas_info_keys = ["gas_price", "max_fee", "max_gas"]
        for k in gas_info_keys:
            v = gas_info.get(k, 0)
            if type(v) is not int:
                raise OptionsError('gas_info[%s] should be an int' % k)
            gas_info[k] = v
        return gas_info

    @classmethod
    def validate_option(cls, options, option_name, err_msg, default = ''):
        val = options.get(option_name, None)
        if not val:
            val = default
        if type(val) != str:
            raise OptionsError(err_msg)
        if not val:
            raise OptionsError('%s is required' % option_name)
        options[option_name] = val

    @classmethod
    def validate_key(cls, key):
        if '/' in key:
            raise OptionsError(KEY_CANNOT_CONTAIN_A_SLASH)
    
# initialize new client with provided `options`
# @param options
#   @required mnemonic
#   @optional chain_id
#   @optional endpoint
#   @optional gas_info
#   @optional debug
def new_client(options):
    # validate options

    if not ('debug' in options):
        options['debug'] = False
    Client.validate_option(options, 'mnemonic', MNEMONIC_MUST_BE_A_STRING)
    Client.validate_option(options, 'uuid', UUID_MUST_BE_A_STRING)
    Client.validate_option(options, 'chain_id', CHAIN_ID_MUST_BE_A_STRING, DEFAULT_CHAIN_ID)
    Client.validate_option(options, 'endpoint', ENDPOINT_MUST_BE_A_STRING, DEFAULT_ENDPOINT)

    client = Client(options)

    # logging
    client.setup_logging()

    # private key
    client.set_private_key()

    # set address
    client.set_address()

    # account
    client.set_account()

    return client
