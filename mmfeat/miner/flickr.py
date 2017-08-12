'''
Flickr Search API miner

Text search is happening in the following way (from: https://www.flickr.com/services/api/flickr.photos.search.html):
    Photos who's title, description or tags contain the text will be returned.
    You can exclude results that match a term by prepending it with a - character.
'''

import os
import sys
import json
import pickle
from urllib import urlencode
import re
import time
import datetime

from .base import BaseMiner

try:
    from requests_oauthlib import OAuth1Session
except ImportError:
    import warnings
    warnings.warn('Could not find requests_oauthlib. You will not be able to use the Flickr miner.')

class FlickrResult(object):

    def __init__(self, result):
        for k, v in result.items():
            self.__setattr__(k, v)
        self.url = self._get_photo_url(result)
        self.format = 'image/jpg'

    def _get_photo_url(self, photo):
        return "http://farm{}.static.flickr.com/{}/{}_{}.jpg".format(photo['farm'], photo['server'], photo['id'], photo['secret'])


class FlickrMiner(BaseMiner):
    def __init__(self, save_dir, config_path='./miner.yaml'):
        super(FlickrMiner, self).__init__(save_dir, config_path)
        self.__engine__ = 'bing'

        self.api_key, self.api_secret = zip(*map(lambda k: k.split(';'), self.config['flickr']['api-keys']))
        self.format_url = '{}{}/?method=flickr.photos.search&{}'

        self.host = 'http://flickr.com/services'
        self.api = '/rest'
        self.MAXPERPAGE = 500

        self.oauth_file = os.path.dirname(config_path) + '/oauth.pkl'
        if os.path.exists(self.oauth_file):
            with open(self.oauth_file, 'r') as f:
                self.oauth = pickle.load(f)
        else:
            self.oauth = self._do_oauth()

    def getUrl(self, query, limit, page, start_date=None, end_date=None):
        params = {'text': query, 'format': 'json', 'page': page, 'per_page': min(self.MAXPERPAGE, limit),
                  'sort': 'relevance'}
        if start_date is not None:
            params['min_upload_date'] = start_date
        if end_date is not None:
            params['max_upload_date'] = end_date
        return self.format_url.format(self.host, self.api, urlencode(self._prepare_params(params)))

    def _prepare_params(self, params):
        """Convert lists to strings with ',' between items."""
        for key, value in params.items():
            if isinstance(value, list):
                params[key] = ','.join([item for item in value])
        return params

    def _search(self, query, limit=20, page=1, start_date=None, end_date=None):
        url = self.getUrl(query, limit, page, start_date, end_date)
        r = self.oauth.get(url)
        try:
            content = re.sub('jsonFlickrApi\(', '', r.content[:-1])
            content = json.loads(content)
            results = content['photos']
        except ValueError:
            print('ERR: Request returned with code %s (%s)' % (r.status_code, r.text))
            sys.exit()

        total = int(results['total'])
        next_page = page + 1 if page < results['pages'] else False
        return [FlickrResult(res) for res in results['photo']], next_page, total


    def search(self, query, limit=20):
        FLICKR_API_LIMIT = 4000

        flickr_start_date = int(datetime.date(2004,1,1).strftime("%s"))
        current_date = int(time.time())
        date_ranges = [(flickr_start_date, current_date)]
        target_date_ranges = []

        # build results by progressively dividing date range
        total_results = 0
        while not (total_results > limit or date_ranges == [] ):
            results, next_page, total = self._search(query, limit, 1, date_ranges[-1][0], date_ranges[-1][1])
            total_results += min(total, FLICKR_API_LIMIT)

            if total > FLICKR_API_LIMIT:
                total_results -= FLICKR_API_LIMIT
                # pop original date range from list
                date_range = date_ranges.pop()
                mid_date = (date_range[0] + date_range[1] ) / 2
                # push binary division of date range onto list
                date_ranges.append((date_range[0], mid_date))
                date_ranges.append((mid_date, date_range[1]))
            else:
                # return results if # less than api limit
                date_range = date_ranges.pop()
                target_date_ranges.append(date_range)

        target_date_ranges += [i for i in date_ranges]

        results = []
        for date_range in target_date_ranges:
            sub_result, next_page, total = self._search(query, limit, 1, date_range[0], date_range[1])
            while next_page and len(sub_result) < FLICKR_API_LIMIT:
                max = limit
                more_results, next_page, total = self._search(query, max, next_page, date_range[0], date_range[1])
                sub_result += more_results

            sub_result = sub_result[:min(len(sub_result), FLICKR_API_LIMIT)]
            results += sub_result
            if len(results) > limit:
                break

        results = results[:min(len(results), limit)]

        return results


    def _do_oauth(self):
        request_token_url = self.host + "/oauth/request_token"
        authorization_url = self.host + "/oauth/authorize"
        access_token_url  = self.host + "/oauth/access_token"

        oauth_session = OAuth1Session(self.api_key[self.cur_api_key], client_secret=self.api_secret[self.cur_api_key], callback_uri="paste_this") # TODO: use 'oob'

        oauth_session.fetch_request_token(request_token_url)
        redirect_url = oauth_session.authorization_url(authorization_url)

        print "Flickr needs user authentication"
        print "--------------------------------"
        print "Visit this site:"
        # Flickr permissions:
        # read - permission to read private information
        # write - permission to add, edit and delete photo metadata (includes 'read')
        # delete - permission to delete photos (includes 'write' and 'read')
        print redirect_url+"&perms=write"

        redirect_response = raw_input('Paste the FULL URL here:')
        oauth_session.parse_authorization_response(redirect_response)

        oauth_session.fetch_access_token(access_token_url)
        with open(self.oauth_file, 'w') as f:
            pickle.dump(oauth_session, f)

        return oauth_session
